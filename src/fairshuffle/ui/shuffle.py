"""Runs a shuffle or an Undo for the picker window, one at a time, off the main thread.

The runner (shuffle/runner.py) does the work on a worker thread and never raises. This
controller starts it with the signed-in client, passes its progress back to the main thread
through a Qt signal, and says how it ended with finished. The picker turns that into dialogs
and status lines, and the tray icon turns a finished shuffle into the completion notice.

The "Keep date added (slower)" choice (P4-4) lives here so it is remembered between runs.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import QObject, Signal

from fairshuffle.shuffle.runner import (
    UNEXPECTED,
    Mode,
    Options,
    Outcome,
    Result,
    shuffle_playlist,
    undo_last_shuffle,
)
from fairshuffle.spotify.cache import PlaylistItemsCache
from fairshuffle.spotify.models import Playlist
from fairshuffle.storage import backups, settings
from fairshuffle.ui.account import (
    AccountController,
    AccountState,
    AccountStatus,
    Runner,
    run_in_thread_pool,
    wait_for_thread_pool,
)

log = logging.getLogger(__name__)

SHUTDOWN_WAIT_MS = 10_000  # how long Quit waits for a shuffle to stop before signing out


class Action(Enum):
    SHUFFLE = auto()
    UNDO = auto()


@dataclass(frozen=True)
class Progress:
    """A run under way: which playlist, and how many of its writes Spotify has confirmed."""

    action: Action
    playlist: Playlist = field(repr=False)  # the name is the user's own data
    done: int = 0
    total: int = 0


@dataclass(frozen=True)
class Finished:
    action: Action
    playlist: Playlist = field(repr=False)
    mode: Mode
    outcome: Outcome


class _Relay(QObject):
    """Carries progress from the worker thread; Qt queues the signal over to the main thread."""

    progress = Signal(int, int)


class ShuffleController(QObject):
    """Starts shuffles and Undos for the picker and reports how they go."""

    running_changed = Signal(object)  # a Progress while a run is under way, None once it ends
    finished = Signal(object)  # a Finished

    def __init__(
        self,
        account: AccountController,
        cache: PlaylistItemsCache | None = None,
        runner: Runner = run_in_thread_pool,
        wait_for_jobs: Callable[[int], bool] = wait_for_thread_pool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._cache = cache if cache is not None else PlaylistItemsCache()
        self._run = runner
        self._wait_for_jobs = wait_for_jobs
        self._settings = settings.load()
        self._running: Progress | None = None
        self._cancel: threading.Event | None = None
        self._relay = _Relay(self)
        self._relay.progress.connect(self._on_progress)
        account.status_changed.connect(self._on_account_status)

    @property
    def keep_date_added(self) -> bool:
        return self._settings.keep_date_added

    def set_keep_date_added(self, keep: bool) -> None:
        if keep != self._settings.keep_date_added:
            self._settings = settings.Settings(keep_date_added=keep)
            settings.save(self._settings)

    @property
    def mode(self) -> Mode:
        """The mode the "Keep date added" choice picks for the next run."""
        return Mode.KEEP_ORDER if self._settings.keep_date_added else Mode.FAST

    @property
    def running(self) -> Progress | None:
        return self._running

    def has_backup(self, playlist_id: str) -> bool:
        """True when Undo has something to put back for this playlist."""
        try:
            return backups.newest(playlist_id) is not None
        except ValueError:  # not a Spotify ID, so FairShuffle never backed it up
            return False

    def shuffle(
        self, playlist: Playlist, mode: Mode | None = None, allowed_losses: int = 0
    ) -> bool:
        """Start shuffling playlist. False if a run is already going or nobody is signed in."""
        return self._start(Action.SHUFFLE, playlist, mode or self.mode, allowed_losses)

    def undo(self, playlist: Playlist, mode: Mode | None = None, allowed_losses: int = 0) -> bool:
        """Start putting back the newest backup of playlist. False if that can't start now."""
        return self._start(Action.UNDO, playlist, mode or self.mode, allowed_losses)

    def cancel(self) -> None:
        """Ask the run to stop. Keep-order mode stops between moves; fast mode only before its
        first write, because stopping halfway would leave the playlist short."""
        if self._cancel is not None:
            self._cancel.set()

    def shutdown(self) -> None:
        """At Quit: ask any run to stop and give it a moment, before the account closes the
        connection it is using."""
        if self._running is None:
            return
        self.cancel()
        if not self._wait_for_jobs(SHUTDOWN_WAIT_MS):
            log.warning("A shuffle was still running at quit")

    def _start(self, action: Action, playlist: Playlist, mode: Mode, allowed_losses: int) -> bool:
        client = self._account.client
        if self._running is not None or client is None:
            return False
        cancel = threading.Event()
        options = Options(
            allowed_losses=allowed_losses, cancel=cancel, progress=self._relay.progress.emit
        )
        work = shuffle_playlist if action is Action.SHUFFLE else undo_last_shuffle
        cache = self._cache
        self._cancel = cancel
        self._set_running(Progress(action, playlist))
        log.info("%s started (%s)", action.name.capitalize(), mode.name.lower())
        self._run(
            lambda: work(client, cache, playlist.id, mode, options),
            lambda outcome: self._done(action, playlist, mode, outcome),
        )
        return True

    def _done(self, action: Action, playlist: Playlist, mode: Mode, outcome: object) -> None:
        if not isinstance(outcome, Outcome):  # the job itself crashed; the pool logged it
            outcome = Outcome(Result.FAILED, changed=True, message=UNEXPECTED)
        self._cancel = None
        self._set_running(None)
        self.finished.emit(Finished(action, playlist, mode, outcome))

    def _on_progress(self, done: int, total: int) -> None:
        if self._running is not None:
            self._set_running(Progress(self._running.action, self._running.playlist, done, total))

    def _on_account_status(self, status: AccountStatus) -> None:
        if status.state is not AccountState.SIGNED_IN:
            self.cancel()  # signing out closes the run's connection anyway; stop it cleanly
            self._cache.clear()

    def _set_running(self, progress: Progress | None) -> None:
        self._running = progress
        self.running_changed.emit(progress)
