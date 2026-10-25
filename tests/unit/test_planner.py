"""The plan builder's writes give exactly the shuffled order when replayed, before any real call.

Fast plans are replayed against the fake Spotify, keep-order plans with its reorder rule, so the
check doesn't reuse the planner's own idea of how a move works.
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Iterator

import pytest
import responses
from fakes.fake_spotify import FakeSpotify, reordered

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.shuffle.engine import shuffled
from fairshuffle.shuffle.planner import (
    MAX_URIS_PER_WRITE,
    Append,
    Move,
    Replace,
    fast_mode_losses,
    fast_plan,
    reorder_plan,
    uri_plan,
)
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.models import PlaylistItem

ITEMS = "/playlists/fakelist/items"
LOCAL = "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"


def seeded(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311  # tests want repeatable, not secret


def song(number: int) -> PlaylistItem:
    return PlaylistItem(number, f"spotify:track:fake{number:05d}", "track", is_local=False)


def songs(count: int) -> list[PlaylistItem]:
    return [song(number) for number in range(count)]


def replay(moves: list[Move], count: int) -> list[int]:
    entries = list(range(count))
    for move in moves:
        entries = reordered(entries, move.range_start, move.insert_before, 1)
    return entries


@pytest.fixture
def fake() -> Iterator[FakeSpotify]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield FakeSpotify(mock)


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        yield SpotifyClient(SpotifyAuth(http, load_settings(), tokens), sleep=lambda _: None)


# Keep-order mode -------------------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 1, 2, 3, 10, 500])
def test_replaying_the_moves_gives_the_target(count: int) -> None:
    target = shuffled(range(count), seeded(count))

    moves = reorder_plan(target)

    assert replay(moves, count) == target
    assert len(moves) <= max(count - 1, 0)


def test_every_order_of_four_is_reached_in_at_most_three_moves() -> None:
    for order in itertools.permutations(range(4)):
        moves = reorder_plan(order)
        assert replay(moves, 4) == list(order)
        assert len(moves) <= 3


def test_entries_already_in_place_are_not_moved() -> None:
    assert reorder_plan([0, 1, 2, 3]) == []
    assert reorder_plan([0, 1, 3, 2]) == [Move(range_start=3, insert_before=2)]


def test_moves_always_go_up_into_place() -> None:
    moves = reorder_plan(shuffled(range(50), seeded(1)))

    assert all(move.insert_before < move.range_start for move in moves)


@pytest.mark.parametrize("target", [[0, 0], [1, 2], [0, 1, 1], [-1, 0], [0, 2]])
def test_a_target_that_isnt_a_permutation_is_refused(target: list[int]) -> None:
    with pytest.raises(ValueError, match="exactly once"):
        reorder_plan(target)


def test_keep_order_moves_keep_dates_and_local_files_on_the_fake(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    uris: list[str | None] = [*(f"spotify:track:fake{n:05d}" for n in range(8)), LOCAL, None]
    playlist = fake.add_playlist("fakelist", uris, local=frozenset({8}))
    stamps = [entry.added_at for entry in playlist.entries]
    target = shuffled(range(10), seeded(7))

    for move in reorder_plan(target):
        client.put(ITEMS, {"range_start": move.range_start, "insert_before": move.insert_before})

    assert playlist.uris == [uris[k] for k in target]
    assert [entry.added_at for entry in playlist.entries] == [stamps[k] for k in target]


# Fast mode -------------------------------------------------------------------------------------


@pytest.mark.parametrize(("count", "calls"), [(1, 1), (100, 1), (101, 2), (250, 3), (500, 5)])
def test_fast_plan_replaces_then_adds_in_chunks(count: int, calls: int) -> None:
    target = shuffled(songs(count), seeded(count))

    plan = fast_plan(target)

    assert len(plan) == calls
    assert isinstance(plan[0], Replace)
    assert all(isinstance(write, Append) for write in plan[1:])
    assert all(1 <= len(write.uris) <= MAX_URIS_PER_WRITE for write in plan)
    assert [uri for write in plan for uri in write.uris] == [item.uri for item in target]


def test_replaying_the_fast_plan_on_the_fake_gives_the_target(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    items = songs(260)
    playlist = fake.add_playlist("fakelist", [item.uri for item in items])
    target = shuffled(items, seeded(3))

    for write in fast_plan(target):
        method = "PUT" if isinstance(write, Replace) else "POST"
        client.request(method, ITEMS, body={"uris": list(write.uris)})

    assert playlist.uris == [item.uri for item in target]


def test_duplicates_and_episodes_are_written_in_fast_mode() -> None:
    items = [
        song(0),
        PlaylistItem(1, "spotify:track:fake00000", "track", is_local=False),  # song 0 again
        PlaylistItem(2, "spotify:episode:fakeep", "episode", is_local=False),
    ]

    plan = fast_plan(items)

    assert plan == [Replace(("spotify:track:fake00000",) * 2 + ("spotify:episode:fakeep",))]


def test_local_files_and_missing_items_are_counted_and_left_out() -> None:
    items = [
        song(0),
        PlaylistItem(1, LOCAL, "track", is_local=True),
        PlaylistItem(2, None, None, is_local=False),
        song(3),
    ]

    assert fast_mode_losses(items) == 2
    assert fast_plan(items) == [Replace((song(0).uri or "", song(3).uri or ""))]


def test_nothing_lost_in_a_plain_playlist() -> None:
    assert fast_mode_losses(songs(5)) == 0


@pytest.mark.parametrize(
    "items",
    [[], [PlaylistItem(0, LOCAL, "track", is_local=True), PlaylistItem(1, None, None, False)]],
)
def test_fast_mode_never_empties_a_playlist(items: list[PlaylistItem]) -> None:
    with pytest.raises(ValueError, match="keep-order|fast mode"):
        fast_plan(items)


def test_a_local_uri_without_its_flag_is_still_left_out() -> None:
    items = [song(0), PlaylistItem(1, LOCAL, "track", is_local=False)]

    assert fast_mode_losses(items) == 1
    assert fast_plan(items) == [Replace((song(0).uri or "",))]


def test_a_uri_plan_needs_at_least_one_uri() -> None:
    with pytest.raises(ValueError):
        uri_plan([])
