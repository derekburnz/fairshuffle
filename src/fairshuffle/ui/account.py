"""The Spotify account behind the tray menu: resume at start, sign in, sign out.

Anything that talks to Spotify or waits on the browser runs on a worker thread from Qt's thread
pool, and its result comes back to the main thread through a Qt signal, so the tray stays
responsive. The networking analogy from docs/architecture.md: the main thread is the control
plane, the workers are the data plane.

All state lives on the main thread. Each action bumps a generation number, so a result that
arrives after the user moved on (a resume that finishes after Sign out, say) is dropped.

Messages shown to the user come from FairShuffle's own errors, which never quote a token. An
error nobody planned for is shown as a fixed sentence and logged by class name only.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from fairshuffle.auth.loopback import CallbackError, ListenerCancelled
from fairshuffle.auth.oauth import SignInRequired, SpotifyAuth, TokenError
from fairshuffle.auth.sign_in import BrowserNotOpened, BrowserSignIn
from fairshuffle.auth.token_store import TokenStoreError, delete_refresh_token
from fairshuffle.config import ConfigError, SpotifySettings, load_settings
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.errors import AccessDenied, SpotifyError, SpotifyUnavailable
from fairshuffle.spotify.profile import display_name

log = logging.getLogger(__name__)

UNEXPECTED = "Something went wrong talking to Spotify. Try again, and check the log if it repeats."
SHUTDOWN_WAIT_MS = 5000  # how long Quit waits for a Spotify task to wrap up


class AccountState(Enum):
    CHECKING = auto()  # looking for a saved sign-in at start
    SIGNED_OUT = auto()
    SIGNING_IN = auto()  # waiting for the user in the browser
    SIGNED_IN = auto()
    SIGN_IN_AGAIN = auto()  # Spotify ended the saved sign-in (six months, or revoked)
    SETUP_NEEDED = auto()  # no Client ID in .env yet
    UNAVAILABLE = auto()  # Spotify or Credential Manager couldn't be reached


@dataclass(frozen=True, slots=True)
class AccountStatus:
    state: AccountState
    # Both can hold the display name, a personal detail, so neither shows in repr or a log line.
    name: str | None = field(default=None, repr=False)  # only when signed in and Spotify gave one
    message: str | None = field(default=None, repr=False)  # told to the user once, as a toast


@dataclass(frozen=True, slots=True)
class _Outcome:
    status: AccountStatus
    client: SpotifyClient | None = None
    http: requests.Session | None = None


Runner = Callable[[Callable[[], Any], Callable[[Any], None]], None]


class _Relay(QObject):
    finished = Signal(object)


class _Task(QRunnable):
    def __init__(self, job: Callable[[], Any], relay: _Relay) -> None:
        super().__init__()
        self._job = job
        self._relay = relay

    def run(self) -> None:
        try:
            result = self._job()
        except Exception as error:  # a job's own bug must still reach the main thread
            log.error("Account task failed (%s)", type(error).__name__)
            result = _Outcome(AccountStatus(AccountState.UNAVAILABLE, message=UNEXPECTED))
        self._relay.finished.emit(result)  # queued over to the main thread


_relays: set[_Relay] = set()  # keeps each relay alive until its result has been delivered


def run_in_thread_pool(job: Callable[[], Any], done: Callable[[Any], None]) -> None:
    """Run job on Qt's thread pool and call done with its result on the main thread."""
    relay = _Relay()
    _relays.add(relay)

    def deliver(result: Any) -> None:
        _relays.discard(relay)
        done(result)

    relay.finished.connect(deliver)
    QThreadPool.globalInstance().start(_Task(job, relay))


def wait_for_thread_pool(milliseconds: int) -> bool:
    """Drop jobs that haven't started, then wait for running ones. True if all finished."""
    pool = QThreadPool.globalInstance()
    pool.clear()
    return pool.waitForDone(milliseconds)


