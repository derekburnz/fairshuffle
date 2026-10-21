"""Talks to Spotify's token endpoint: turns the sign-in code into tokens and refreshes them.

Sign-in is Authorization Code with PKCE, so there is no client secret anywhere: the app proves
it started the sign-in by sending the code verifier only it knows (see pkce.py). The steps are:

1. authorize_url() builds the Spotify page the browser opens.
2. The loopback listener catches the code Spotify sends back (see loopback.py).
3. SpotifyAuth.from_code() swaps the code for tokens and saves the refresh token.
4. SpotifyAuth.request() sends API calls with the access token, refreshing it when it runs out
   or when Spotify answers 401, then trying the call once more.

A refresh token lasts six months from the first sign-in and refreshing does not extend that.
When Spotify stops accepting it, the token endpoint answers 400 invalid_grant: that is never
retried, the stored token is removed and SignInRequired tells the app to ask the user to sign in.

Every code, verifier and token is registered with mask_secret() before anything else is done
with it, errors quote only Spotify's short error code, and no error carries along the HTTP
library's own exception, whose message could hold request details.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from fairshuffle.auth.pkce import CHALLENGE_METHOD, PkceRequest, check_code_verifier
from fairshuffle.auth.token_store import (
    TokenStoreError,
    delete_refresh_token,
    load_refresh_token,
    save_refresh_token,
)
from fairshuffle.config import SpotifySettings
from fairshuffle.storage.logging_setup import mask_secret

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
API_HOST = "api.spotify.com"
TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105  # a URL, not a password
# Read the user's own and collaborative playlists, then write the new order back.
SCOPES = (
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
)
TIMEOUT_SECONDS = 15
# Refresh a minute early, so a token never runs out between the check and the call.
EXPIRY_MARGIN_SECONDS = 60
_ERROR_CODE = re.compile(r"[a-z_]{1,40}")  # OAuth error codes are short snake_case words

log = logging.getLogger(__name__)


class SignInRequired(Exception):
    """Spotify no longer accepts this sign-in. The user has to sign in again in the browser."""


class TokenError(Exception):
    """The token endpoint couldn't be reached or gave an unusable reply. Never quotes a token."""


