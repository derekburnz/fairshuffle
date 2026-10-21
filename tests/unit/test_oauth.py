"""The token endpoint calls and the 401 refresh, against fake Spotify replies (responses, P2-2)."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable, Iterator
from urllib.parse import parse_qs, urlsplit

import keyring
import pytest
import requests
import responses
from responses import matchers

from fairshuffle.auth import oauth
from fairshuffle.auth.oauth import (
    SignInRequired,
    SpotifyAuth,
    TokenError,
    Tokens,
    authorize_url,
    exchange_code,
    refresh_tokens,
)
from fairshuffle.auth.pkce import PkceRequest
from fairshuffle.config import SpotifySettings, load_settings
from fairshuffle.storage import logging_setup

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1/me"
FAKE_CODE = "fake-authorization-code"
FAKE_VERIFIER = "fake-code-verifier-" + "v" * 30  # 49 unreserved characters, a valid length
FAKE_ACCESS = "fake-access-token-1"
FAKE_ACCESS_2 = "fake-access-token-2"
FAKE_REFRESH = "fake-refresh-token-for-tests"
FAKE_REFRESH_2 = "fake-refresh-token-rotated"
ALL_FAKES = (FAKE_CODE, FAKE_VERIFIER, FAKE_ACCESS, FAKE_ACCESS_2, FAKE_REFRESH, FAKE_REFRESH_2)


def token_reply(access: str = FAKE_ACCESS, refresh: str | None = FAKE_REFRESH, **extra: object):
    body: dict[str, object] = {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "playlist-read-private playlist-modify-private",
    }
    if refresh is not None:
        body["refresh_token"] = refresh
    body.update(extra)
    return body


def form_of(call: responses.Call) -> dict[str, str]:
    body = call.request.body
    text = body.decode() if isinstance(body, bytes) else str(body)
    return {key: values[0] for key, values in parse_qs(text).items()}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def spotify() -> Iterator[responses.RequestsMock]:
    """Fake Spotify. Any request it was not told to expect fails the test."""
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture
def http() -> Iterator[requests.Session]:
    with requests.Session() as session:
        yield session


@pytest.fixture
def settings() -> SpotifySettings:
    return load_settings()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def stored() -> str | None:
    return keyring.get_password("FairShuffle", "spotify-refresh-token")


# The sign-in page


def test_the_authorize_url_asks_for_a_pkce_code_with_our_scopes(settings: SpotifySettings) -> None:
    request = PkceRequest.new()

    url = urlsplit(authorize_url(settings, request))
    query = {key: values[0] for key, values in parse_qs(url.query).items()}

    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.spotify.com/authorize"
    assert query == {
        "client_id": "fake-client-id-for-tests",
        "response_type": "code",
        "redirect_uri": "http://127.0.0.1:8888/callback",
        "code_challenge_method": "S256",
        "code_challenge": request.challenge,
        "state": request.state,
        "scope": " ".join(oauth.SCOPES),
    }
    assert request.verifier not in url.geturl()


# Swapping the code for tokens


def test_the_code_is_exchanged_for_tokens(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, json=token_reply())

    tokens = exchange_code(http, settings, FAKE_CODE, FAKE_VERIFIER)

    assert tokens == Tokens(
        access_token=FAKE_ACCESS,
        refresh_token=FAKE_REFRESH,
        expires_in=3600,
        scope=frozenset({"playlist-read-private", "playlist-modify-private"}),
    )
    assert form_of(spotify.calls[0]) == {
        "grant_type": "authorization_code",
        "code": FAKE_CODE,
        "redirect_uri": "http://127.0.0.1:8888/callback",
        "client_id": "fake-client-id-for-tests",
        "code_verifier": FAKE_VERIFIER,
    }
    assert "client_secret" not in form_of(spotify.calls[0])
    assert spotify.calls[0].request.headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_a_bad_verifier_is_refused_before_anything_is_sent(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    with pytest.raises(ValueError, match="verifier"):
        exchange_code(http, settings, FAKE_CODE, "too-short")

    assert len(spotify.calls) == 0


def test_the_token_endpoint_is_never_followed_through_a_redirect(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, status=307, headers={"Location": "https://example.com/steal"})

    with pytest.raises(TokenError, match="307"):
        exchange_code(http, settings, FAKE_CODE, FAKE_VERIFIER)

    assert len(spotify.calls) == 1


def test_codes_verifiers_and_tokens_are_masked_as_soon_as_they_are_known(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, json=token_reply())

    exchange_code(http, settings, FAKE_CODE, FAKE_VERIFIER)

    for value in (FAKE_CODE, FAKE_VERIFIER, FAKE_ACCESS, FAKE_REFRESH):
        assert value in logging_setup._masked_values


def test_tokens_are_left_out_of_repr() -> None:
    tokens = Tokens(FAKE_ACCESS, FAKE_REFRESH, 3600, frozenset())

    assert FAKE_ACCESS not in repr(tokens)
    assert FAKE_REFRESH not in repr(tokens)


# Refreshing


def test_a_refresh_keeps_the_old_refresh_token_when_spotify_sends_none(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, refresh=None))

    tokens = refresh_tokens(http, settings, FAKE_REFRESH)

    assert tokens.access_token == FAKE_ACCESS_2
    assert tokens.refresh_token == FAKE_REFRESH
    assert form_of(spotify.calls[0]) == {
        "grant_type": "refresh_token",
        "refresh_token": FAKE_REFRESH,
        "client_id": "fake-client-id-for-tests",
    }


def test_a_refresh_uses_the_new_refresh_token_when_spotify_sends_one(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, FAKE_REFRESH_2))

    assert refresh_tokens(http, settings, FAKE_REFRESH).refresh_token == FAKE_REFRESH_2


def test_invalid_grant_means_sign_in_again_and_is_not_retried(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})

    with pytest.raises(SignInRequired):
        refresh_tokens(http, settings, FAKE_REFRESH)

    assert len(spotify.calls) == 1


# Replies we can't use


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (400, {"error": "invalid_client"}, r"400 \(invalid_client\)"),
        (400, {"error": "invalid_request", "error_description": FAKE_REFRESH}, "invalid_request"),
        (400, {"error": f"Weird {FAKE_REFRESH}"}, r"400 \(no error code\)"),
        (400, {"error": 42}, "no error code"),
        (401, {"error": "invalid_client"}, "401"),
        (429, {"error": "rate_limited"}, "429"),
        (500, "<html>Server error</html>", r"500 \(no error code\)"),
        (503, None, "503"),
        (200, "not json", r"200 \(no error code\)"),
        (200, ["a", "list"], "200"),
    ],
)
def test_error_replies_raise_token_error_quoting_only_the_code(
    spotify: responses.RequestsMock,
    http: requests.Session,
    settings: SpotifySettings,
    status: int,
    body: object,
    message: str,
) -> None:
    if body is None or isinstance(body, str):
        spotify.post(TOKEN_URL, status=status, body=body or "")
    else:
        spotify.post(TOKEN_URL, status=status, json=body)

    with pytest.raises(TokenError, match=message) as caught:
        refresh_tokens(http, settings, FAKE_REFRESH)

    assert FAKE_REFRESH not in str(caught.value)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (token_reply(access=""), "no access token"),
        ({k: v for k, v in token_reply().items() if k != "access_token"}, "no access token"),
        (token_reply(access=123), "no access token"),  # type: ignore[arg-type]
        (token_reply(refresh=None), "no refresh token"),
        (token_reply(token_type="mac"), "token type"),
        (token_reply(token_type=None), "token type"),
        (token_reply(expires_in=0), "expiry"),
        (token_reply(expires_in="3600"), "expiry"),
        (token_reply(expires_in=True), "expiry"),
    ],
)
def test_unusable_token_replies_are_refused(
    spotify: responses.RequestsMock,
    http: requests.Session,
    settings: SpotifySettings,
    reply: dict[str, object],
    message: str,
) -> None:
    spotify.post(TOKEN_URL, json=reply)

    with pytest.raises(TokenError, match=message):
        exchange_code(http, settings, FAKE_CODE, FAKE_VERIFIER)


def test_a_lowercase_bearer_and_a_missing_scope_are_accepted(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    reply = token_reply(token_type="bearer")
    del reply["scope"]
    spotify.post(TOKEN_URL, json=reply)

    assert exchange_code(http, settings, FAKE_CODE, FAKE_VERIFIER).scope == frozenset()


def test_a_refused_reply_still_has_its_tokens_masked(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, token_type="mac"))

    with pytest.raises(TokenError):
        exchange_code(http, settings, FAKE_CODE, FAKE_VERIFIER)

    assert FAKE_ACCESS_2 in logging_setup._masked_values


@pytest.mark.parametrize(
    "failure",
    [requests.ConnectionError("down"), requests.Timeout("slow"), requests.exceptions.SSLError()],
)
def test_network_failures_raise_token_error_without_the_original(
    spotify: responses.RequestsMock,
    http: requests.Session,
    settings: SpotifySettings,
    failure: requests.RequestException,
) -> None:
    spotify.post(TOKEN_URL, body=failure)

    with pytest.raises(TokenError, match=type(failure).__name__) as caught:
        refresh_tokens(http, settings, FAKE_REFRESH)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


# The sign-in for one run


def test_from_code_saves_the_refresh_token(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, json=token_reply())

    auth = SpotifyAuth.from_code(http, settings, FAKE_CODE, FAKE_VERIFIER)

    assert stored() == FAKE_REFRESH
    assert auth.access_token() == FAKE_ACCESS
    assert auth.scope == frozenset({"playlist-read-private", "playlist-modify-private"})


def test_from_store_is_none_when_nobody_signed_in(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    assert SpotifyAuth.from_store(http, settings) is None
    assert len(spotify.calls) == 0


def test_from_store_resumes_with_a_refresh(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    keyring.set_password("FairShuffle", "spotify-refresh-token", FAKE_REFRESH)
    spotify.post(TOKEN_URL, json=token_reply(refresh=None))

    auth = SpotifyAuth.from_store(http, settings)

    assert auth is not None
    assert auth.access_token() == FAKE_ACCESS
    assert stored() == FAKE_REFRESH


def test_from_store_saves_a_rotated_refresh_token(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    keyring.set_password("FairShuffle", "spotify-refresh-token", FAKE_REFRESH)
    spotify.post(TOKEN_URL, json=token_reply(refresh=FAKE_REFRESH_2))

    SpotifyAuth.from_store(http, settings)

    assert stored() == FAKE_REFRESH_2


def test_an_expired_saved_sign_in_is_removed(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    keyring.set_password("FairShuffle", "spotify-refresh-token", FAKE_REFRESH)
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})

    with pytest.raises(SignInRequired):
        SpotifyAuth.from_store(http, settings)

    assert stored() is None
    assert len(spotify.calls) == 1


def test_the_access_token_is_refreshed_a_minute_before_it_runs_out(
    spotify: responses.RequestsMock,
    http: requests.Session,
    settings: SpotifySettings,
    clock: FakeClock,
) -> None:
    auth = SpotifyAuth(http, settings, Tokens(FAKE_ACCESS, FAKE_REFRESH, 3600, frozenset()), clock)
    clock.now += 3600 - 61
    assert auth.access_token() == FAKE_ACCESS
    assert len(spotify.calls) == 0

    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, FAKE_REFRESH_2))
    clock.now += 1

    assert auth.access_token() == FAKE_ACCESS_2
    assert stored() == FAKE_REFRESH_2


def test_a_very_short_lived_token_is_refreshed_on_next_use(
    spotify: responses.RequestsMock,
    http: requests.Session,
    settings: SpotifySettings,
    clock: FakeClock,
) -> None:
    auth = SpotifyAuth(http, settings, Tokens(FAKE_ACCESS, FAKE_REFRESH, 30, frozenset()), clock)
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, refresh=None))

    assert auth.access_token() == FAKE_ACCESS_2
    assert stored() is None  # the refresh token didn't change, so nothing new was saved


def test_repr_shows_no_token(http: requests.Session, settings: SpotifySettings) -> None:
    auth = SpotifyAuth(http, settings, Tokens(FAKE_ACCESS, FAKE_REFRESH, 3600, frozenset()))

    assert FAKE_ACCESS not in repr(auth)
    assert FAKE_REFRESH not in repr(auth)


# API calls and the 401 refresh


@pytest.fixture
def auth(http: requests.Session, settings: SpotifySettings, clock: FakeClock) -> SpotifyAuth:
    return SpotifyAuth(http, settings, Tokens(FAKE_ACCESS, FAKE_REFRESH, 3600, frozenset()), clock)


def bearer(token: str) -> Callable[..., tuple[bool, str]]:
    return matchers.header_matcher({"Authorization": f"Bearer {token}"})


def test_api_calls_carry_the_access_token_and_a_timeout(
    spotify: responses.RequestsMock, auth: SpotifyAuth
) -> None:
    spotify.get(API_URL, json={"display_name": "Fake User"}, match=[bearer(FAKE_ACCESS)])

    response = auth.request("GET", API_URL, headers={"Accept": "application/json"})

    assert response.json() == {"display_name": "Fake User"}
    assert spotify.calls[0].request.headers["Accept"] == "application/json"
    assert spotify.calls[0].request.req_kwargs["timeout"] == oauth.TIMEOUT_SECONDS  # type: ignore[attr-defined]  # responses adds it


def test_a_401_refreshes_once_and_tries_again(
    spotify: responses.RequestsMock, auth: SpotifyAuth
) -> None:
    spotify.get(API_URL, status=401, match=[bearer(FAKE_ACCESS)])
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, refresh=None))
    spotify.get(API_URL, json={"display_name": "Fake User"}, match=[bearer(FAKE_ACCESS_2)])

    response = auth.request("GET", API_URL)

    assert response.status_code == 200
    assert [call.request.url for call in spotify.calls] == [API_URL, TOKEN_URL, API_URL]


def test_a_second_401_is_handed_back_without_another_refresh(
    spotify: responses.RequestsMock, auth: SpotifyAuth
) -> None:
    spotify.get(API_URL, status=401)
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, refresh=None))

    response = auth.request("GET", API_URL)

    assert response.status_code == 401
    assert len(spotify.calls) == 3  # call, refresh, call again: no loop


def test_a_401_whose_refresh_is_refused_means_sign_in_again(
    spotify: responses.RequestsMock, auth: SpotifyAuth
) -> None:
    keyring.set_password("FairShuffle", "spotify-refresh-token", FAKE_REFRESH)
    spotify.get(API_URL, status=401)
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})

    with pytest.raises(SignInRequired):
        auth.request("GET", API_URL)

    assert stored() is None


def test_other_errors_are_handed_back_without_a_refresh(
    spotify: responses.RequestsMock, auth: SpotifyAuth
) -> None:
    spotify.get(API_URL, status=403, json={"error": {"status": 403, "message": "Forbidden"}})

    assert auth.request("GET", API_URL).status_code == 403
    assert len(spotify.calls) == 1


# Logs


def test_no_token_text_reaches_any_log_record(
    spotify: responses.RequestsMock,
    http: requests.Session,
    settings: SpotifySettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """caplog sees records before FairShuffle's redacting filter, so this proves none is logged."""
    caplog.set_level(logging.DEBUG)
    spotify.post(TOKEN_URL, json=token_reply())
    spotify.get(API_URL, status=401)
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, FAKE_REFRESH_2))
    spotify.get(API_URL, json={})
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})

    auth = SpotifyAuth.from_code(http, settings, FAKE_CODE, FAKE_VERIFIER)
    auth.request("GET", API_URL)
    with pytest.raises(SignInRequired):
        auth.refresh()

    assert caplog.records  # the flow did log
    text = "\n".join(
        json.dumps([record.getMessage(), record.exc_text, record.args], default=str)
        for record in caplog.records
    )
    for fake in ALL_FAKES:
        assert fake not in text


