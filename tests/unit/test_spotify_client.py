"""The Web API client: retries, waits and error mapping, against fake Spotify replies."""

from __future__ import annotations

import logging
import random
from collections.abc import Iterator

import pytest
import requests
import responses
from responses import matchers

from fairshuffle import __version__
from fairshuffle.auth.oauth import SignInRequired, SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.spotify import client as client_module
from fairshuffle.spotify import errors
from fairshuffle.spotify.client import API_BASE, SpotifyClient, new_session
from fairshuffle.spotify.errors import (
    AccessDenied,
    NotOwner,
    RateLimited,
    RequestRejected,
    SpotifyUnavailable,
)
from fairshuffle.spotify.ratelimit import RetryPolicy

ME = f"{API_BASE}/me"
ITEMS = f"{API_BASE}/playlists/fake-playlist-id/items"
TOKEN_URL = "https://accounts.spotify.com/api/token"
FAKE_ACCESS = "fake-access-token-1"
QUOTA_BODY = {"error": {"status": 429, "message": "Too many requests", "reason": "QUOTA_EXCEEDED"}}


class Ceiling(random.Random):
    """Always picks the top of the jitter range, so waits are predictable."""

    def uniform(self, a: float, b: float) -> float:
        return b


@pytest.fixture
def spotify() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture
def waits() -> list[float]:
    return []


@pytest.fixture
def client(waits: list[float]) -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens(FAKE_ACCESS, "fake-refresh-token-for-tests", 3600, frozenset())
        auth = SpotifyAuth(http, load_settings(), tokens)
        yield SpotifyClient(auth, RetryPolicy(), sleep=waits.append, rng=Ceiling())


# Plain calls