@dataclass(frozen=True, slots=True)
class Tokens:
    """One reply from the token endpoint. Both tokens are left out of repr."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    scope: frozenset[str]


def authorize_url(settings: SpotifySettings, request: PkceRequest) -> str:
    """The Spotify sign-in page for this attempt, with the challenge and state in it."""
    query = {
        "client_id": settings.client_id,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "code_challenge_method": CHALLENGE_METHOD,
        "code_challenge": request.challenge,
        "state": request.state,
        "scope": " ".join(SCOPES),
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def exchange_code(
    http: requests.Session, settings: SpotifySettings, code: str, verifier: str
) -> Tokens:
    """Swap the code from the callback for an access token and a refresh token."""
    mask_secret(code)
    mask_secret(verifier)
    check_code_verifier(verifier)
    reply = _post_token(
        http,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "client_id": settings.client_id,
            "code_verifier": verifier,
        },
    )
    return _read_tokens(reply, earlier_refresh_token=None)


def refresh_tokens(http: requests.Session, settings: SpotifySettings, refresh_token: str) -> Tokens:
    """Get a new access token. Spotify may also send a new refresh token; if not, keep this one."""
    mask_secret(refresh_token)
    reply = _post_token(
        http,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.client_id,
        },
    )
    return _read_tokens(reply, earlier_refresh_token=refresh_token)


def check_session(http: requests.Session) -> None:
    """Refuse a session that has certificate checks turned off, since tokens travel over it."""
    if http.verify is not True:
        raise ValueError("Sign-in needs a session that checks Spotify's certificate.")


def _post_token(http: requests.Session, form: dict[str, str]) -> dict[str, Any]:
    """POST the form to the token endpoint and return the JSON reply, or raise."""
    check_session(http)
    try:
        # No redirects: the form holds a code or a refresh token, so it only ever goes to Spotify.
        response = http.post(
            TOKEN_URL,
            data=form,
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        failure = type(error).__name__
    else:
        return _read_reply(response)
    raise TokenError(f"Couldn't reach Spotify's sign-in service ({failure}).")


def _read_reply(response: requests.Response) -> dict[str, Any]:
    body = _json_object(response)
    if response.status_code == 200 and body is not None:
        return body
    error = body.get("error") if body is not None else None
    code = error if isinstance(error, str) and _ERROR_CODE.fullmatch(error) else None
    if response.status_code == 400 and code == "invalid_grant":
        raise SignInRequired("Spotify needs you to sign in again.")
    detail = code or "no error code"
    raise TokenError(f"Spotify's sign-in service answered {response.status_code} ({detail}).")


def _json_object(response: requests.Response) -> dict[str, Any] | None:
    try:
        body = response.json()
    except ValueError:  # not JSON at all, for example an HTML error page
        return None
    return body if isinstance(body, dict) else None


def _read_tokens(reply: dict[str, Any], earlier_refresh_token: str | None) -> Tokens:
    access_token = reply.get("access_token")
    refresh_token = reply.get("refresh_token") or earlier_refresh_token
    # Mask before checking anything else, so even a reply we refuse can't leak a token.
    for token in (access_token, refresh_token):
        if isinstance(token, str) and token:
            mask_secret(token)
    if not isinstance(access_token, str) or not access_token:
        raise TokenError("Spotify's sign-in reply had no access token.")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise TokenError("Spotify's sign-in reply had no refresh token.")
    token_type = reply.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise TokenError("Spotify's sign-in reply had an unexpected token type.")
    expires_in = reply.get("expires_in")
    if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
        raise TokenError("Spotify's sign-in reply had no usable expiry time.")
    scope = reply.get("scope")
    return Tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        scope=frozenset(scope.split()) if isinstance(scope, str) else frozenset(),
    )


def _check_api_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != API_HOST:
        raise ValueError(f"API calls only go to https://{API_HOST}.")


class SpotifyAuth:
    """The sign-in for one run of the app: hands out a current access token and refreshes it.

    The access token lives only in this object's memory. The refresh token is also saved to
    Credential Manager whenever Spotify sends a new one, so the next run starts signed in.
    """

    def __init__(
        self,
        http: requests.Session,
        settings: SpotifySettings,
        tokens: Tokens,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        check_session(http)
        self._http = http
        self._settings = settings
        self._clock = clock
        self._tokens = tokens
        self._expires_at = self._deadline(tokens)
        # Worker threads share one sign-in. Spotify may rotate the refresh token on each refresh,
        # so two refreshes at once could spend the old one twice and end the sign-in.
        self._lock = threading.RLock()
        self._signed_out = False  # set once Spotify ends the sign-in, so no thread asks again

    def __repr__(self) -> str:
        return f"{type(self).__name__}(scope={sorted(self._tokens.scope)!r})"

    @classmethod
    def from_code(
        cls,
        http: requests.Session,
        settings: SpotifySettings,
        code: str,
        verifier: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> SpotifyAuth:
        """Finish a browser sign-in: swap the code for tokens and save the refresh token."""
        tokens = exchange_code(http, settings, code, verifier)
        save_refresh_token(tokens.refresh_token)
        log.info("Signed in to Spotify")
        return cls(http, settings, tokens, clock)

    @classmethod
    def from_store(
        cls,
        http: requests.Session,
        settings: SpotifySettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> SpotifyAuth | None:
        """Resume the saved sign-in, or None if there is none. SignInRequired if it expired."""
        refresh_token = load_refresh_token()
        if refresh_token is None:
            return None
        tokens = cls._refresh_or_forget(http, settings, refresh_token)
        if tokens.refresh_token != refresh_token:
            save_refresh_token(tokens.refresh_token)
        log.info("Resumed the saved Spotify sign-in")
        return cls(http, settings, tokens, clock)

    @property
    def scope(self) -> frozenset[str]:
        return self._tokens.scope

    def access_token(self) -> str:
        """A current access token, refreshed first if it has run out or is about to."""
        with self._lock:
            if self._clock() >= self._expires_at:
                self._refresh()
            return self._tokens.access_token

    def refresh(self) -> None:
        """Get a new access token now. Raises SignInRequired if Spotify ended the sign-in."""
        with self._lock:
            self._refresh()

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Send one API call with the access token. On a 401, refresh once and send it again.

        The token only ever goes to https://api.spotify.com, so a bad URL (a paging link from
        somewhere unexpected, say) can't send it to another host or over plain http.
        """
        _check_api_url(url)
        if kwargs.get("verify", True) is not True:
            raise ValueError("API calls always check Spotify's certificate.")
        sent_with = self.access_token()
        response = self._send(method, url, sent_with, kwargs)
        if response.status_code != 401:
            return response
        log.info("Spotify answered 401, so refreshing the access token and trying once more")
        response.close()
        with self._lock:
            if self._tokens.access_token == sent_with:  # another thread may have refreshed already
                self._refresh()
            token = self._tokens.access_token
        return self._send(method, url, token, kwargs)

    def _send(self, method: str, url: str, token: str, kwargs: dict[str, Any]) -> requests.Response:
        headers = {**(kwargs.get("headers") or {}), "Authorization": f"Bearer {token}"}
        options = {"timeout": TIMEOUT_SECONDS, **kwargs, "headers": headers}
        return self._http.request(method, url, **options)

    def _refresh(self) -> None:
        """Refresh while holding the lock, so two threads never spend the same refresh token."""
        if self._signed_out:
            raise SignInRequired("Spotify needs you to sign in again.")
        old = self._tokens.refresh_token
        try:
            self._tokens = self._refresh_or_forget(self._http, self._settings, old)
        except SignInRequired:
            self._signed_out = True
            raise
        self._expires_at = self._deadline(self._tokens)
        if self._tokens.refresh_token != old:
            save_refresh_token(self._tokens.refresh_token)
        log.info("Refreshed the Spotify access token")

    def _deadline(self, tokens: Tokens) -> float:
        return self._clock() + max(tokens.expires_in - EXPIRY_MARGIN_SECONDS, 0)

    @staticmethod
    def _refresh_or_forget(
        http: requests.Session, settings: SpotifySettings, refresh_token: str
    ) -> Tokens:
        """Refresh, and if Spotify says the sign-in is over, remove the saved token first."""
        try:
            return refresh_tokens(http, settings, refresh_token)
        except SignInRequired:
            pass
        try:
            delete_refresh_token()
        except TokenStoreError:  # the user must still be sent back to sign in
            log.warning("Spotify ended the saved sign-in, but it couldn't be removed")
        else:
            log.info("Spotify ended the saved sign-in, so it was removed")
        raise SignInRequired("Spotify needs you to sign in again.")
