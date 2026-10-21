"""The signed-in user's playlists behind the picker window: loading and refreshing them.

Like the account, the Spotify calls run on a worker thread and the result comes back to the main
thread through a Qt signal. Each load bumps a generation number, so a list that arrives after
the user signed out, or after a newer Refresh, is dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import QObject, Signal

from fairshuffle.auth.oauth import SignInRequired, TokenError
from fairshuffle.auth.token_store import TokenStoreError
from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.errors import SpotifyError
from fairshuffle.spotify.models import Playlist
from fairshuffle.spotify.playlists import list_editable_playlists
from fairshuffle.spotify.profile import user_id
from fairshuffle.ui.account import (
    UNEXPECTED,
    AccountController,
    AccountState,
    AccountStatus,
    Runner,
    run_in_thread_pool,
)

log = logging.getLogger(__name__)

NO_USER_ID = "Spotify didn't say which account you are signed in with. Try Refresh."


class PlaylistsState(Enum):
    IDLE = auto()  # nothing loaded yet, or signed out
    LOADING = auto()
    READY = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class PlaylistsStatus:
    state: PlaylistsState
    # Playlist names are the user's own content, so they never show in repr or a log line.
    playlists: tuple[Playlist, ...] = field(default=(), repr=False)
    message: str | None = None  # why loading failed, from FairShuffle's own errors


@dataclass(frozen=True, slots=True)
class _Loaded:
    # The user ID and the playlist names are the user's own data, so neither shows in repr.
    owner_id: str | None = field(default=None, repr=False)
    playlists: tuple[Playlist, ...] = field(default=(), repr=False)
    message: str | None = None


class PlaylistController(QObject):
    """Loads the playlists FairShuffle can reorder for whoever is signed in."""

    status_changed = Signal(object)  # a PlaylistsStatus

    def __init__(
        self,
        account: AccountController,
        runner: Runner = run_in_thread_pool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._run = runner
        self._status = PlaylistsStatus(PlaylistsState.IDLE)
        self._owner_id: str | None = None  # the signed-in user's ID, once Spotify has said it
        self._generation = 0
        account.status_changed.connect(self._on_account_status)

    @property
    def status(self) -> PlaylistsStatus:
        return self._status

    def refresh(self) -> None:
        """Load the list again. While it loads, the last list stays on show."""
        client = self._account.client
        if client is None:
            self._forget()
            return
        self._generation += 1
        generation = self._generation
        owner_id = self._owner_id
        self._set(PlaylistsStatus(PlaylistsState.LOADING, self._status.playlists))
        self._run(lambda: _load(client, owner_id), lambda result: self._done(generation, result))

    def load_if_needed(self) -> None:
        """Load the list unless it is loaded or loading already."""
        if self._status.state in (PlaylistsState.IDLE, PlaylistsState.FAILED):
            self.refresh()

    def _done(self, generation: int, result: object) -> None:
        if generation != self._generation:  # signed out or refreshed since; this list is stale
            return
        if not isinstance(result, _Loaded):  # the job itself crashed; the runner logged it
            result = _Loaded(message=UNEXPECTED)
        if result.message is not None:
            failed = PlaylistsStatus(PlaylistsState.FAILED, self._status.playlists, result.message)
            self._set(failed)
            return
        self._owner_id = result.owner_id
        self._set(PlaylistsStatus(PlaylistsState.READY, result.playlists))

    def _on_account_status(self, status: AccountStatus) -> None:
        if status.state is not AccountState.SIGNED_IN:
            self._forget()

    def _forget(self) -> None:
        """Drop the list and the user ID, and any load still running."""
        self._generation += 1
        self._owner_id = None
        if self._status != PlaylistsStatus(PlaylistsState.IDLE):
            self._set(PlaylistsStatus(PlaylistsState.IDLE))

    def _set(self, status: PlaylistsStatus) -> None:
        self._status = status
        self.status_changed.emit(status)


def _load(client: SpotifyClient, owner_id: str | None) -> _Loaded:
    """Runs on a worker thread: the user's ID if not known yet, then their editable playlists."""
    try:
        owner_id = owner_id or user_id(client)
        if owner_id is None:
            return _Loaded(message=NO_USER_ID)
        return _Loaded(owner_id, tuple(list_editable_playlists(client, owner_id)))
    except (SignInRequired, SpotifyError, TokenError, TokenStoreError) as error:
        return _Loaded(message=str(error))
    except Exception as error:  # a bug of ours: a fixed sentence, the class name in the log
        log.error("Loading playlists failed (%s)", type(error).__name__)
        return _Loaded(message=UNEXPECTED)