class AccountController(QObject):
    """Keeps track of the Spotify sign-in and does the work behind the tray's account items."""

    status_changed = Signal(object)  # an AccountStatus

    def __init__(
        self,
        settings_loader: Callable[[], SpotifySettings] = load_settings,
        session_factory: Callable[[], requests.Session] = new_session,
        open_browser: Callable[[str], bool] = webbrowser.open,
        runner: Runner = run_in_thread_pool,
        wait_for_jobs: Callable[[int], bool] = wait_for_thread_pool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_loader = settings_loader
        self._session_factory = session_factory
        self._open_browser = open_browser
        self._run = runner
        self._wait_for_jobs = wait_for_jobs
        # Set at Quit. The one thing workers read: it cuts short the client's waits between
        # retries, so a job doesn't keep the app alive after the icon has gone.
        self._stopping = threading.Event()
        self._status = AccountStatus(AccountState.CHECKING)
        self._client: SpotifyClient | None = None
        self._http: requests.Session | None = None
        self._sign_in: BrowserSignIn | None = None
        self._generation = 0

    @property
    def status(self) -> AccountStatus:
        return self._status

    @property
    def client(self) -> SpotifyClient | None:
        """The Web API client while signed in, for the playlist features (M3)."""
        return self._client

    def start(self) -> None:
        """Look for a saved sign-in and resume it without opening the browser."""
        self._begin(AccountState.CHECKING, self._resume)

    def sign_in(self) -> None:
        """Open the browser to sign in. A sign-in already in progress is left alone."""
        if self._status.state is AccountState.SIGNING_IN:
            return
        try:
            settings = self._settings_loader()
        except ConfigError as error:
            self._set(AccountStatus(AccountState.SETUP_NEEDED, message=str(error)))
            return
        http = self._session_factory()
        attempt = BrowserSignIn(http, settings, self._open_browser)
        self._sign_in = attempt
        self._begin(AccountState.SIGNING_IN, lambda: self._finish_sign_in(attempt, http))

    def cancel_sign_in(self) -> None:
        if self._sign_in is not None:
            self._sign_in.cancel()

    def sign_out(self) -> None:
        """Forget the sign-in here and remove it from Credential Manager."""
        self.cancel_sign_in()
        old = self._client  # a worker (a playlist load, say) may still be using it
        self._begin(AccountState.CHECKING, lambda: self._forget(old))

    def shutdown(self) -> None:
        """Stop any sign-in and wait briefly for running jobs, before the app lets go of its
        single-instance lock. Otherwise a relaunch could run while this copy is still saving a
        new refresh token."""
        self._stopping.set()
        self._generation += 1
        self.cancel_sign_in()
        self._drop_client()
        if not self._wait_for_jobs(SHUTDOWN_WAIT_MS):
            log.warning("A Spotify task was still running at quit")

    def _begin(self, state: AccountState, job: Callable[[], _Outcome]) -> None:
        self._generation += 1
        generation = self._generation
        self._drop_client()
        self._set(AccountStatus(state))
        self._run(job, lambda outcome: self._done(generation, outcome))

    def _done(self, generation: int, outcome: _Outcome) -> None:
        if generation != self._generation:  # the user moved on; this result is stale
            if outcome.http is not None:
                outcome.http.close()
            return
        self._sign_in = None
        self._client, self._http = outcome.client, outcome.http
        self._set(outcome.status)

    def _set(self, status: AccountStatus) -> None:
        self._status = status
        self.status_changed.emit(status)

    def _drop_client(self) -> None:
        if self._http is not None:
            self._http.close()
        self._client, self._http = None, None

    # The jobs below run on a worker thread. Apart from the _stopping event they touch no
    # controller state.

    def _resume(self) -> _Outcome:
        try:
            settings = self._settings_loader()
        except ConfigError:
            return _Outcome(AccountStatus(AccountState.SETUP_NEEDED))  # no notice at start
        http = self._session_factory()
        return _closing(http, lambda: self._resume_with(settings, http))

    def _resume_with(self, settings: SpotifySettings, http: requests.Session) -> _Outcome:
        try:
            auth = SpotifyAuth.from_store(http, settings)
        except SignInRequired:
            return _Outcome(AccountStatus(AccountState.SIGN_IN_AGAIN))
        except (TokenError, TokenStoreError) as error:
            return _Outcome(AccountStatus(AccountState.UNAVAILABLE, message=str(error)))
        if auth is None:
            return _Outcome(AccountStatus(AccountState.SIGNED_OUT))
        return self._signed_in(auth, http, notify=False)

    def _finish_sign_in(self, attempt: BrowserSignIn, http: requests.Session) -> _Outcome:
        return _closing(http, lambda: self._sign_in_with(attempt, http))

    def _sign_in_with(self, attempt: BrowserSignIn, http: requests.Session) -> _Outcome:
        try:
            auth = attempt.run()
        except ListenerCancelled:
            return _Outcome(AccountStatus(AccountState.SIGNED_OUT))
        except (
            CallbackError,
            BrowserNotOpened,
            SignInRequired,
            TokenError,
            TokenStoreError,
        ) as error:
            return _Outcome(AccountStatus(AccountState.SIGNED_OUT, message=str(error)))
        return self._signed_in(auth, http, notify=True)

    def _signed_in(self, auth: SpotifyAuth, http: requests.Session, notify: bool) -> _Outcome:
        client = SpotifyClient(auth, sleep=self._pause)
        message = None
        try:
            name = display_name(client)
        except SignInRequired:
            return _Outcome(AccountStatus(AccountState.SIGN_IN_AGAIN))
        except (AccessDenied, TokenError, TokenStoreError) as error:
            # Signed in, but the user should hear why: usually the account is missing from User
            # Management (AccessDenied), or a refresh or saving its new token failed.
            name, message = None, str(error)
        except SpotifyError:
            name = None  # signed in all the same; the name can wait for the next start
        if notify and message is None:
            message = f"Signed in as {name}." if name else "Signed in to Spotify."
        status = AccountStatus(AccountState.SIGNED_IN, name=name, message=message)
        return _Outcome(status, client, http)

    def _pause(self, seconds: float) -> None:
        """The client's wait between retries, cut short when the app quits."""
        if self._stopping.wait(seconds):
            raise SpotifyUnavailable("FairShuffle is closing.")

    def _forget(self, old: SpotifyClient | None) -> _Outcome:
        if old is not None:
            # First, so a refresh another worker is in the middle of can't save a new token
            # after the delete below and quietly sign this account back in at the next start.
            old.end_sign_in()
        try:
            delete_refresh_token()
        except TokenStoreError as error:  # signed out here, but the entry is still saved
            return _Outcome(AccountStatus(AccountState.SIGNED_OUT, message=str(error)))
        log.info("Signed out of Spotify")
        return _Outcome(AccountStatus(AccountState.SIGNED_OUT, message="Signed out of Spotify."))


def _closing(http: requests.Session, work: Callable[[], _Outcome]) -> _Outcome:
    """Run work, then close http unless the outcome keeps it, even if work raises."""
    try:
        outcome = work()
    except BaseException:
        http.close()
        raise
    if outcome.http is not http:
        http.close()
    return outcome
