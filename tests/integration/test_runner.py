"""A whole shuffle and Undo, end to end, against the fake Spotify.

The real SpotifyClient, item reader, cache, planner, backups and verify all run; only Spotify is
fake. Pacing sleeps are skipped.
"""

from __future__ import annotations

import random
import threading
from collections import Counter
from collections.abc import Iterator

import pytest
import responses
from fakes.fake_spotify import Call, FakeSpotify

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.shuffle import engine, runner
from fairshuffle.shuffle.runner import Mode, Options, Result, shuffle_playlist, undo_last_shuffle
from fairshuffle.spotify.cache import PlaylistItemsCache
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.errors import SpotifyUnavailable
from fairshuffle.spotify.ratelimit import RetryPolicy
from fairshuffle.storage import backups

LOCAL = "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"


def songs(count: int) -> list[str | None]:
    return [f"spotify:track:fake{number:05d}" for number in range(count)]


def quick(**changes: object) -> Options:
    options = Options(sleep=lambda _: None)
    for name, value in changes.items():
        setattr(options, name, value)
    return options


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
    """The app shuffles with secrets.SystemRandom; tests use a seeded source so they repeat.
    The seed is chosen so no test's order comes out unchanged."""
    rng = random.Random(4)  # noqa: S311  # tests want repeatable, not secret
    monkeypatch.setattr(runner, "shuffled", lambda items: engine.shuffled(items, rng))


@pytest.fixture
def cache() -> PlaylistItemsCache:
    return PlaylistItemsCache()


# Shuffling -------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [Mode.FAST, Mode.KEEP_ORDER])
@pytest.mark.parametrize("count", [2, 30, 260])
def test_a_shuffle_keeps_every_song_and_verifies(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache, mode: Mode, count: int
) -> None:
    playlist = fake.add_playlist("fakelist", songs(count))

    outcome = shuffle_playlist(client, cache, "fakelist", mode, quick())

    assert outcome.result is Result.DONE
    assert outcome.verdict is not None and outcome.verdict.ok
    assert Counter(playlist.uris) == Counter(songs(count))


def test_fast_mode_uses_a_handful_of_calls(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(500))

    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert [call.method for call in fake.writes()] == ["PUT"] + ["POST"] * 4


def test_keep_order_mode_keeps_dates_and_local_files(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", [*songs(20), LOCAL, None], local=frozenset({20}))
    dates = {entry.uri: entry.added_at for entry in playlist.entries}

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick())

    assert outcome.result is Result.DONE
    assert {entry.uri: entry.added_at for entry in playlist.entries} == dates
    assert all(call.body and "snapshot_id" in call.body for call in fake.writes())


def test_each_move_carries_the_snapshot_the_last_one_returned(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(10))
    fake.reject_stale_snapshot = True  # the strict reading: a stale snapshot_id is refused

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick())

    assert outcome.result is Result.DONE
    assert playlist.version == 1 + len(fake.writes())


def test_a_backup_is_saved_before_the_first_write(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(5))
    seen: list[object] = []

    def check(call: Call) -> None:
        if call.method != "GET" and not seen:
            seen.append(backups.newest("fakelist"))

    fake.before_request = check

    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    (backup,) = seen
    assert backup is not None
    assert [item.uri for item in backup.items] == songs(5)  # type: ignore[attr-defined]


def test_no_backup_means_no_shuffle(
    fake: FakeSpotify,
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake.add_playlist("fakelist", songs(5))

    def refuse(*_args: object) -> None:
        raise backups.BackupError("FairShuffle couldn't save a backup, so nothing was changed.")

    monkeypatch.setattr(runner.backups, "save", refuse)

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.FAILED, False)
    assert fake.writes() == []


@pytest.mark.parametrize("count", [0, 1])
def test_too_short_to_shuffle(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache, count: int
) -> None:
    fake.add_playlist("fakelist", songs(count))

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert outcome.result is Result.NOTHING_TO_DO
    assert fake.writes() == []


def test_progress_is_reported_after_each_write(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(250))
    seen: list[tuple[int, int]] = []

    shuffle_playlist(
        client, cache, "fakelist", Mode.FAST, quick(progress=lambda d, t: seen.append((d, t)))
    )

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_writes_are_paced(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(250))
    slept: list[float] = []

    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick(sleep=slept.append, pace=0.05))

    assert slept == [0.05] * 3


