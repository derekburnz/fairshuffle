"""The controller behind the picker's Shuffle, Undo and Cancel buttons."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fakes.ui_fakes import FakeAccount, HeldJobs, playlist
from PySide6.QtWidgets import QApplication

from fairshuffle.shuffle.runner import UNEXPECTED, Mode, Options, Outcome, Result
from fairshuffle.spotify.cache import PlaylistItemsCache
from fairshuffle.spotify.models import PlaylistItem
from fairshuffle.storage import backups, settings
from fairshuffle.ui.shuffle import Action, Finished, Progress, ShuffleController


class Recorder:
    """Stands in for shuffle_playlist or undo_last_shuffle and remembers each call."""

    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[Any, str, Mode, Options]] = []

    def __call__(
        self, client: Any, _cache: Any, playlist_id: str, mode: Mode, options: Options
    ) -> Outcome:
        self.calls.append((client, playlist_id, mode, options))
        return self.outcome


@pytest.fixture
def account(qapp: QApplication) -> FakeAccount:
    return FakeAccount()


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def cache() -> PlaylistItemsCache:
    return PlaylistItemsCache()


@pytest.fixture
def controller(
    account: FakeAccount, jobs: HeldJobs, cache: PlaylistItemsCache
) -> ShuffleController:
    return ShuffleController(account, cache, runner=jobs)  # type: ignore[arg-type]


@pytest.fixture
def shuffle(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder(Outcome(Result.DONE, changed=True))
    monkeypatch.setattr("fairshuffle.ui.shuffle.shuffle_playlist", recorder)
    return recorder


@pytest.fixture
def undo(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder(Outcome(Result.DONE, changed=True))
    monkeypatch.setattr("fairshuffle.ui.shuffle.undo_last_shuffle", recorder)
    return recorder


def collect(controller: ShuffleController) -> tuple[list[Progress | None], list[Finished]]:
    running: list[Progress | None] = []
    finished: list[Finished] = []
    controller.running_changed.connect(running.append)
    controller.finished.connect(finished.append)
    return running, finished


def test_fast_mode_is_the_default(controller: ShuffleController) -> None:
    assert not controller.keep_date_added
    assert controller.mode is Mode.FAST


def test_the_keep_date_added_choice_is_remembered(
    account: FakeAccount, controller: ShuffleController
) -> None:
    controller.set_keep_date_added(True)

    assert controller.mode is Mode.KEEP_ORDER
    assert settings.load().keep_date_added
    later = ShuffleController(account, runner=HeldJobs())  # type: ignore[arg-type]
    assert later.keep_date_added


def test_a_shuffle_runs_off_the_main_thread_and_reports_how_it_ended(
    controller: ShuffleController, jobs: HeldJobs, shuffle: Recorder, account: FakeAccount
) -> None:
    running, finished = collect(controller)
    target = playlist(1, "Road Trip")

    assert controller.shuffle(target)
    assert controller.running == Progress(Action.SHUFFLE, target)
    assert len(jobs.jobs) == 1
    assert shuffle.calls == []  # nothing runs until the worker picks it up

    jobs.release()

    [(client, playlist_id, mode, options)] = shuffle.calls
    assert client is account.client
    assert (playlist_id, mode, options.allowed_losses) == ("fakeplaylist1", Mode.FAST, 0)
    assert options.cancel is not None and options.progress is not None
    assert running == [Progress(Action.SHUFFLE, target), None]
    assert finished == [Finished(Action.SHUFFLE, target, Mode.FAST, shuffle.outcome)]
    assert controller.running is None


def test_the_keep_order_choice_picks_the_mode(
    controller: ShuffleController, jobs: HeldJobs, shuffle: Recorder
) -> None:
    controller.set_keep_date_added(True)
    controller.shuffle(playlist(1))
    jobs.release()

    assert shuffle.calls[0][2] is Mode.KEEP_ORDER


def test_a_rerun_after_the_question_carries_the_mode_and_allowed_losses(
    controller: ShuffleController, jobs: HeldJobs, shuffle: Recorder
) -> None:
    controller.shuffle(playlist(1), Mode.FAST, allowed_losses=3)
    jobs.release()

    assert shuffle.calls[0][2] is Mode.FAST
    assert shuffle.calls[0][3].allowed_losses == 3


def test_only_one_run_at_a_time(
    controller: ShuffleController, jobs: HeldJobs, shuffle: Recorder, undo: Recorder
) -> None:
    assert controller.shuffle(playlist(1))
    assert not controller.shuffle(playlist(2))
    assert not controller.undo(playlist(1))
    assert len(jobs.jobs) == 1


def test_nothing_starts_while_signed_out(
    account: FakeAccount, controller: ShuffleController, jobs: HeldJobs
) -> None:
    account.sign_out()

    assert not controller.shuffle(playlist(1))
    assert not controller.undo(playlist(1))
    assert jobs.jobs == []


def test_undo_runs_the_undo(controller: ShuffleController, jobs: HeldJobs, undo: Recorder) -> None:
    _running, finished = collect(controller)
    controller.undo(playlist(1), Mode.KEEP_ORDER)
    jobs.release()

    assert undo.calls[0][1:3] == ("fakeplaylist1", Mode.KEEP_ORDER)
    assert finished[0].action is Action.UNDO


def test_progress_from_the_worker_reaches_the_status(
    controller: ShuffleController, jobs: HeldJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    running, _finished = collect(controller)
    seen: list[Progress | None] = []

    def work(_client: Any, _cache: Any, _id: str, _mode: Mode, options: Options) -> Outcome:
        assert options.progress is not None
        options.progress(1, 3)
        options.progress(2, 3)
        seen.append(controller.running)
        return Outcome(Result.DONE, changed=True)

    monkeypatch.setattr("fairshuffle.ui.shuffle.shuffle_playlist", work)
    target = playlist(1)
    controller.shuffle(target)
    jobs.release()

    assert seen == [Progress(Action.SHUFFLE, target, 2, 3)]
    assert running[-1] is None


def test_progress_from_a_real_worker_thread_is_queued_to_the_main_thread(
    controller: ShuffleController, qapp: QApplication
) -> None:
    target = playlist(1)
    controller._running = Progress(Action.SHUFFLE, target)  # as _start leaves it
    thread = threading.Thread(target=lambda: controller._relay.progress.emit(5, 9))
    thread.start()
    thread.join()

    assert controller.running == Progress(Action.SHUFFLE, target)  # not applied off-thread
    qapp.processEvents()
    assert controller.running == Progress(Action.SHUFFLE, target, 5, 9)


def test_cancel_sets_the_runs_cancel_flag(
    controller: ShuffleController, jobs: HeldJobs, shuffle: Recorder
) -> None:
    controller.shuffle(playlist(1))
    controller.cancel()
    jobs.release()

    assert shuffle.calls[0][3].cancel is not None and shuffle.calls[0][3].cancel.is_set()


def test_signing_out_cancels_a_run_and_empties_the_cache(
    account: FakeAccount,
    controller: ShuffleController,
    jobs: HeldJobs,
    shuffle: Recorder,
    cache: PlaylistItemsCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleared: list[bool] = []
    monkeypatch.setattr(cache, "clear", lambda: cleared.append(True))
    controller.shuffle(playlist(1))
    account.sign_out()
    jobs.release()

    assert shuffle.calls[0][3].cancel is not None and shuffle.calls[0][3].cancel.is_set()
    assert cleared == [True]


def test_a_crashed_job_still_ends_the_run_and_offers_undo(
    controller: ShuffleController, jobs: HeldJobs
) -> None:
    _running, finished = collect(controller)
    controller._run = lambda _job, done: done(None)  # the pool's answer when a job raised
    controller.shuffle(playlist(1))

    assert finished[0].outcome == Outcome(Result.FAILED, changed=True, message=UNEXPECTED)
    assert controller.running is None


def test_quit_cancels_and_waits_for_a_running_shuffle(
    account: FakeAccount, shuffle: Recorder
) -> None:
    waits: list[int] = []
    jobs = HeldJobs()
    controller = ShuffleController(
        account,  # type: ignore[arg-type]
        runner=jobs,
        wait_for_jobs=lambda ms: waits.append(ms) or True,
    )
    controller.shutdown()
    assert waits == []  # nothing running: Quit doesn't wait

    controller.shuffle(playlist(1))
    controller.shutdown()

    assert waits == [10_000]
    jobs.release()
    assert shuffle.calls[0][3].cancel is not None and shuffle.calls[0][3].cancel.is_set()


def test_undo_is_offered_once_a_backup_exists(controller: ShuffleController) -> None:
    assert not controller.has_backup("fakeplaylist1")
    assert not controller.has_backup("../not-an-id")

    backups.save(
        "fakeplaylist1", "fake-snapshot-1", [PlaylistItem(0, "spotify:track:a", "track", False)]
    )

    assert controller.has_backup("fakeplaylist1")
    assert not controller.has_backup("fakeplaylist2")


def test_a_backups_folder_that_cant_be_listed_hides_undo(
    controller: ShuffleController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_playlist_id: str) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(backups, "newest", refuse)

    assert not controller.has_backup("fakeplaylist1")
