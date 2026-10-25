"""Sends FairShuffle's calls to the Spotify Web API and turns the replies into data or errors.

Every call goes through SpotifyAuth (auth/oauth.py), which adds the access token and handles a
401 by refreshing once. On top of that this client:

- waits and tries again on 429 (Retry-After, or backoff when Spotify gives no wait), but hands
  QUOTA_EXCEEDED and very long waits straight back as RateLimited, since waiting in the app
  won't help;
- backs off and tries again on 5xx and dropped connections, for reads only. A change such as a
  reorder is not idempotent: if the connection drops after Spotify applied it, sending it again
  would move the songs a second time. So a change is retried only when it surely never took
  effect (a 429, or a connection that never opened), and otherwise SpotifyUnavailable says it
  may have been applied, so the caller re-reads the playlist first;
- maps the rest: 403 to NotOwner for playlists and AccessDenied elsewhere, 400 and 404 to
  RequestRejected.

Log lines name the method and path with {id} in place of any ID, never the query string or a
body.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from typing import Any

import requests

from fairshuffle import __version__
from fairshuffle.auth.oauth import SignInRequired, SpotifyAuth
from fairshuffle.spotify.errors import (
    AccessDenied,
    NotOwner,
    RateLimited,
    RequestRejected,
    SpotifyError,
    SpotifyUnavailable,
)
from fairshuffle.spotify.ratelimit import (
    RetryPolicy,
    backoff_delay,
    quota_exceeded,
    retry_after_seconds,
)

API_BASE = "https://api.spotify.com/v1"
_READS = frozenset({"GET", "HEAD"})
_REASON = re.compile(r"[A-Z_]{1,40}")  # Spotify's reason codes, such as QUOTA_EXCEEDED
_ENCODED_STEP = re.compile(r"%(2e|2f|5c)", re.IGNORECASE)
# A segment after one of these names an ID, which is the user's own data (a user ID can be the
# account name), so log lines show {id} in its place.
_ID_SEGMENT = re.compile(
    r"/(albums|artists|audiobooks|chapters|episodes|playlists|shows|tracks|users)/[^/]+",
    re.IGNORECASE,
)

log = logging.getLogger(__name__)


def new_session() -> requests.Session:
    """The HTTP session FairShuffle uses for Spotify: certificate checks on, our own user agent."""
    session = requests.Session()
    session.headers["User-Agent"] = f"FairShuffle/{__version__}"
    return session


class SpotifyClient:
    """Calls the Spotify Web API for the signed-in user. Safe to share between worker threads."""

    def __init__(
        self,
        auth: SpotifyAuth,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._auth = auth
        self._policy = policy or RetryPolicy()
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311  # jitter, not security

    def end_sign_in(self) -> None:
        """Stop this client for good (see SpotifyAuth.end). Call it from a worker thread."""
        self._auth.end()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a path under /v1, such as "/me", and return the JSON reply."""
        return self.request("GET", path, params=params)

    def get_url(self, url: str) -> dict[str, Any]:
        """GET a full URL Spotify gave us.

        Not for paging: a "next" link can name a path FairShuffle didn't choose (it has pointed
        at /users/{user id}/...), which would then show in the log. Page by offset on a fixed
        path instead, as spotify/playlists.py does.
        """
        if not url.startswith(API_BASE + "/"):
            raise ValueError("Only Spotify Web API links can be followed.")
        return self.request("GET", url[len(API_BASE) :])

    def put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("PUT", path, body=body)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, body=body)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one call, retrying as the module docstring describes, and return its JSON."""
        _check_path(path)
        method = method.upper()
        is_read = method in _READS
        what = f"{method} {_log_route(path)}"
        for attempt in range(self._policy.max_attempts):
            last = attempt == self._policy.max_attempts - 1
            response = self._send(method, path, params, body, what, is_read, last)
            if response is None:  # a dropped connection that is safe to retry
                self._wait(backoff_delay(attempt, self._policy, self._rng), what, "no connection")
                continue
            status = response.status_code
            if status == 429:
                self._wait(self._rate_limit_wait(response, what, attempt, last), what, "429")
                continue
            if status >= 500:
                if not is_read:
                    raise SpotifyUnavailable(
                        f"Spotify had a problem ({status}) during a change, which may or may "
                        "not have been applied.",
                        may_have_applied=True,
                    )
                if last:
                    raise SpotifyUnavailable(f"Spotify keeps answering {status}. Try again later.")
                self._wait(backoff_delay(attempt, self._policy, self._rng), what, str(status))
                continue
            return self._read(response, path)
        raise AssertionError("unreachable")  # pragma: no cover  # the last attempt always ends

    def _send(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        body: dict[str, Any] | None,
        what: str,
        is_read: bool,
        last: bool,
    ) -> requests.Response | None:
        """Send once. None means the connection failed in a way that is safe to retry."""
        try:
            return self._auth.request(method, API_BASE + path, params=params, json=body)
        except requests.ConnectTimeout:
            failure, never_sent = "ConnectTimeout", True  # the connection never opened
        except requests.RequestException as error:
            failure, never_sent = type(error).__name__, False
        if (is_read or never_sent) and not last:
            log.info("%s failed (%s), trying again", what, failure)
            return None
        # Raised outside the except blocks, so the HTTP library's exception isn't carried along.
        raise SpotifyUnavailable(
            f"Couldn't reach Spotify ({failure}).", may_have_applied=not (is_read or never_sent)
        )

    def _rate_limit_wait(
        self, response: requests.Response, what: str, attempt: int, last: bool
    ) -> float:
        """How long to wait after a 429, or RateLimited when waiting here isn't worth it."""
        retry_after = retry_after_seconds(response)
        if quota_exceeded(response):
            raise RateLimited(
                "Spotify's request quota for this app is used up. Try again later.",
                retry_after,
                quota_exceeded=True,
            )
        if last or (retry_after is not None and retry_after > self._policy.max_retry_after):
            raise RateLimited(
                "Spotify asked FairShuffle to slow down. Try again in a little while.",
                retry_after,
                quota_exceeded=False,
            )
        if retry_after is None:
            log.info("%s got 429 with no Retry-After, backing off", what)
            return max(self._policy.base_delay, backoff_delay(attempt, self._policy, self._rng))
        return retry_after

    def _wait(self, seconds: float, what: str, reason: str) -> None:
        log.info("%s: waiting %.1f s after %s", what, seconds, reason)
        self._sleep(seconds)

    def _read(self, response: requests.Response, path: str) -> dict[str, Any]:
        try:
            return self._read_reply(response, path)
        except SpotifyError as error:
            error.reason = _reason_code(response)
            raise

    def _read_reply(self, response: requests.Response, path: str) -> dict[str, Any]:
        status = response.status_code
        if status == 401:  # still 401 after SpotifyAuth refreshed once
            raise SignInRequired("Spotify needs you to sign in again.")
        if status == 403:
            reason = _reason(response)
            if path.startswith("/playlists/"):
                raise NotOwner(
                    "You can only shuffle playlists you own or collaborate on" + reason + "."
                )
            raise AccessDenied(
                "Spotify refused access" + reason + ". In development mode, check that your "
                "account is on the app's User Management list."
            )
        if status >= 300:  # 3xx too: SpotifyAuth never follows a redirect
            raise RequestRejected(
                f"Spotify refused the request ({status}){_reason(response)}.", status
            )
        if status == 204 or not response.content:
            return {}
        data = _json_object(response)
        if data is None:
            raise SpotifyUnavailable("Spotify sent a reply FairShuffle doesn't understand.")
        return data


