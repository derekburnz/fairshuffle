"""The playlist items cache: an unchanged snapshot_id means no item calls."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
import responses
from responses import matchers

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.spotify.cache import MAX_PLAYLISTS, PlaylistItemsCache
from fairshuffle.spotify.client import API_BASE, SpotifyClient, new_session
from fairshuffle.spotify.models import Playlist, PlaylistItem


@pytest.fixture
def spotify() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        yield SpotifyClient(SpotifyAuth(http, load_settings(), tokens), sleep=lambda _: None)


def playlist(number: int = 1, snapshot: str = "fake-snapshot-1") -> Playlist:
    return Playlist(f"fakeplaylist{number}", "Fake", "fakeuser", False, snapshot, 2)


def serve_items(
    spotify: responses.RequestsMock, number: int = 1, uris: list[str] | None = None
) -> None:
    uris = uris or ["spotify:track:faketrack1", "spotify:track:faketrack2"]
    entries: list[dict[str, Any]] = [{"item": {"type": "track", "uri": uri}} for uri in uris]
    spotify.get(
        f"{API_BASE}/playlists/fakeplaylist{number}/items",
        json={"items": entries, "next": None},
        match=[matchers.query_param_matcher({"offset": "0"}, strict_match=False)],
    )


def uris(items: tuple[PlaylistItem, ...]) -> list[str | None]:
    return [item.uri for item in items]


def test_the_first_read_asks_spotify(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    serve_items(spotify)

    items = PlaylistItemsCache().items(client, playlist())

    assert uris(items) == ["spotify:track:faketrack1", "spotify:track:faketrack2"]
    assert len(spotify.calls) == 1


def test_an_unchanged_snapshot_makes_no_item_calls(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    serve_items(spotify)
    cache = PlaylistItemsCache()
    first = cache.items(client, playlist())

    again = cache.items(client, playlist())

    assert again == first
    assert len(spotify.calls) == 1  # the second read never reached Spotify


def test_a_changed_snapshot_reads_again(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    serve_items(spotify)
    serve_items(spotify, uris=["spotify:track:faketrack9"])
    cache = PlaylistItemsCache()
    cache.items(client, playlist())

    changed = cache.items(client, playlist(snapshot="fake-snapshot-2"))

    assert uris(changed) == ["spotify:track:faketrack9"]
    assert len(spotify.calls) == 2
    assert cache.items(client, playlist(snapshot="fake-snapshot-2")) == changed  # now cached


def test_playlists_are_kept_apart(spotify: responses.RequestsMock, client: SpotifyClient) -> None:
    serve_items(spotify, 1, ["spotify:track:one"])
    serve_items(spotify, 2, ["spotify:track:two"])
    cache = PlaylistItemsCache()

    assert uris(cache.items(client, playlist(1))) == ["spotify:track:one"]
    assert uris(cache.items(client, playlist(2))) == ["spotify:track:two"]
    assert uris(cache.items(client, playlist(1))) == ["spotify:track:one"]
    assert len(spotify.calls) == 2


def test_the_least_recently_used_playlist_is_forgotten_first(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    for number in (1, 2, 3):
        serve_items(spotify, number)
    serve_items(spotify, 2)  # read again after it was pushed out
    cache = PlaylistItemsCache(max_playlists=2)
    cache.items(client, playlist(1))
    cache.items(client, playlist(2))
    cache.items(client, playlist(1))  # 1 is now the most recent
    cache.items(client, playlist(3))  # pushes out 2

    assert len(cache) == 2
    cache.items(client, playlist(1))  # still cached
    cache.items(client, playlist(2))  # read again
    assert len(spotify.calls) == 4


def test_forget_and_clear(spotify: responses.RequestsMock, client: SpotifyClient) -> None:
    for _ in range(2):
        serve_items(spotify, 1)
    serve_items(spotify, 2)
    cache = PlaylistItemsCache()
    cache.items(client, playlist(1))
    cache.forget("fakeplaylist1")
    cache.forget("never-cached")
    cache.items(client, playlist(1))
    cache.items(client, playlist(2))

    cache.clear()

    assert len(cache) == 0
    assert len(spotify.calls) == 3


def test_a_failed_read_caches_nothing(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(f"{API_BASE}/playlists/fakeplaylist1/items", status=403)
    cache = PlaylistItemsCache()

    with pytest.raises(Exception, match="own or collaborate"):
        cache.items(client, playlist())
    assert len(cache) == 0


def test_the_default_limit_bounds_memory() -> None:
    assert MAX_PLAYLISTS == 50


def test_it_is_safe_to_share_between_threads(
    client: SpotifyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = PlaylistItem(0, "spotify:track:faketrack1", "track", False)
    monkeypatch.setattr("fairshuffle.spotify.cache.read_playlist_items", lambda _c, _id: [item])
    cache = PlaylistItemsCache(max_playlists=5)
    errors: list[BaseException] = []

    def work(offset: int) -> None:
        try:
            for number in range(40):
                cache.items(client, replace(playlist((number + offset) % 9), snapshot_id="s"))
        except BaseException as error:  # pragma: no cover  # only on a real race
            errors.append(error)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(cache) == 5


def test_it_logs_no_ids(
    spotify: responses.RequestsMock, client: SpotifyClient, caplog: pytest.LogCaptureFixture
) -> None:
    serve_items(spotify)
    cache = PlaylistItemsCache()
    with caplog.at_level("DEBUG"):
        cache.items(client, playlist())
        cache.items(client, playlist())

    assert "no item calls needed" in caplog.text
    for private in ("fakeplaylist1", "fake-snapshot-1", "spotify:track"):
        assert private not in caplog.text
