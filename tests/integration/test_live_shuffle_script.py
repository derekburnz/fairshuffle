"""The live test script (#31) picks only "Shuffle Test" and checks every run, against the fake.

The script itself is run by hand against the real Spotify; these tests run its logic on the fake
Spotify so a mistake in it can't reach Derek's playlists.
"""

from __future__ import annotations

import importlib.util
import random
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import responses
from fakes.fake_spotify import Call, FakeSpotify
from PySide6.QtCore import QLockFile

from fairshuffle.app import default_instance_key
from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.shuffle import engine, runner
from fairshuffle.spotify.cache import PlaylistItemsCache
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.models import Playlist
from fairshuffle.spotify.ratelimit import RetryPolicy

SCRIPT = Path(__file__).parents[2] / "scripts" / "live_shuffle_test.py"
LOCAL = "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_shuffle_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def songs(count: int) -> list[str | None]:
    return [f"spotify:track:fake{number:05d}" for number in range(count)]


def playlist(playlist_id: str, name: str, owner: str, collaborative: bool = False) -> Playlist:
    return Playlist(playlist_id, name, owner, collaborative, "fake-snapshot", 30)


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


@pytest.fixture(autouse=True)
def repeatable_shuffle(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = random.Random(4)  # noqa: S311  # tests want repeatable, not secret
    monkeypatch.setattr(runner, "shuffled", lambda items: engine.shuffled(items, rng))


# Picking the playlist --------------------------------------------------------------------------


def test_the_one_owned_shuffle_test_playlist_is_picked() -> None:
    lists = [playlist("a1", "Road Trip", "fake-user"), playlist("b2", "Shuffle Test", "fake-user")]

    assert script.find_test_playlist(lists, "fake-user").id == "b2"


@pytest.mark.parametrize(
    "lists",
    [
        [],
        [playlist("a1", "shuffle test", "fake-user")],  # the name must match exactly
        [playlist("a1", "Shuffle Test ", "fake-user")],
        [playlist("a1", "Shuffle Test", "someone-else", collaborative=True)],
        [playlist("a1", "Shuffle Test", "fake-user"), playlist("b2", "Shuffle Test", "fake-user")],
    ],
    ids=["none", "case", "trailing-space", "not-owned", "two"],
)
def test_anything_but_exactly_one_is_refused(lists: list[Playlist]) -> None:
    with pytest.raises(script.SetupError):
        script.find_test_playlist(lists, "fake-user")


# Running it ------------------------------------------------------------------------------------


def test_ten_shuffles_and_an_undo_all_verify(fake: FakeSpotify, client: SpotifyClient) -> None:
    fake.add_playlist("fakelist", songs(30))
    lines: list[str] = []

    passed = script.live_test(client, PlaylistItemsCache(), "fakelist", lines.append, pace=0)

    assert passed, lines
    assert len(lines) == 12  # 10 runs, the Undo, the summary
    assert all("verified" in line for line in lines)
    assert sum("fast" in line for line in lines[:10]) == 5


def test_the_output_names_no_songs(fake: FakeSpotify, client: SpotifyClient) -> None:
    fake.add_playlist("fakelist", songs(30))
    lines: list[str] = []

    script.live_test(client, PlaylistItemsCache(), "fakelist", lines.append, pace=0)

    assert not any("spotify:" in line or "fakelist" in line for line in lines)


def test_it_passes_when_snapshot_ids_are_named_apart_as_live(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    """The first live run (#31) stopped at run 6 on this; the songs check doesn't."""
    fake.add_playlist("fakelist", songs(60))
    fake.replies_name_versions_apart = True
    lines: list[str] = []

    passed = script.live_test(client, PlaylistItemsCache(), "fakelist", lines.append, pace=0)

    assert passed, lines


def test_it_stops_at_the_first_failure(fake: FakeSpotify, client: SpotifyClient) -> None:
    fake.add_playlist("fakelist", songs(30))
    fake.fail_next(400, method="PUT")
    lines: list[str] = []

    passed = script.live_test(client, PlaylistItemsCache(), "fakelist", lines.append, pace=0)

    assert not passed
    assert len(lines) == 1 and "FAILED" in lines[0]


def test_local_files_stop_it_before_fast_mode_removes_them(
    fake: FakeSpotify, client: SpotifyClient
) -> None:
    pl = fake.add_playlist("fakelist", [*songs(29), LOCAL], local=frozenset({29}))
    lines: list[str] = []

    passed = script.live_test(client, PlaylistItemsCache(), "fakelist", lines.append, pace=0)

    assert not passed
    assert "NEEDS_CONFIRM" in lines[0]
    assert pl.uris == [*songs(29), LOCAL]
    assert fake.writes() == []


def test_a_run_cut_off_after_writing_is_put_back(fake: FakeSpotify, client: SpotifyClient) -> None:
    pl = fake.add_playlist("fakelist", songs(30))
    fake.fail_next(None, applied=True, method="PUT")  # the replace lands, its reply is lost
    lines: list[str] = []

    passed = script.live_test(client, PlaylistItemsCache(), "fakelist", lines.append, pace=0)

    assert not passed
    assert "FAILED" in lines[0]
    assert lines[1].startswith("Put the order from before that run back")
    assert pl.uris == songs(30)


# The app's lock --------------------------------------------------------------------------------


def test_the_lock_is_refused_while_the_app_holds_it(tmp_path: Path) -> None:
    app = QLockFile(str(tmp_path / f"{default_instance_key()}.lock"))
    assert app.tryLock(0)
    try:
        with pytest.raises(script.SetupError, match="FairShuffle is running"):
            script.hold_app_lock(tmp_path)
    finally:
        app.unlock()


def test_the_lock_is_taken_when_the_app_is_not_running(tmp_path: Path) -> None:
    lock = script.hold_app_lock(tmp_path)
    try:
        assert lock.isLocked()
    finally:
        lock.unlock()


def test_a_run_stopped_before_writing_is_not_put_back(
    fake: FakeSpotify, client: SpotifyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pl = fake.add_playlist("fakelist", songs(30))
    monkeypatch.setattr(runner, "SETTLE_SECONDS", 0)
    item_reads = [0]

    def edit_during_the_runners_reads(call: Call) -> None:
        if call.method == "GET" and call.path.endswith("/items") and not fake.writes():
            item_reads[0] += 1
            if item_reads[0] >= 3:  # the script read it twice; these are the runner's tries
                fake.edit("fakelist", [*pl.uris, "spotify:track:new"])

    fake.before_request = edit_during_the_runners_reads
    lines: list[str] = []

    passed = script.live_test(client, PlaylistItemsCache(), "fakelist", lines.append, pace=0)

    assert not passed
    assert lines == [lines[0]] and "CHANGED_ELSEWHERE" in lines[0]
    assert fake.writes() == []
