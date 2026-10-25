"""The True Shuffle toggle behind the tray menu (M6, P6-04).

The user listens to one of their playlists in the Spotify app as usual and ticks True Shuffle in
FairShuffle's tray menu. shuffle/session.py then carries that playlist on in a fair random order
in the Spotify app; unticking goes back to normal play. Like the account and shuffle controllers,
anything that talks to Spotify runs on Qt's thread pool and reports back through a signal, and a
generation number drops a result that arrives after the user moved on.

While it is on, a timer looks at Spotify once a minute. When the user has moved on to something
else in Spotify, the toggle unticks itself, so the menu never claims a true shuffle that isn't
playing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from fairshuffle.shuffle import session as true_shuffle
from fairshuffle.spotify import player
from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.errors import SignInRequired, SpotifyError
from fairshuffle.ui.account import (
    UNEXPECTED,
    AccountController,
    AccountState,
    AccountStatus,
    run_in_thread_pool,
)

WATCH_MS = 60_000  # how often to check that our order is still what Spotify plays
NEEDS_PLAYBACK_SIGN_IN = (
    'True Shuffle needs one more sign-in first: pick "Allow playback control" in the menu.'
)
NOT_SIGNED_IN = "Sign in to Spotify from the tray menu first."
START_FAILED = "True Shuffle couldn't start"
STOP_FAILED = "True Shuffle couldn't turn off"

log = logging.getLogger(__name__)

Runner = Callable[[Callable[[], Any], Callable[[Any], None]], None]


class ToggleState(Enum):
    OFF = auto()
    STARTING = auto()
    ON = auto()
    STOPPING = auto()


@dataclass(frozen=True)
class ToggleStatus:
    state: ToggleState
    message: str | None = field(default=None, repr=False)  # told to the user once, as a toast
    title: str | None = field(default=None, repr=False)
    warning: bool = False


@dataclass(frozen=True)
class _Failed:
    message: str


class TrueShuffleController(QObject):
    """Turns True Shuffle on and off for the playlist playing in the user's Spotify app."""

    status_changed = Signal(object)  # a ToggleStatus

    def __init__(
        self,
        account: AccountController,
        runner: Runner = run_in_thread_pool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._run = runner
        self._status = ToggleStatus(ToggleState.OFF)
        self._session: true_shuffle.Session | None = None
        self._generation = 0
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(WATCH_MS)
        self.watch_timer.timeout.connect(self._watch)
        account.status_changed.connect(self._on_account_status)

    @property
    def status(self) -> ToggleStatus:
        return self._status

    @property
    def session(self) -> true_shuffle.Session | None:
        """The true shuffle playing while the toggle is on; None otherwise."""
        return self._session

    def toggle(self, on: bool) -> None:
        """Turn True Shuffle on or off. Ignored while a change is already under way."""
        if self._status.state in (ToggleState.STARTING, ToggleState.STOPPING):
            return
        if on and self._status.state is ToggleState.OFF:
            self._start()
        elif not on and self._status.state is ToggleState.ON:
            self._stop()

    def _start(self) -> None:
        client = self._account.client
        account = self._account.status
        if client is None or account.state is not AccountState.SIGNED_IN:
            self._set(ToggleStatus(ToggleState.OFF, NOT_SIGNED_IN, START_FAILED, warning=True))
            return
        if not account.playback:
            self._set(
                ToggleStatus(ToggleState.OFF, NEEDS_PLAYBACK_SIGN_IN, START_FAILED, warning=True)
            )
            return
        self._begin(ToggleState.STARTING, lambda: _guarded(lambda: true_shuffle.start(client)))

    def _stop(self) -> None:
        client, session = self._account.client, self._session
        self.watch_timer.stop()
        if client is None or session is None:
            self._off()
            return
        self._begin(
            ToggleState.STOPPING, lambda: _guarded(lambda: true_shuffle.stop(client, session))
        )

    def _begin(self, state: ToggleState, job: Callable[[], object]) -> None:
        self._generation += 1
        generation = self._generation
        self._set(ToggleStatus(state))
        self._run(job, lambda result: self._done(generation, state, result))

    def _done(self, generation: int, state: ToggleState, result: object) -> None:
        if generation != self._generation:  # signed out or quit meanwhile; this is stale
            return
        if isinstance(result, _Failed):  # a failed stop leaves our order on; the toast says why
            title = STOP_FAILED if state is ToggleState.STOPPING else START_FAILED
            self._off(ToggleStatus(ToggleState.OFF, result.message, title, warning=True))
            return
        if state is ToggleState.STOPPING:
            self._off(ToggleStatus(ToggleState.OFF))
            return
        if not isinstance(result, true_shuffle.Session):  # the job itself crashed; pool logged it
            self._off(ToggleStatus(ToggleState.OFF, UNEXPECTED, START_FAILED, warning=True))
            return
        self._session = result
        self.watch_timer.start()
        self._set(ToggleStatus(ToggleState.ON, _started_text(result), "True Shuffle is on"))

    def _watch(self) -> None:
        """Untick when Spotify has moved on from our order. A failed look changes nothing."""
        client, session = self._account.client, self._session
        if client is None or session is None or self._status.state is not ToggleState.ON:
            return
        generation = self._generation
        self._run(
            lambda: _still_ours(client, session),
            lambda ours: self._watched(generation, ours),
        )

    def _watched(self, generation: int, ours: object) -> None:
        if generation != self._generation or ours is not False:
            return
        log.info("Spotify moved on from the true shuffle order; True Shuffle is off")
        self._off()

    def _on_account_status(self, status: AccountStatus) -> None:
        if status.state is not AccountState.SIGNED_IN and self._status.state is not ToggleState.OFF:
            self._generation += 1  # a start or stop under way loses its client anyway
            self._off()

    def _off(self, status: ToggleStatus | None = None) -> None:
        self.watch_timer.stop()
        self._session = None
        self._set(status or ToggleStatus(ToggleState.OFF))

    def _set(self, status: ToggleStatus) -> None:
        self._status = status
        self.status_changed.emit(status)


def _guarded(work: Callable[[], object]) -> object:
    """Run work on the worker; a Spotify error becomes its message, anything else a fixed one."""
    try:
        return work()
    except SignInRequired:
        return _Failed("Spotify needs you to sign in again.")
    except SpotifyError as error:
        return _Failed(str(error))
    except Exception as error:  # a bug of ours: logged by class only, never with data
        log.error("True Shuffle failed (%s)", type(error).__name__)
        return _Failed(UNEXPECTED)


def _still_ours(client: SpotifyClient, session: true_shuffle.Session) -> bool | None:
    """True or False once Spotify says what it plays; None when it couldn't be asked."""
    try:
        state = player.playback_state(client)
    except SpotifyError:
        return None
    return true_shuffle.is_ours(state, session)


def _started_text(session: true_shuffle.Session) -> str:
    songs = len(session.order)
    text = (
        f"{songs} {'song' if songs == 1 else 'songs'} in a fair random order. Next and Previous "
        "in Spotify follow it."
    )
    if session.left_for_later:
        text += (
            f" The other {session.left_for_later} wait for next time: tick True Shuffle again "
            "for a fresh pick."
        )
    if session.skipped:
        text += (
            f" {session.skipped} local or unavailable "
            f"{'song was' if session.skipped == 1 else 'songs were'} left out."
        )
    if not session.confirmed:
        text += " Spotify hasn't confirmed it yet; if another order plays, tick True Shuffle again."
    return text
