"""One browser sign-in, start to finish: PKCE values, listener, browser, code exchange.

This runs on a worker thread, never Qt's main thread, because it waits up to five minutes for
the user to approve the sign-in in the browser. cancel() can be called from any thread.

The order matters. The listener binds to 127.0.0.1 before the browser opens, so Spotify's reply
can't arrive before anything is listening, and a port already in use is reported before the user
has done anything in the browser.
"""

from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable

import requests

from fairshuffle.auth.loopback import (
    DEFAULT_TIMEOUT_SECONDS,
    ListenerCancelled,
    LoopbackListener,
)
from fairshuffle.auth.oauth import SpotifyAuth, authorize_url
from fairshuffle.auth.pkce import PkceRequest
from fairshuffle.auth.token_store import delete_refresh_token
from fairshuffle.config import SpotifySettings


class BrowserNotOpened(Exception):
    """Windows couldn't open a browser for the sign-in page."""


class BrowserSignIn:
    """One sign-in attempt. Make a new one for each attempt."""

    def __init__(
        self,
        http: requests.Session,
        settings: SpotifySettings,
        open_browser: Callable[[str], bool] = webbrowser.open,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._http = http
        self._settings = settings
        self._open_browser = open_browser
        self._timeout = timeout
        self._lock = threading.Lock()
        self._listener: LoopbackListener | None = None
        self._cancelled = False

    def run(self) -> SpotifyAuth:
        """Sign in and return the new sign-in. Raises the listener's or token endpoint's errors."""
        request = PkceRequest.new()
        with LoopbackListener(self._settings.redirect, request.state) as listener:
            with self._lock:
                if self._cancelled:
                    raise ListenerCancelled("Sign-in was cancelled.")
                self._listener = listener
            if not self._open_browser(authorize_url(self._settings, request)):
                raise BrowserNotOpened(
                    "Windows couldn't open your web browser for the Spotify sign-in page."
                )
            code = listener.wait(self._timeout)
        self._stop_if_cancelled()  # a Cancel that came just after the callback still counts
        auth = SpotifyAuth.from_code(self._http, self._settings, code, request.verifier)
        try:
            self._stop_if_cancelled()  # a Cancel during the exchange undoes the saved sign-in
        except ListenerCancelled:
            delete_refresh_token()
            raise
        return auth

    def _stop_if_cancelled(self) -> None:
        with self._lock:
            if self._cancelled:
                raise ListenerCancelled("Sign-in was cancelled.")

    def cancel(self) -> None:
        """Stop waiting for the browser. Safe from any thread, before or during run()."""
        with self._lock:
            self._cancelled = True
            if self._listener is not None:
                self._listener.cancel()