def _log_route(path: str) -> str:
    """The path as log lines show it: no query string, and {id} in place of each ID."""
    return _ID_SEGMENT.sub(r"/\1/{id}", path.partition("?")[0])


def _check_path(path: str) -> None:
    """Refuse a path that could leave /v1, forge a log line or name another host."""
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("The path must start with a single /, as in /me.")
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError("The path has control characters in it.")
    route = path.partition("?")[0]
    if "\\" in route or _ENCODED_STEP.search(route):  # a step up or a new segment once decoded
        raise ValueError("The path has a backslash or an encoded dot or slash in it.")
    if ".." in route.split("/"):
        raise ValueError("The path can't step up with '..'.")


def _json_object(response: requests.Response) -> dict[str, Any] | None:
    """The reply's JSON object, or None. The parse error is dropped here, not chained on, because
    it carries the whole response body."""
    try:
        data: Any = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _reason(response: requests.Response) -> str:
    """ " (REASON)" from Spotify's error object when it gives a well-formed reason code, else ""."""
    reason = _reason_code(response)
    return f" ({reason})" if reason else ""


def _reason_code(response: requests.Response) -> str | None:
    """Spotify's reason code from the error object when it is well-formed, else None."""
    if response.status_code < 300:
        return None
    try:
        body: Any = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    reason = error.get("reason") if isinstance(error, dict) else None
    return reason if isinstance(reason, str) and _REASON.fullmatch(reason) else None