# Where the token may go


@pytest.mark.parametrize(
    "url",
    [
        "http://api.spotify.com/v1/me",
        "https://example.com/v1/me",
        "https://api.spotify.com.evil.test/v1/me",
        "https://api.spotify.com:8443/v1/me",
        "https://user@api.spotify.com/v1/me",
        "/v1/me",
    ],
)
def test_the_token_only_goes_to_spotifys_api_over_https(
    spotify: responses.RequestsMock, auth: SpotifyAuth, url: str
) -> None:
    with pytest.raises(ValueError, match="api.spotify.com"):
        auth.request("GET", url)

    assert len(spotify.calls) == 0


@pytest.mark.parametrize("verify", [False, "/some/ca.pem"])
def test_certificate_checks_cannot_be_turned_off(
    spotify: responses.RequestsMock, auth: SpotifyAuth, verify: object
) -> None:
    with pytest.raises(ValueError, match="certificate"):
        auth.request("GET", API_URL, verify=verify)

    assert len(spotify.calls) == 0


def test_a_failed_removal_still_means_sign_in_again(
    spotify: responses.RequestsMock,
    http: requests.Session,
    settings: SpotifySettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_delete() -> None:
        raise oauth.TokenStoreError("Could not remove the sign-in from Windows Credential Manager.")

    monkeypatch.setattr(oauth, "delete_refresh_token", broken_delete)
    keyring.set_password("FairShuffle", "spotify-refresh-token", FAKE_REFRESH)
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})

    with pytest.raises(SignInRequired) as caught:
        SpotifyAuth.from_store(http, settings)

    assert caught.value.__context__ is None