def test_a_get_returns_the_json_with_our_headers(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(
        ME,
        json={"display_name": "Fake User"},
        match=[
            matchers.header_matcher(
                {
                    "Authorization": f"Bearer {FAKE_ACCESS}",
                    "User-Agent": f"FairShuffle/{__version__}",
                }
            )
        ],
    )

    assert client.get("/me") == {"display_name": "Fake User"}


def test_query_parameters_and_bodies_are_sent(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(ITEMS, json={"items": []}, match=[matchers.query_param_matcher({"limit": "50"})])
    spotify.put(
        ITEMS,
        json={"snapshot_id": "fake-snapshot-2"},
        match=[matchers.json_params_matcher({"range_start": 0, "insert_before": 3})],
    )
    spotify.post(ITEMS, json={"snapshot_id": "fake-snapshot-3"})

    assert client.get("/playlists/fake-playlist-id/items", {"limit": 50}) == {"items": []}
    assert client.put("/playlists/fake-playlist-id/items", {"range_start": 0, "insert_before": 3})
    assert client.post("/playlists/fake-playlist-id/items", {"uris": []})


@pytest.mark.parametrize("status", [200, 201, 204])
def test_an_empty_reply_is_an_empty_dict(
    spotify: responses.RequestsMock, client: SpotifyClient, status: int
) -> None:
    spotify.put(ITEMS, status=status, body=b"")

    assert client.put("/playlists/fake-playlist-id/items", {}) == {}


@pytest.mark.parametrize(
    "path",
    [
        "me",
        "//evil.test/me",
        "https://api.spotify.com/v1/me",
        "",
        "/me\r\nINFO forged line",
        "/me\x00",
        "/../../x",
        "/playlists/../me",
        "/%2e%2e/%2E%2E/x",
        "/playlists%2Ffake",
        "/playlists%5c..%5cme",
        "/a\\..\\b",
    ],
)
def test_unsafe_paths_are_refused(
    spotify: responses.RequestsMock, client: SpotifyClient, path: str
) -> None:
    with pytest.raises(ValueError, match="path"):
        client.get(path)

    assert len(spotify.calls) == 0


def test_dots_in_a_query_are_fine(spotify: responses.RequestsMock, client: SpotifyClient) -> None:
    spotify.get(ME, json={}, match=[matchers.query_param_matcher({"fields": "a..b"})])

    assert client.get_url(f"{ME}?fields=a..b") == {}


def test_a_next_link_from_spotify_can_be_followed(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(
        ITEMS,
        json={"items": [], "next": None},
        match=[matchers.query_param_matcher({"offset": "50"})],
    )

    assert client.get_url(f"{ITEMS}?offset=50") == {"items": [], "next": None}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1/me",
        "http://api.spotify.com/v1/me",
        "https://api.spotify.com/v10/me",
        "https://api.spotify.com.evil.test/v1/me",
        "https://api.spotify.com/v1",
    ],
)
def test_links_elsewhere_are_refused(client: SpotifyClient, url: str) -> None:
    with pytest.raises(ValueError, match="Spotify Web API"):
        client.get_url(url)


# 429: slow down


def test_a_429_with_retry_after_waits_that_long_then_tries_again(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.get(ME, status=429, headers={"Retry-After": "3"})
    spotify.get(ME, json={"id": "fake-user"})

    assert client.get("/me") == {"id": "fake-user"}
    assert waits == [3.0]


def test_a_429_without_retry_after_backs_off(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.get(ME, status=429)
    spotify.get(ME, status=429)
    spotify.get(ME, json={})

    client.get("/me")

    assert waits == [1.0, 2.0]


def test_quota_exceeded_is_handed_back_without_waiting(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.get(ME, status=429, json=QUOTA_BODY, headers={"Retry-After": "30"})

    with pytest.raises(RateLimited, match="quota") as caught:
        client.get("/me")

    assert caught.value.quota_exceeded
    assert caught.value.retry_after == 30.0
    assert waits == []
    assert len(spotify.calls) == 1


def test_a_very_long_retry_after_is_handed_back_without_waiting(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.get(ME, status=429, headers={"Retry-After": "600"})

    with pytest.raises(RateLimited) as caught:
        client.get("/me")

    assert caught.value.retry_after == 600.0
    assert not caught.value.quota_exceeded
    assert waits == []


def test_429s_stop_after_the_last_attempt(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    for _ in range(4):
        spotify.get(ME, status=429, headers={"Retry-After": "1"})

    with pytest.raises(RateLimited):
        client.get("/me")

    assert len(spotify.calls) == 4
    assert waits == [1.0, 1.0, 1.0]


def test_a_change_is_retried_after_a_429_because_spotify_refused_it(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.put(ITEMS, status=429, headers={"Retry-After": "2"})
    spotify.put(ITEMS, json={"snapshot_id": "fake-snapshot-2"})

    assert client.put("/playlists/fake-playlist-id/items", {}) == {"snapshot_id": "fake-snapshot-2"}
    assert waits == [2.0]


# 5xx and dropped connections


def test_a_read_backs_off_after_5xx_then_succeeds(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.get(ME, status=503)
    spotify.get(ME, status=502)
    spotify.get(ME, json={"id": "fake-user"})

    assert client.get("/me") == {"id": "fake-user"}
    assert waits == [1.0, 2.0]


def test_a_read_gives_up_after_repeated_5xx(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    for _ in range(4):
        spotify.get(ME, status=500)

    with pytest.raises(SpotifyUnavailable, match="500") as caught:
        client.get("/me")

    assert not caught.value.may_have_applied
    assert waits == [1.0, 2.0, 4.0]


def test_a_change_is_not_retried_after_a_5xx(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.put(ITEMS, status=500)

    with pytest.raises(SpotifyUnavailable) as caught:
        client.put("/playlists/fake-playlist-id/items", {"range_start": 0, "insert_before": 3})

    assert caught.value.may_have_applied
    assert len(spotify.calls) == 1
    assert waits == []


def test_a_read_is_retried_after_a_dropped_connection(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.get(ME, body=requests.ConnectionError("connection reset"))
    spotify.get(ME, json={"id": "fake-user"})

    assert client.get("/me") == {"id": "fake-user"}
    assert waits == [1.0]


def test_a_read_gives_up_after_repeated_drops_without_the_original_error(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    for _ in range(4):
        spotify.get(ME, body=requests.Timeout("read timed out"))

    with pytest.raises(SpotifyUnavailable, match="Timeout") as caught:
        client.get("/me")

    assert caught.value.__context__ is None
    assert not caught.value.may_have_applied


def test_a_change_is_not_resent_after_a_drop_that_may_have_reached_spotify(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.put(ITEMS, body=requests.ConnectionError("connection reset"))

    with pytest.raises(SpotifyUnavailable) as caught:
        client.put("/playlists/fake-playlist-id/items", {"range_start": 0, "insert_before": 3})

    assert caught.value.may_have_applied
    assert len(spotify.calls) == 1


def test_a_change_is_retried_when_the_connection_never_opened(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float]
) -> None:
    spotify.put(ITEMS, body=requests.ConnectTimeout("connect timed out"))
    spotify.put(ITEMS, json={"snapshot_id": "fake-snapshot-2"})

    assert client.put("/playlists/fake-playlist-id/items", {}) == {"snapshot_id": "fake-snapshot-2"}
    assert waits == [1.0]


def test_a_change_whose_connection_never_opens_gives_up_as_not_applied(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    for _ in range(4):
        spotify.put(ITEMS, body=requests.ConnectTimeout("connect timed out"))

    with pytest.raises(SpotifyUnavailable) as caught:
        client.put("/playlists/fake-playlist-id/items", {})

    assert not caught.value.may_have_applied


# Errors Spotify answers with


def test_a_403_on_a_playlist_means_not_owner(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(ITEMS, status=403, json={"error": {"status": 403, "message": "Forbidden"}})

    with pytest.raises(NotOwner, match="own or collaborate on"):
        client.get("/playlists/fake-playlist-id/items")


def test_a_403_elsewhere_points_at_user_management(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(ME, status=403, body=b"")

    with pytest.raises(AccessDenied, match="User Management") as caught:
        client.get("/me")

    assert not isinstance(caught.value, NotOwner)


def test_a_redirect_is_never_followed(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.put(ITEMS, status=307, headers={"Location": "https://192.0.2.1/steal"})

    with pytest.raises(RequestRejected, match="307"):
        client.put("/playlists/fake-playlist-id/items", {"uris": []})

    assert len(spotify.calls) == 1


@pytest.mark.parametrize("status", [400, 404, 413])
def test_other_client_errors_are_rejected_without_retrying(
    spotify: responses.RequestsMock, client: SpotifyClient, waits: list[float], status: int
) -> None:
    spotify.get(ME, status=status, json={"error": {"status": status, "message": "Bad thing"}})

    with pytest.raises(RequestRejected, match=str(status)) as caught:
        client.get("/me")

    assert caught.value.status == status
    assert "Bad thing" not in str(caught.value)
    assert waits == []


def test_only_a_well_formed_reason_code_is_quoted(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(ME, status=400, json={"error": {"reason": "BAD_INPUT"}})
    spotify.get(ME, status=400, json={"error": {"reason": "fake-access-token-1 leaked"}})

    with pytest.raises(RequestRejected, match=r"\(400\) \(BAD_INPUT\)"):
        client.get("/me")
    with pytest.raises(RequestRejected) as caught:
        client.get("/me")

    assert "leaked" not in str(caught.value)


def test_a_second_401_means_sign_in_again(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(ME, status=401)
    spotify.post(
        TOKEN_URL,
        json={"access_token": "fake-access-token-2", "token_type": "Bearer", "expires_in": 3600},
    )
    spotify.get(ME, status=401)

    with pytest.raises(SignInRequired):
        client.get("/me")


@pytest.mark.parametrize("body", [b"<html>oops</html>", b"[1, 2]"])
def test_a_reply_that_isnt_a_json_object_is_refused(
    spotify: responses.RequestsMock, client: SpotifyClient, body: bytes
) -> None:
    spotify.get(ME, body=body, content_type="application/json")

    with pytest.raises(SpotifyUnavailable) as caught:
        client.get("/me")

    assert caught.value.__context__ is None  # the parse error holds the whole body


def test_every_spotify_error_comes_from_one_place() -> None:
    assert errors.SignInRequired is SignInRequired
    for error in (AccessDenied, RateLimited, RequestRejected, SpotifyUnavailable):
        assert issubclass(error, errors.SpotifyError)
    assert issubclass(NotOwner, AccessDenied)


# Logs


def test_logs_name_the_path_but_never_the_query_or_body(
    spotify: responses.RequestsMock,
    client: SpotifyClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="fairshuffle")
    spotify.get(ITEMS, status=503)
    spotify.get(ITEMS, body=requests.ConnectionError("reset"))
    spotify.get(ITEMS, json={})

    client.get("/playlists/fake-playlist-id/items", {"fields": "fake-secret-field", "limit": 50})

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "GET /playlists/{id}/items: waiting" in text
    assert "fake-playlist-id" not in text  # IDs are the user's own data
    assert "fake-secret-field" not in text
    assert FAKE_ACCESS not in text


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        ("/me", "/me"),
        ("/me/playlists", "/me/playlists"),
        ("/playlists/abc123/items", "/playlists/{id}/items"),
        ("/users/fake-account-name/playlists", "/users/{id}/playlists"),
        ("/tracks/abc?market=XX", "/tracks/{id}"),
        ("/Playlists/ABC/items", "/Playlists/{id}/items"),  # any case
    ],
)
def test_ids_in_a_path_are_hidden_in_log_lines(path: str, shown: str) -> None:
    assert client_module._log_route(path) == shown


def test_a_next_links_query_stays_out_of_the_logs(
    spotify: responses.RequestsMock,
    client: SpotifyClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="fairshuffle")
    spotify.get(ITEMS, status=503)
    spotify.get(ITEMS, json={})

    client.get_url(f"{ITEMS}?offset=50&fields=fake-secret-field")

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "GET /playlists/{id}/items: waiting" in text
    assert "fake-secret-field" not in text
    assert "offset" not in text


def test_turning_certificate_checks_off_later_is_still_refused(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    client._auth._http.verify = False  # type: ignore[attr-defined]  # reaching in, as a bug would

    with pytest.raises(ValueError, match="certificate"):
        client.get("/me")

    assert len(spotify.calls) == 0