def test_an_order_that_comes_out_unchanged_needs_no_writes(
    fake: FakeSpotify,
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake.add_playlist("fakelist", songs(5))
    monkeypatch.setattr(runner, "shuffled", list)  # Fisher-Yates can land on the same order

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick())

    assert (outcome.result, outcome.changed) == (Result.DONE, False)
    assert fake.writes() == []


def test_the_cache_is_used_then_forgotten(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(60))

    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert len(cache) == 0  # forgotten after writing, so the next read is fresh


# Local files in fast mode (P4-2) -----------------------------------------------------------


def test_fast_mode_asks_before_removing_local_files(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", [*songs(5), LOCAL, None], local=frozenset({5}))

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.losses, outcome.changed) == (Result.NEEDS_CONFIRM, 2, False)
    assert fake.writes() == []


def test_shuffle_fast_anyway_drops_them_and_verifies(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", [*songs(5), LOCAL, None], local=frozenset({5}))

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick(allowed_losses=2))

    assert outcome.result is Result.DONE
    assert Counter(playlist.uris) == Counter(songs(5))


def test_a_playlist_of_only_local_files_needs_keep_order(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", [LOCAL, LOCAL], local=frozenset({0, 1}))

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick(allowed_losses=2))

    assert outcome.result is Result.FAILED
    assert "keep-order" in outcome.message
    assert fake.writes() == []


# Cancel, other editors and failures --------------------------------------------------------


def test_cancel_before_writing_changes_nothing(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(10))
    cancel = threading.Event()
    cancel.set()

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick(cancel=cancel))

    assert (outcome.result, outcome.changed) == (Result.CANCELLED, False)
    assert fake.writes() == []


def test_cancel_stops_between_moves_with_every_song_kept(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(40))
    cancel = threading.Event()

    def stop_after_five(done: int, _total: int) -> None:
        if done == 5:
            cancel.set()

    options = quick(cancel=cancel, progress=stop_after_five)
    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, options)

    assert (outcome.result, outcome.changed) == (Result.CANCELLED, True)
    assert len(fake.writes()) == 5
    assert Counter(playlist.uris) == Counter(songs(40))


def test_fast_mode_ignores_cancel_once_writing(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(250))
    cancel = threading.Event()

    outcome = shuffle_playlist(
        client, cache, "fakelist", Mode.FAST, quick(cancel=cancel, progress=lambda *_: cancel.set())
    )

    assert outcome.result is Result.DONE  # stopping after the replace would leave it short


def test_a_change_while_reading_stops_before_writing(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(60))

    def edit_once(call: Call) -> None:
        if call.path.endswith("/items") and playlist.version == 1:
            fake.edit("fakelist", songs(61))

    fake.before_request = edit_once

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.CHANGED_ELSEWHERE, False)
    assert fake.writes() == []


@pytest.mark.parametrize("mode", [Mode.FAST, Mode.KEEP_ORDER])
def test_snapshot_ids_named_apart_dont_stop_the_run(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache, mode: Mode
) -> None:
    """The live test (#31): GET /playlists/{id} never returned the snapshot_id a reorder did."""
    playlist = fake.add_playlist("fakelist", songs(60))
    fake.replies_name_versions_apart = True

    outcome = shuffle_playlist(client, cache, "fakelist", mode, quick(check_every=10))

    assert (outcome.result, outcome.verdict is not None and outcome.verdict.ok) == (
        Result.DONE,
        True,
    )
    assert Counter(playlist.uris) == Counter(songs(60))


def test_another_editor_moving_a_song_between_moves_stops_the_run(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(40))
    moved = [False]

    def move_one_before_the_check(call: Call) -> None:
        is_check = call.method == "GET" and call.path.endswith("/items")
        if is_check and len(fake.writes()) == 5 and not moved[0]:
            moved[0] = True
            fake.edit("fakelist", [*playlist.uris[1:], playlist.uris[0]])

    fake.before_request = move_one_before_the_check

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick(check_every=5))

    assert (outcome.result, outcome.changed) == (Result.CHANGED_ELSEWHERE, True)
    assert len(fake.writes()) == 5


