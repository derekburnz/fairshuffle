"""Listing the playlists FairShuffle can reorder and reading their items, against fake replies."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
import responses
from responses import matchers

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.spotify.client import API_BASE, SpotifyClient, new_session
from fairshuffle.spotify.errors import NotOwner, SpotifyUnavailable
from fairshuffle.spotify.models import Playlist, PlaylistItem
from fairshuffle.spotify.playlists import PAGE_SIZE, list_editable_playlists, read_playlist_items

LIST = f"{API_BASE}/me/playlists"
ME_ID = "fakeuser"


@pytest.fixture
def spotify() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        yield SpotifyClient(SpotifyAuth(http, load_settings(), tokens), sleep=lambda _: None)


def entry(number: int, **changes: Any) -> dict[str, Any]:
    """One playlist as GET /me/playlists lists it, owned by the fake user unless changed."""
    playlist: dict[str, Any] = {
        "id": f"fakeplaylist{number}",
        "name": f"Fake Playlist {number}",
        "owner": {"id": ME_ID, "display_name": "Fake User"},
        "collaborative": False,
        "public": False,
        "snapshot_id": f"fake-snapshot-{number}",
        "items": {"href": f"{API_BASE}/playlists/fakeplaylist{number}/items", "total": number},
        "tracks": {"href": "deprecated", "total": 9999},
        "uri": f"spotify:playlist:fakeplaylist{number}",
    }
    playlist.update(changes)
    return playlist


def page_query(number: int) -> list[Any]:
    return [
        matchers.query_param_matcher(
            {"limit": str(PAGE_SIZE), "offset": str(number * PAGE_SIZE)}, strict_match=False
        )
    ]


def add_pages(spotify: responses.RequestsMock, entries: list[dict[str, Any]]) -> None:
    """Serve entries the way Spotify does: pages of 50, each with a next link but the last."""
    pages = [entries[start : start + PAGE_SIZE] for start in range(0, len(entries), PAGE_SIZE)]
    for number, items in enumerate(pages or [[]]):
        is_last = number == max(len(pages) - 1, 0)
        next_url = (
            None if is_last else f"{LIST}?offset={(number + 1) * PAGE_SIZE}&limit={PAGE_SIZE}"
        )
        spotify.get(
            LIST,
            json={"items": items, "next": next_url, "total": len(entries), "limit": PAGE_SIZE},
            match=page_query(number),
        )


@pytest.mark.parametrize("count", [0, 1, 120])
def test_every_page_is_read(
    spotify: responses.RequestsMock, client: SpotifyClient, count: int
) -> None:
    add_pages(spotify, [entry(number) for number in range(1, count + 1)])

    playlists = list_editable_playlists(client, ME_ID)

    assert [playlist.id for playlist in playlists] == [
        f"fakeplaylist{n}" for n in range(1, count + 1)
    ]
    assert len(spotify.calls) == max(1, -(-count // PAGE_SIZE))  # one call per page of 50


def test_a_playlist_becomes_plain_data(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    add_pages(spotify, [entry(7)])

    assert list_editable_playlists(client, ME_ID) == [
        Playlist(
            id="fakeplaylist7",
            name="Fake Playlist 7",
            owner_id=ME_ID,
            collaborative=False,
            snapshot_id="fake-snapshot-7",
            item_count=7,  # from items.total, never the deprecated tracks.total
        )
    ]


def test_only_owned_and_collaborative_playlists_are_kept(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    add_pages(
        spotify,
        [
            entry(1),
            entry(2, owner={"id": "someone-else"}),  # followed: can't be reordered
            entry(3, owner={"id": "someone-else"}, collaborative=True),
            entry(4, collaborative="true"),  # owned, so kept, but not counted as collaborative
        ],
    )

    playlists = list_editable_playlists(client, ME_ID)

    assert [(p.id, p.collaborative) for p in playlists] == [
        ("fakeplaylist1", False),
        ("fakeplaylist3", True),
        ("fakeplaylist4", False),
    ]


@pytest.mark.parametrize(
    "items",
    [None, {}, {"total": None}, {"total": -1}, {"total": "12"}, {"total": True}, "12"],
)
def test_a_missing_or_odd_count_is_none(
    spotify: responses.RequestsMock, client: SpotifyClient, items: Any
) -> None:
    add_pages(spotify, [entry(1, items=items)])

    assert list_editable_playlists(client, ME_ID)[0].item_count is None


@pytest.mark.parametrize(
    "broken",
    [
        None,
        "not a playlist",
        {"id": "fakeplaylist1"},
        entry(1, id=None),
        entry(1, id="../me"),
        entry(1, id="fake?playlist"),
        entry(1, id="x" * 65),
        entry(1, owner=None),
        entry(1, owner={"id": 5}),
        entry(1, snapshot_id=None),
        entry(1, snapshot_id=""),
        entry(1, snapshot_id="fake snapshot"),
        entry(1, snapshot_id="fake\r\nsnapshot"),
        entry(1, snapshot_id="x" * 257),
    ],
)
def test_malformed_entries_are_skipped(
    spotify: responses.RequestsMock, client: SpotifyClient, broken: Any
) -> None:
    add_pages(spotify, [broken, entry(2)])

    assert [playlist.id for playlist in list_editable_playlists(client, ME_ID)] == ["fakeplaylist2"]


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("Morning Run", "Morning Run"),
        ("  Road\nTrip‮ ", "RoadTrip"),  # line breaks and direction tricks removed
        ("", ""),
        (None, ""),
        (42, ""),
        ("x" * 300, "x" * 300),  # the picker truncates for display; the data keeps it all
        ("x" * 10_000, "x" * 499 + "…"),  # but not without limit
    ],
)
def test_names_are_cleaned_and_cut_only_when_huge(
    spotify: responses.RequestsMock, client: SpotifyClient, name: Any, shown: str
) -> None:
    add_pages(spotify, [entry(1, name=name)])

    assert list_editable_playlists(client, ME_ID)[0].name == shown


def test_a_playlist_listed_twice_appears_once(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    add_pages(spotify, [entry(1), entry(1, name="Again")])

    assert len(list_editable_playlists(client, ME_ID)) == 1


@pytest.mark.parametrize(
    "page",
    [
        {},
        {"items": None},
        {"items": "x", "next": 5},
        {"items": [], "next": True},  # neither null nor a link
        {"items": [], "next": 7},
    ],
)
def test_a_page_without_an_items_list_is_refused(
    spotify: responses.RequestsMock, client: SpotifyClient, page: dict[str, Any]
) -> None:
    spotify.get(LIST, json=page)

    with pytest.raises(SpotifyUnavailable, match="doesn't understand"):
        list_editable_playlists(client, ME_ID)


def test_a_later_page_without_items_never_gives_back_part_of_the_list(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    first = [entry(number) for number in range(1, PAGE_SIZE + 1)]
    spotify.get(LIST, json={"items": first, "next": f"{LIST}?more"}, match=page_query(0))
    spotify.get(LIST, json={"error": {"status": 500}}, match=page_query(1))

    with pytest.raises(SpotifyUnavailable, match="doesn't understand"):
        list_editable_playlists(client, ME_ID)


def test_the_next_link_is_never_followed(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    # Older replies pointed next at /users/{user id}/playlists, which would put the user ID in
    # the log on a retry. FairShuffle asks for /me/playlists at the next offset instead.
    first = [entry(number) for number in range(1, PAGE_SIZE + 1)]
    elsewhere = f"{API_BASE}/users/fake-account-name/playlists?offset=50"
    spotify.get(LIST, json={"items": first, "next": elsewhere}, match=page_query(0))
    spotify.get(LIST, json={"items": [entry(51)], "next": None}, match=page_query(1))

    assert len(list_editable_playlists(client, ME_ID)) == PAGE_SIZE + 1
    assert all(str(call.request.url).startswith(LIST + "?") for call in spotify.calls)


@pytest.mark.parametrize(
    "page",
    [
        {"items": [entry(1)], "next": f"{LIST}?offset=50"},  # a short page that claims more
        {"items": [entry(n) for n in range(PAGE_SIZE + 1)], "next": None},  # more than asked
    ],
)
def test_a_page_that_doesnt_add_up_is_refused(
    spotify: responses.RequestsMock, client: SpotifyClient, page: dict[str, Any]
) -> None:
    spotify.get(LIST, json=page)

    with pytest.raises(SpotifyUnavailable, match="doesn't understand"):
        list_editable_playlists(client, ME_ID)


def test_the_page_limit_stops_an_endless_list_with_an_error(
    spotify: responses.RequestsMock, client: SpotifyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("fairshuffle.spotify.playlists.MAX_PAGES", 2)
    for number in range(2):
        items = [entry(number * PAGE_SIZE + n) for n in range(1, PAGE_SIZE + 1)]
        spotify.get(LIST, json={"items": items, "next": f"{LIST}?more"}, match=page_query(number))

    with pytest.raises(SpotifyUnavailable, match="doesn't understand"):
        list_editable_playlists(client, ME_ID)  # more pages remain: never hand back part of it
    assert len(spotify.calls) == 2


def test_names_stay_out_of_the_log(
    spotify: responses.RequestsMock, client: SpotifyClient, caplog: pytest.LogCaptureFixture
) -> None:
    add_pages(spotify, [entry(1, name="Secret Crush Songs")])

    with caplog.at_level(logging.DEBUG):
        list_editable_playlists(client, ME_ID)

    assert "Found 1 playlists" in caplog.text
    assert "Secret Crush" not in caplog.text


# Reading a playlist's items

FIXTURES = Path(__file__).parent.parent / "fixtures" / "spotify"
ITEMS = f"{API_BASE}/playlists/fakeplaylist1/items"


def item_entry(number: int) -> dict[str, Any]:
    uri = f"spotify:track:faketrack{number:013d}"
    return {"is_local": False, "item": {"type": "track", "uri": uri}}


def test_tracks_episodes_local_files_and_missing_items_are_all_kept(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    page = json.loads((FIXTURES / "playlist_items_page.json").read_text(encoding="utf-8"))
    spotify.get(
        ITEMS,
        json=page,
        match=[
            matchers.query_param_matcher(
                {"limit": str(PAGE_SIZE), "offset": "0", "additional_types": "track,episode"}
            )
        ],
    )

    assert read_playlist_items(client, "fakeplaylist1") == [
        PlaylistItem(0, "spotify:track:faketrack0000000000001", "track", is_local=False),
        PlaylistItem(1, "spotify:episode:fakeepisode00000000001", "episode", is_local=False),
        PlaylistItem(
            2, "spotify:local:Fake+Artist:Fake+Album:Fake+Local+Song:215", "track", is_local=True
        ),
        PlaylistItem(3, None, None, is_local=False),  # no longer available, but keeps its place
    ]


@pytest.mark.parametrize("count", [0, 1, 50, 51, 120])
def test_positions_run_across_pages(
    spotify: responses.RequestsMock, client: SpotifyClient, count: int
) -> None:
    entries = [item_entry(number) for number in range(count)]
    pages = [entries[start : start + PAGE_SIZE] for start in range(0, count, PAGE_SIZE)] or [[]]
    for number, items in enumerate(pages):
        last = number == len(pages) - 1
        spotify.get(
            ITEMS,
            json={"items": items, "next": None if last else f"{ITEMS}?more"},
            match=page_query(number),
        )

    items = read_playlist_items(client, "fakeplaylist1")

    assert [item.position for item in items] == list(range(count))
    assert [item.uri for item in items] == [entry["item"]["uri"] for entry in entries]


@pytest.mark.parametrize(
    "entry",
    [
        None,
        "not an item",
        {},
        {"item": "spotify:track:x"},
        {"item": {"type": "track"}},
        {"item": {"type": "track", "uri": 5}},
        {"item": {"type": "track", "uri": "https://example.com/track"}},
        {"item": {"type": "track", "uri": "spotify:track:fake\nline"}},
        {"item": {"type": "track", "uri": "spotify:local:" + "x" * 1_000}},
    ],
)
def test_an_unusable_entry_becomes_an_unavailable_item(
    spotify: responses.RequestsMock, client: SpotifyClient, entry: Any
) -> None:
    spotify.get(ITEMS, json={"items": [entry, item_entry(1)], "next": None})

    first, second = read_playlist_items(client, "fakeplaylist1")

    assert first.uri is None
    assert first.is_local is False
    assert second.position == 1


@pytest.mark.parametrize(
    ("kind", "kept"), [("track", "track"), ("episode", "episode"), ("show", None), (None, None)]
)
def test_only_known_kinds_are_kept(
    spotify: responses.RequestsMock, client: SpotifyClient, kind: Any, kept: str | None
) -> None:
    entry = {"item": {"type": kind, "uri": "spotify:track:faketrack0000000000001"}}
    spotify.get(ITEMS, json={"items": [entry]})

    assert read_playlist_items(client, "fakeplaylist1")[0].kind == kept


def test_the_deprecated_track_field_is_not_read(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    entry = {"track": {"type": "track", "uri": "spotify:track:faketrack0000000000001"}}
    spotify.get(ITEMS, json={"items": [entry]})

    assert read_playlist_items(client, "fakeplaylist1")[0].uri is None


@pytest.mark.parametrize("playlist_id", ["", "../me", "fake/playlist", "fake?x=1", "x" * 65])
def test_an_odd_playlist_id_never_reaches_a_path(client: SpotifyClient, playlist_id: str) -> None:
    with pytest.raises(ValueError, match="isn't a Spotify playlist ID"):
        read_playlist_items(client, playlist_id)


def test_a_playlist_you_dont_own_raises_not_owner(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(ITEMS, status=403, json={"error": {"status": 403, "message": "Forbidden"}})

    with pytest.raises(NotOwner):
        read_playlist_items(client, "fakeplaylist1")


def test_items_stay_out_of_the_log(
    spotify: responses.RequestsMock, client: SpotifyClient, caplog: pytest.LogCaptureFixture
) -> None:
    page = json.loads((FIXTURES / "playlist_items_page.json").read_text(encoding="utf-8"))
    spotify.get(ITEMS, json=page)

    with caplog.at_level(logging.DEBUG):
        read_playlist_items(client, "fakeplaylist1")

    assert "Read 4 playlist items" in caplog.text
    for private in ("spotify:", "Fake+Local", "Fake Local Song", "fakeplaylist1"):
        assert private not in caplog.text


def test_a_retry_logs_neither_the_playlist_id_nor_the_items(
    spotify: responses.RequestsMock, client: SpotifyClient, caplog: pytest.LogCaptureFixture
) -> None:
    page = json.loads((FIXTURES / "playlist_items_page.json").read_text(encoding="utf-8"))
    spotify.get(ITEMS, status=503)
    spotify.get(ITEMS, status=429, headers={"Retry-After": "1"})
    spotify.get(ITEMS, body=requests.ConnectionError("reset"))
    spotify.get(ITEMS, json=page)

    with caplog.at_level(logging.DEBUG):
        read_playlist_items(client, "fakeplaylist1")

    assert "GET /playlists/{id}/items" in caplog.text
    for private in ("fakeplaylist1", "spotify:", "Fake Local Song"):
        assert private not in caplog.text


def test_an_items_repr_leaves_out_the_uri() -> None:
    item = PlaylistItem(0, "spotify:local:Fake+Artist:Fake+Album:Fake+Song:200", "track", True)

    assert "Fake" not in repr(item)
