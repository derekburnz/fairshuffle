"""The picker's Shuffle, Undo and Cancel buttons, the keep-order box and the dialogs (#32)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fakes.ui_fakes import FakeAccount, HeldJobs, playlist
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from fairshuffle.shuffle.runner import Mode, Options, Outcome, Result
from fairshuffle.spotify.models import PlaylistItem
from fairshuffle.storage import backups
from fairshuffle.ui.picker import (
    KEEP_DATE_ADDED,
    NOT_PUT_BACK,
    PlaylistPicker,
    finished_text,
    quoted,
    running_text,
)
from fairshuffle.ui.playlists import PlaylistController
from fairshuffle.ui.shuffle import Action, Finished, Progress, ShuffleController


class Runs:
    """Stands in for the runner's shuffle and undo: answers each call with the next outcome."""

    def __init__(self) -> None:
        self.outcomes: list[Outcome] = []
        self.calls: list[tuple[str, str, Mode, int]] = []

    def answer(self, *outcomes: Outcome) -> None:
        self.outcomes.extend(outcomes)

    def shuffle(
        self, _client: Any, _cache: Any, playlist_id: str, mode: Mode, o: Options
    ) -> Outcome:
        return self._call("shuffle", playlist_id, mode, o)

    def undo(self, _client: Any, _cache: Any, playlist_id: str, mode: Mode, o: Options) -> Outcome:
        return self._call("undo", playlist_id, mode, o)

    def _call(self, what: str, playlist_id: str, mode: Mode, options: Options) -> Outcome:
        self.calls.append((what, playlist_id, mode, options.allowed_losses))
        return self.outcomes.pop(0) if self.outcomes else Outcome(Result.DONE, changed=True)


class Dialogs:
    """Stands in for picker.choose: records each question and gives the planned answers."""

    def __init__(self) -> None:
        self.answers: list[int] = []
        self.asked: list[tuple[str, str, list[str], int]] = []

    def __call__(
        self, _parent: QWidget, title: str, text: str, buttons: Sequence[str], default: int
    ) -> int:
        self.asked.append((title, text, list(buttons), default))
        return self.answers.pop(0)


@pytest.fixture
def account(qapp: QApplication) -> FakeAccount:
    return FakeAccount()


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> Runs:
    fake = Runs()
    monkeypatch.setattr("fairshuffle.ui.shuffle.shuffle_playlist", fake.shuffle)
    monkeypatch.setattr("fairshuffle.ui.shuffle.undo_last_shuffle", fake.undo)
    return fake


@pytest.fixture
def dialogs(monkeypatch: pytest.MonkeyPatch) -> Dialogs:
    fake = Dialogs()
    monkeypatch.setattr("fairshuffle.ui.picker.choose", fake)
    return fake


@pytest.fixture
def shuffles(account: FakeAccount, jobs: HeldJobs) -> ShuffleController:
    return ShuffleController(account, runner=jobs)  # type: ignore[arg-type]