def test_another_editor_between_moves_stops_the_run(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(40))

    def edit_before_the_check(call: Call) -> None:
        is_check = call.method == "GET" and call.path.endswith("/items")
        if is_check and len(fake.writes()) == 5 and playlist.uris[0] != "spotify:track:new":
            fake.edit("fakelist", ["spotify:track:new", *playlist.uris])

    fake.before_request = edit_before_the_check

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick(check_every=5))

    assert (outcome.result, outcome.changed) == (Result.CHANGED_ELSEWHERE, True)
    assert len(fake.writes()) == 5  # stopped at the next check, not at the end


def test_an_edit_landing_with_one_of_ours_is_caught_at_the_next_check(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    # Spotify's reply to our write already includes the other edit, so no snapshot_id could show
    # it; reading the songs back at the next check does.
    playlist = fake.add_playlist("fakelist", songs(40))

    def edit_with_the_fourth_move(call: Call) -> None:
        if call.method == "PUT" and len(fake.writes()) == 4:
            fake.edit("fakelist", [*playlist.uris, "spotify:track:new"])

    fake.before_request = edit_with_the_fourth_move

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick(check_every=5))

    assert (outcome.result, outcome.changed) == (Result.CHANGED_ELSEWHERE, True)
    assert len(fake.writes()) == 5


def test_an_edit_after_the_last_check_is_caught_by_the_read_back(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(40))

    def edit_with_the_fourth_move(call: Call) -> None:
        if call.method == "PUT" and len(fake.writes()) == 4:
            fake.edit("fakelist", [*playlist.uris, "spotify:track:new"])

    fake.before_request = edit_with_the_fourth_move

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick(check_every=1000))

    assert (outcome.result, outcome.changed) == (Result.NOT_VERIFIED, True)


def test_a_lost_reply_ends_the_run_and_offers_undo(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(250))
    fake.fail_next(None, applied=True, method="POST")

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.FAILED, True)
    assert "Undo" in outcome.message
    assert len(fake.writes()) == 2  # nothing sent twice


def test_a_refused_first_write_changes_nothing(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(5))
    fake.fail_next(400, method="PUT")  # refused: Spotify applied nothing

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.FAILED, False)


def test_a_server_error_on_a_write_may_have_applied(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(5))
    fake.fail_next(502, method="PUT")  # FairShuffle can't know whether it landed

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.FAILED, True)
    assert len(fake.writes()) == 1  # never sent twice


def test_rate_limits_are_waited_out(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(30))
    fake.fail_next(429, retry_after="1", method="PUT")

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick())

    assert outcome.result is Result.DONE


def test_someone_elses_playlist_fails_cleanly(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(5), editable=False)

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.FAILED, False)


def test_a_read_back_that_doesnt_match_is_not_verified(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(30))

    def sneak_in(call: Call) -> None:
        last_write = call.method == "GET" and call.path.endswith("/items") and fake.writes()
        if last_write and len(playlist.entries) == 30:
            fake.edit("fakelist", [*playlist.uris, "spotify:track:sneaky"])

    fake.before_request = sneak_in

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.NOT_VERIFIED, True)
    assert outcome.verdict is not None and outcome.verdict.extra == 1


def test_a_bug_of_ours_gives_a_fixed_message(
    fake: FakeSpotify,
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake.add_playlist("fakelist", songs(5))

    def broken(*_args: object) -> None:
        raise KeyError("fake bug")

    monkeypatch.setattr(runner, "fast_plan", broken)

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.message) == (Result.FAILED, runner.UNEXPECTED)
    assert not outcome.changed  # the plan is built before the first write
    assert fake.writes() == []


def test_a_bug_after_the_first_write_offers_undo(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(30))

    def broken(_done: int, _total: int) -> None:
        raise KeyError("fake bug")

    outcome = shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick(progress=broken))

    assert (outcome.result, outcome.changed) == (Result.FAILED, True)
    assert outcome.message.startswith(runner.UNEXPECTED)
    assert len(fake.writes()) == 1


def test_a_bad_playlist_id_changes_nothing(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(5))

    outcome = shuffle_playlist(client, cache, "not a playlist id", Mode.FAST, quick())

    assert (outcome.result, outcome.changed) == (Result.FAILED, False)
    assert fake.writes() == []