def test_a_401_after_another_thread_refreshed_does_not_refresh_again(
    spotify: responses.RequestsMock, auth: SpotifyAuth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two calls fail with the same old token: only the first spends the refresh token."""
    spotify.post(TOKEN_URL, json=token_reply(FAKE_ACCESS_2, FAKE_REFRESH_2))
    spotify.get(API_URL, json={}, match=[bearer(FAKE_ACCESS_2)])
    real_send = SpotifyAuth._send

    def send_then_lose_the_race(self, method, url, token, kwargs):  # type: ignore[no-untyped-def]
        if token == FAKE_ACCESS:
            self.refresh()  # another thread refreshes while this call is on the wire
            return _response(401)
        return real_send(self, method, url, token, kwargs)

    monkeypatch.setattr(SpotifyAuth, "_send", send_then_lose_the_race)

    assert auth.request("GET", API_URL).status_code == 200
    assert [call.request.url for call in spotify.calls] == [TOKEN_URL, API_URL]


def _response(status: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.raw = io.BytesIO(b"")
    return response


def test_a_session_without_certificate_checks_is_refused(settings: SpotifySettings) -> None:
    with requests.Session() as insecure:
        insecure.verify = False

        with pytest.raises(ValueError, match="certificate"):
            SpotifyAuth(insecure, settings, Tokens(FAKE_ACCESS, FAKE_REFRESH, 3600, frozenset()))
        with pytest.raises(ValueError, match="certificate"):
            refresh_tokens(insecure, settings, FAKE_REFRESH)


def test_once_the_sign_in_has_ended_nobody_asks_spotify_again(
    spotify: responses.RequestsMock, auth: SpotifyAuth
) -> None:
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})

    with pytest.raises(SignInRequired):
        auth.refresh()
    with pytest.raises(SignInRequired):
        auth.refresh()  # another worker thread that was waiting on the lock

    assert len(spotify.calls) == 1