@pytest.fixture
def picker(
    qtbot: QtBot,
    account: FakeAccount,
    jobs: HeldJobs,
    shuffles: ShuffleController,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[PlaylistPicker]:
    """A picker showing "Road Trip" and "Focus", with the first one selected."""
    monkeypatch.setattr("fairshuffle.ui.playlists.user_id", lambda _client: "fakeuser")
    shown = [playlist(1, "Road Trip", 60), playlist(2, "Focus", 30)]
    monkeypatch.setattr(
        "fairshuffle.ui.playlists.list_editable_playlists", lambda _client, _owner: shown
    )
    lists = PlaylistController(account, runner=jobs)  # type: ignore[arg-type]
    window = PlaylistPicker(account, lists, shuffles)  # type: ignore[arg-type]
    qtbot.addWidget(window)
    lists.refresh()
    jobs.release()
    yield window
    window.hide()


def back_up(playlist_id: str = "fakeplaylist1") -> None:
    backups.save(playlist_id, "fake-snapshot", [PlaylistItem(0, "spotify:track:a", "track", False)])


def test_the_box_and_buttons_are_laid_out_as_p4_4_says(picker: PlaylistPicker) -> None:
    assert picker.keep_date_added.text() == KEEP_DATE_ADDED
    assert not picker.keep_date_added.isChecked()  # fast mode by default (D12)
    assert picker.undo_button.text() == "&Undo"
    assert picker.shuffle_button.isEnabled()
    assert not picker.undo_button.isEnabled()  # no backup of this playlist yet
    assert picker.cancel_button.isHidden()
    layout = picker.layout()
    assert layout is not None
    box_at = layout.indexOf(picker.keep_date_added)
    assert box_at == layout.count() - 2  # straight above the row with the Shuffle button


def test_ticking_the_box_is_remembered(picker: PlaylistPicker, shuffles: ShuffleController) -> None:
    picker.keep_date_added.setChecked(True)

    assert shuffles.mode is Mode.KEEP_ORDER


def test_shuffle_runs_on_the_selected_playlist_and_shows_progress(
    picker: PlaylistPicker, jobs: HeldJobs, runs: Runs, shuffles: ShuffleController
) -> None:
    picker.shuffle_button.click()

    assert picker.status_label.text() == "Shuffling “Road Trip”…"
    assert not picker.shuffle_button.isEnabled()
    assert not picker.undo_button.isEnabled()
    assert not picker.refresh_button.isEnabled()
    assert not picker.keep_date_added.isEnabled()
    assert not picker.cancel_button.isHidden()

    shuffles._on_progress(12, 59)
    assert picker.status_label.text() == "Shuffling “Road Trip”… 12 of 59 steps"

    back_up()  # what the real runner does before its first write
    jobs.release()

    assert runs.calls == [("shuffle", "fakeplaylist1", Mode.FAST, 0)]
    assert picker.status_label.text() == (
        "Shuffled “Road Trip”. Play it from track 1 with shuffle off."
    )
    assert picker.shuffle_button.isEnabled()
    assert picker.undo_button.isEnabled()  # there is a backup now
    assert picker.cancel_button.isHidden()
    assert picker.refresh_button.isEnabled()


def test_typing_a_search_mid_run_keeps_the_progress_line(
    picker: PlaylistPicker, runs: Runs
) -> None:
    picker.shuffle_button.click()
    picker.search.setText("Road")

    assert picker.status_label.text() == "Shuffling “Road Trip”…"


def test_the_checked_box_shuffles_in_keep_order_mode(
    picker: PlaylistPicker, jobs: HeldJobs, runs: Runs
) -> None:
    picker.keep_date_added.setChecked(True)
    picker.shuffle_button.click()
    jobs.release()

    assert runs.calls == [("shuffle", "fakeplaylist1", Mode.KEEP_ORDER, 0)]


def test_cancel_reaches_the_run(
    picker: PlaylistPicker, jobs: HeldJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancelled: list[bool] = []

    def work(_client: Any, _cache: Any, _id: str, _mode: Mode, options: Options) -> Outcome:
        assert options.cancel is not None
        cancelled.append(options.cancel.is_set())
        return Outcome(Result.CANCELLED, message="Cancelled. Nothing was changed.")

    monkeypatch.setattr("fairshuffle.ui.shuffle.shuffle_playlist", work)
    picker.shuffle_button.click()
    picker.cancel_button.click()
    jobs.release()

    assert cancelled == [True]
    assert picker.status_label.text() == "Cancelled. Nothing was changed."


@pytest.mark.parametrize(
    ("answer", "rerun", "status"),
    [
        (0, ("shuffle", "fakeplaylist1", Mode.KEEP_ORDER, 0), None),
        (1, ("shuffle", "fakeplaylist1", Mode.FAST, 2), None),
        (2, None, "Cancelled. Nothing was changed."),
    ],
)
def test_fast_mode_asks_before_dropping_local_files(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    runs: Runs,
    dialogs: Dialogs,
    answer: int,
    rerun: tuple[str, str, Mode, int] | None,
    status: str | None,
) -> None:
    message = "Fast mode would remove 2 local files or songs Spotify no longer has."
    runs.answer(Outcome(Result.NEEDS_CONFIRM, message=message, losses=2))
    dialogs.answers.append(answer)
    picker.hide()  # the question brings the window back
    picker.shuffle_button.click()
    jobs.release()

    assert dialogs.asked == [
        (
            "Shuffle “Road Trip”?",
            f"{message} {NOT_PUT_BACK}",
            ["Use &keep-order mode", "Shuffle &fast anyway", "Cancel"],
            0,
        )
    ]
    assert picker.isVisible()
    if rerun is None:
        assert jobs.jobs == []
        assert picker.status_label.text() == status
    else:
        jobs.release()
        assert runs.calls[-1] == rerun
    assert not picker.keep_date_added.isChecked()  # the answer is for this run only


@pytest.mark.parametrize(("answer", "reruns"), [(0, True), (1, False)])
def test_a_fast_undo_asks_before_removing_songs_added_since(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    runs: Runs,
    dialogs: Dialogs,
    answer: int,
    reruns: bool,
) -> None:
    back_up()
    model = picker.list.model()
    picker.list.setCurrentIndex(model.index(1, 0))  # moving the selection refreshes the buttons
    picker.list.setCurrentIndex(model.index(0, 0))
    message = "Undo in fast mode would remove 3 songs that are in the playlist now."
    runs.answer(Outcome(Result.NEEDS_CONFIRM, message=message, losses=3))
    dialogs.answers.append(answer)
    picker.undo_button.click()
    jobs.release()

    assert dialogs.asked == [
        ("Undo the shuffle of “Road Trip”?", message, ["&Undo anyway", "Cancel"], 1)
    ]
    if reruns:
        jobs.release()
        assert runs.calls[-1] == ("undo", "fakeplaylist1", Mode.FAST, 3)
    else:
        assert jobs.jobs == []


@pytest.mark.parametrize(
    "result", [Result.FAILED, Result.NOT_VERIFIED, Result.CHANGED_ELSEWHERE, Result.CANCELLED]
)
def test_a_run_that_may_have_changed_the_playlist_offers_undo(
    picker: PlaylistPicker, jobs: HeldJobs, runs: Runs, dialogs: Dialogs, result: Result
) -> None:
    picker.keep_date_added.setChecked(True)
    runs.answer(Outcome(result, changed=True, message="It may be partly shuffled."))
    dialogs.answers.append(0)
    picker.shuffle_button.click()
    jobs.release()

    assert dialogs.asked == [
        ("The shuffle didn't finish", "It may be partly shuffled.", ["&Undo now", "&Leave it"], 0)
    ]
    jobs.release()
    assert runs.calls[-1] == ("undo", "fakeplaylist1", Mode.KEEP_ORDER, 0)


def test_undo_after_a_cut_off_fast_run_is_fast_whatever_the_box_says(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    runs: Runs,
    dialogs: Dialogs,
    shuffles: ShuffleController,
) -> None:
    runs.answer(Outcome(Result.FAILED, changed=True, message="Cut off."))
    dialogs.answers.append(0)
    picker.shuffle_button.click()
    picker.keep_date_added.setChecked(True)  # disabled mid-run, but even so
    jobs.release()
    jobs.release()

    assert runs.calls[-1] == ("undo", "fakeplaylist1", Mode.FAST, 0)


def test_leaving_it_keeps_the_message(
    picker: PlaylistPicker, jobs: HeldJobs, runs: Runs, dialogs: Dialogs
) -> None:
    runs.answer(Outcome(Result.FAILED, changed=True, message="It may be partly shuffled."))
    dialogs.answers.append(1)
    picker.shuffle_button.click()
    jobs.release()

    assert jobs.jobs == []
    assert picker.status_label.text() == "It may be partly shuffled."


def test_a_failure_before_any_write_only_says_why(
    picker: PlaylistPicker, jobs: HeldJobs, runs: Runs, dialogs: Dialogs
) -> None:
    runs.answer(Outcome(Result.FAILED, message="Spotify is busy. Nothing was changed."))
    picker.shuffle_button.click()
    jobs.release()

    assert dialogs.asked == []
    assert picker.status_label.text() == "Spotify is busy. Nothing was changed."


def test_no_dialog_once_signed_out(
    picker: PlaylistPicker, jobs: HeldJobs, runs: Runs, dialogs: Dialogs, account: FakeAccount
) -> None:
    runs.answer(Outcome(Result.FAILED, changed=True, message="FairShuffle is closing."))
    picker.shuffle_button.click()
    account.sign_out()
    jobs.release()

    assert dialogs.asked == []
    assert not picker.shuffle_button.isEnabled()


def test_undo_waits_for_a_backup_and_follows_the_selection(
    picker: PlaylistPicker, jobs: HeldJobs, runs: Runs
) -> None:
    back_up("fakeplaylist2")
    model = picker.list.model()

    picker.list.setCurrentIndex(model.index(1, 0))
    assert picker.undo_button.isEnabled()
    picker.list.setCurrentIndex(model.index(0, 0))
    assert not picker.undo_button.isEnabled()

    picker.list.setCurrentIndex(model.index(1, 0))
    picker.undo_button.click()
    jobs.release()
    assert runs.calls == [("undo", "fakeplaylist2", Mode.FAST, 0)]
    assert picker.status_label.text() == "Put back the order of “Focus” from before the shuffle."


def test_no_shuffle_while_a_search_matches_nothing(picker: PlaylistPicker) -> None:
    picker.search.setText("no such playlist")

    assert not picker.shuffle_button.isEnabled()


def test_long_names_are_cut_in_the_status_line() -> None:
    long = "x" * 100
    assert quoted(long) == "“" + "x" * 59 + "…”"
    progress = Progress(Action.UNDO, playlist(1, long), 0, 0)
    assert running_text(progress).startswith("Putting back “xxx")


def test_a_done_run_that_changed_nothing_says_so() -> None:
    outcome = Outcome(Result.DONE, message="The playlist was already in that order.")
    finished = Finished(Action.SHUFFLE, playlist(1), Mode.FAST, outcome)

    assert finished_text(finished) == "The playlist was already in that order."


def test_a_fast_undo_note_follows_the_done_line() -> None:
    note = "2 local files or songs Spotify no longer has couldn't be put back."
    outcome = Outcome(Result.DONE, changed=True, message=note)
    finished = Finished(Action.UNDO, playlist(1, "Mix"), Mode.FAST, outcome)

    assert finished_text(finished) == f"Put back the order of “Mix” from before the shuffle. {note}"