@pytest.mark.parametrize("mode", [Mode.FAST, Mode.KEEP_ORDER])
def test_a_failed_read_back_still_offers_undo(
    fake: FakeSpotify,
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    monkeypatch: pytest.MonkeyPatch,
    mode: Mode,
) -> None:
    fake.add_playlist("fakelist", songs(30))

    def unreachable(*_args: object) -> None:
        raise SpotifyUnavailable("Spotify isn't answering right now.")

    monkeypatch.setattr(runner, "read_playlist_items", unreachable)

    outcome = shuffle_playlist(client, cache, "fakelist", mode, quick())

    assert (outcome.result, outcome.changed) == (Result.FAILED, True)
    assert runner.PARTLY_DONE in outcome.message


# Undo --------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [Mode.FAST, Mode.KEEP_ORDER])
def test_undo_puts_the_old_order_back(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache, mode: Mode
) -> None:
    playlist = fake.add_playlist("fakelist", songs(120))
    shuffle_playlist(client, cache, "fakelist", mode, quick())
    assert playlist.uris != songs(120)

    outcome = undo_last_shuffle(client, cache, "fakelist", mode, quick())

    assert outcome.result is Result.DONE
    assert playlist.uris == songs(120)


def test_undo_after_a_cut_off_fast_shuffle(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(250))
    fake.fail_next(None, applied=True, method="POST")
    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())
    assert len(playlist.entries) == 200  # left short

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick())

    assert outcome.result is Result.DONE
    assert playlist.uris == songs(250)


def test_undo_does_not_save_a_new_backup(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(10))
    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())
    before = backups.newest("fakelist")

    undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick())

    assert backups.newest("fakelist") == before


def test_undo_without_a_backup(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", songs(10))

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick())

    assert outcome.result is Result.FAILED
    assert fake.writes() == []


def test_keep_order_undo_refuses_when_songs_were_added(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(10))
    shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick())
    fake.edit("fakelist", [*playlist.uris, "spotify:track:new"])

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.KEEP_ORDER, quick())

    assert outcome.result is Result.FAILED
    assert "Fast mode can" in outcome.message


def test_fast_undo_asks_before_removing_songs_added_since(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(10))
    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())
    fake.edit("fakelist", [*playlist.uris, "spotify:track:new"])
    writes = len(fake.writes())

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.losses, outcome.changed) == (Result.NEEDS_CONFIRM, 1, False)
    assert "added since" in outcome.message
    assert len(fake.writes()) == writes

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick(allowed_losses=1))

    assert outcome.result is Result.DONE
    assert playlist.uris == songs(10)


def test_fast_undo_asks_before_dropping_local_files_kept_by_keep_order(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    fake.add_playlist("fakelist", [*songs(5), LOCAL], local=frozenset({5}))
    shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick())

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick())

    assert (outcome.result, outcome.losses) == (Result.NEEDS_CONFIRM, 1)


def test_fast_undo_of_only_local_files_needs_keep_order(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    other = LOCAL.replace("215", "216")
    fake.add_playlist("fakelist", [LOCAL, other], local=frozenset({0, 1}))
    shuffle_playlist(client, cache, "fakelist", Mode.KEEP_ORDER, quick())
    writes = len(fake.writes())

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick(allowed_losses=2))

    assert (outcome.result, outcome.changed) == (Result.FAILED, False)
    assert "keep-order" in outcome.message
    assert len(fake.writes()) == writes


def test_agreeing_to_some_losses_does_not_cover_more(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", songs(10))
    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick())
    fake.edit("fakelist", [*playlist.uris, "spotify:track:new"])
    asked = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick())
    fake.edit("fakelist", [*playlist.uris, "spotify:track:newer"])  # a collaborator, meanwhile
    writes = len(fake.writes())

    outcome = undo_last_shuffle(
        client, cache, "fakelist", Mode.FAST, quick(allowed_losses=asked.losses)
    )

    assert (outcome.result, outcome.losses) == (Result.NEEDS_CONFIRM, 2)
    assert len(fake.writes()) == writes


def test_fast_undo_says_what_it_could_not_put_back(
    fake: FakeSpotify, client: SpotifyClient, cache: PlaylistItemsCache
) -> None:
    playlist = fake.add_playlist("fakelist", [*songs(5), LOCAL], local=frozenset({5}))
    shuffle_playlist(client, cache, "fakelist", Mode.FAST, quick(allowed_losses=1))

    outcome = undo_last_shuffle(client, cache, "fakelist", Mode.FAST, quick())

    assert outcome.result is Result.DONE
    assert playlist.uris == songs(5)
    assert outcome.message == ("1 local files or songs Spotify no longer has couldn't be put back.")
