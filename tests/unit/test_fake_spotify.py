"""The fake Spotify behaves the way the Web API reference describes, so the shuffle's tests
against it mean something. Each test goes through the real SpotifyClient."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import responses
from fakes.fake_spotify import FakeSpotify, reordered

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.errors import (
    NotOwner,
    RateLimited,
    RequestRejected,
    SpotifyUnavailable,
)
from fairshuffle.spotify.playlists import read_playlist_items
from fairshuffle.spotify.ratelimit import RetryPolicy

ITEMS = "/playlists/fakelist/items"


def songs(count: int) -> list[str | None]:
    return [f"spotify:track:fake{number:04d}" for number in range(count)]


@pytest.fixture
def fake() -> Iterator[FakeSpotify]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield FakeSpotify(mock)


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        auth = SpotifyAuth(http, load_settings(), tokens)
        yield SpotifyClient(auth, RetryPolicy(max_attempts=3), sleep=lambda _: None)


# Reading ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 1, 50, 51, 120])
def test_items_come_back_in_pages_of_50(
    fake: FakeSpotify, client: SpotifyClient, count: int
) -> None:
    fake.add_playlist("fakelist", songs(count))

    items = read_playlist_items(client, "fakelist")

    assert [item.uri for item in items] == songs(count)
    assert len(fake.calls) == max(1, -(-count // 50))


def test_local_files_episodes_and_unavailable_items_read_back(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    uris: list[str | None] = [
        "spotify:track:fake0001",
        "spotify:episode:fake0002",
        "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215",
        None,
    ]
    fake.add_playlist("fakelist", uris, local=frozenset({2}))

    items = read_playlist_items(client, "fakelist")

    assert [(i.uri, i.kind, i.is_local) for i in items] == [
        ("spotify:track:fake0001", "track", False),
        ("spotify:episode:fake0002", "episode", False),
        ("spotify:local:Fake+Artist:Fake+Album:Fake+Song:215", "track", True),
        (None, None, False),
    ]


def test_the_playlist_object_carries_snapshot_and_total(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))

    reply = client.get("/playlists/fakelist")

    assert reply["snapshot_id"] == playlist.snapshot_id
    assert reply["items"]["total"] == 3


def test_someone_elses_playlist_is_refused(fake: FakeSpotify, client: SpotifyClient) -> None:
    fake.add_playlist("fakelist", songs(3), editable=False)

    with pytest.raises(NotOwner):
        read_playlist_items(client, "fakelist")


def test_an_unknown_playlist_is_404(fake: FakeSpotify, client: SpotifyClient) -> None:
    with pytest.raises(RequestRejected) as raised:
        client.get("/playlists/nosuchlist")

    assert raised.value.status == 404


# Reorder ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "before", "length", "expected"),
    [
        (0, 5, 1, "BCDEAF"),  # first item to just before the sixth
        (5, 0, 1, "FABCDE"),  # last item to the top
        (0, 6, 1, "BCDEFA"),  # insert_before the length means the end
        (1, 4, 2, "ADBCEF"),  # a block of two
        (4, 1, 2, "AEFBCD"),
        (2, 2, 1, "ABCDEF"),  # into its own place: nothing moves
        (2, 3, 1, "ABCDEF"),
        (1, 2, 3, "ABCDEF"),  # inside its own range
    ],
)
def test_reorder_moves_a_range_like_spotify(
    start: int, before: int, length: int, expected: str
) -> None:
    assert "".join(reordered(list("ABCDEF"), start, before, length)) == expected


def test_reorder_keeps_added_at_and_changes_snapshot(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    playlist = fake.add_playlist("fakelist", songs(4), local=frozenset({3}))
    stamps = {entry.uri: entry.added_at for entry in playlist.entries}
    old_snapshot = playlist.snapshot_id

    move = {"range_start": 3, "insert_before": 0, "range_length": 1, "snapshot_id": old_snapshot}
    reply = client.put(ITEMS, move)

    assert playlist.uris == [songs(4)[3], *songs(3)]
    assert playlist.entries[0].is_local  # a local file can be moved
    assert {entry.uri: entry.added_at for entry in playlist.entries} == stamps
    assert reply["snapshot_id"] == playlist.snapshot_id != old_snapshot


@pytest.mark.parametrize(
    "body",
    [
        {"range_start": 4, "insert_before": 0},  # past the end
        {"range_start": -1, "insert_before": 0},
        {"range_start": 0, "insert_before": 5},
        {"range_start": 2, "insert_before": 0, "range_length": 3},  # runs off the end
        {"range_start": 0, "insert_before": 1, "range_length": 0},
        {"range_start": "0", "insert_before": 1},
        {"range_start": True, "insert_before": 1},
        {"range_start": 0, "insert_before": 1, "uris": ["spotify:track:fake0000"]},  # both kinds
        {},
    ],
)
def test_bad_writes_are_refused_and_change_nothing(
    fake: FakeSpotify, client: SpotifyClient, body: dict[str, object]
) -> None:
    playlist = fake.add_playlist("fakelist", songs(4))

    with pytest.raises(RequestRejected) as raised:
        client.put(ITEMS, body)

    assert raised.value.status == 400
    assert playlist.uris == songs(4)
    assert playlist.version == 1


# Replace and add -------------------------------------------------------------------------------


def test_replace_overwrites_with_new_added_at(fake: FakeSpotify, client: SpotifyClient) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))
    stamps = {entry.added_at for entry in playlist.entries}
    new_order = list(reversed(songs(3)))

    reply = client.put(ITEMS, {"uris": new_order})

    assert playlist.uris == new_order
    assert stamps.isdisjoint(entry.added_at for entry in playlist.entries)
    assert reply == {"snapshot_id": playlist.snapshot_id}


def test_replace_with_nothing_clears_the_playlist(fake: FakeSpotify, client: SpotifyClient) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))

    client.put(ITEMS, {"uris": []})

    assert playlist.uris == []


def test_add_appends_or_inserts_and_answers_201(fake: FakeSpotify, client: SpotifyClient) -> None:
    playlist = fake.add_playlist("fakelist", songs(2))

    client.post(ITEMS, {"uris": ["spotify:episode:fakeep01"]})
    client.post(ITEMS, {"uris": ["spotify:track:fakefirst"], "position": 0})

    assert playlist.uris == ["spotify:track:fakefirst", *songs(2), "spotify:episode:fakeep01"]
    assert playlist.version == 3


def test_replace_then_add_rebuilds_a_long_playlist(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    playlist = fake.add_playlist("fakelist", songs(250))
    target = list(reversed(songs(250)))

    client.put(ITEMS, {"uris": target[:100]})
    client.post(ITEMS, {"uris": target[100:200]})
    client.post(ITEMS, {"uris": target[200:]})

    assert playlist.uris == target


@pytest.mark.parametrize(
    ("method", "body"),
    [
        ("PUT", {"uris": songs(101)}),  # more than 100
        ("POST", {"uris": songs(101)}),
        ("PUT", {"uris": ["spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"]}),
        ("POST", {"uris": ["spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"]}),
        ("PUT", {"uris": ["not-a-uri"]}),
        ("PUT", {"uris": "spotify:track:fake0000"}),
        ("POST", {"uris": []}),
        ("POST", {"uris": songs(1), "position": 9}),
        ("POST", {"uris": songs(1), "position": -1}),
    ],
)
def test_bad_replace_or_add_is_refused(
    fake: FakeSpotify, client: SpotifyClient, method: str, body: dict[str, object]
) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))

    with pytest.raises(RequestRejected):
        client.request(method, ITEMS, body=body)

    assert playlist.uris == songs(3)


def test_uris_on_the_query_string_are_refused(fake: FakeSpotify, client: SpotifyClient) -> None:
    fake.add_playlist("fakelist", songs(3))

    with pytest.raises(RequestRejected):
        client.request("PUT", ITEMS, params={"uris": "spotify:track:fake0000"}, body={})
    with pytest.raises(RequestRejected):
        client.request("POST", ITEMS, params={"uris": "spotify:track:fake0000"}, body={})


# Faults and other editors ----------------------------------------------------------------------


def test_a_429_is_waited_out_and_the_write_lands_once(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))
    fake.fail_next(429, retry_after="2", method="PUT")

    client.put(ITEMS, {"range_start": 0, "insert_before": 3})

    assert playlist.uris == [*songs(3)[1:], songs(3)[0]]
    assert [call.method for call in fake.writes()] == ["PUT", "PUT"]


def test_quota_style_429_storms_end_in_rate_limited(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    fake.add_playlist("fakelist", songs(3))
    for _ in range(3):
        fake.fail_next(429, retry_after="1")

    with pytest.raises(RateLimited):
        client.get("/playlists/fakelist")


def test_a_reply_lost_after_the_change_reports_may_have_applied(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))
    fake.fail_next(None, applied=True, method="PUT")

    with pytest.raises(SpotifyUnavailable) as raised:
        client.put(ITEMS, {"range_start": 0, "insert_before": 3})

    assert raised.value.may_have_applied
    assert playlist.version == 2  # it did land


def test_a_5xx_before_the_change_leaves_the_playlist_alone(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))
    fake.fail_next(502, method="PUT")

    with pytest.raises(SpotifyUnavailable):
        client.put(ITEMS, {"range_start": 0, "insert_before": 3})

    assert playlist.version == 1


def test_faults_for_one_method_skip_the_others(fake: FakeSpotify, client: SpotifyClient) -> None:
    fake.add_playlist("fakelist", songs(3))
    fake.fail_next(502, method="PUT")

    client.get("/playlists/fakelist")  # not the PUT the fault waits for

    assert len(fake.faults) == 1


def test_another_editor_changes_the_snapshot(fake: FakeSpotify, client: SpotifyClient) -> None:
    playlist = fake.add_playlist("fakelist", songs(3))
    first = client.get("/playlists/fakelist")["snapshot_id"]

    def someone_edits(call: object) -> None:
        if playlist.version == 1:
            fake.edit("fakelist", songs(2))

    fake.before_request = someone_edits
    second = client.get("/playlists/fakelist")["snapshot_id"]

    assert second != first
    assert playlist.uris == songs(2)


def test_calls_are_recorded_with_their_bodies(fake: FakeSpotify, client: SpotifyClient) -> None:
    fake.add_playlist("fakelist", songs(3))

    client.put(ITEMS, {"range_start": 0, "insert_before": 2, "snapshot_id": "fake-old"})

    (call,) = fake.writes()
    assert call.path == "/v1" + ITEMS
    assert call.body == {"range_start": 0, "insert_before": 2, "snapshot_id": "fake-old"}
