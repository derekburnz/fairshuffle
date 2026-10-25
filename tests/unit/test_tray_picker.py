"""Opening the playlist picker from the tray (D11 B), and the notice when a shuffle finishes."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fakes.ui_fakes import FakeAccount, HeldJobs, playlist
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from fairshuffle.shuffle.runner import Mode, Outcome, Result
from fairshuffle.ui.playlists import PlaylistController
from fairshuffle.ui.shuffle import Action, Finished, ShuffleController
from fairshuffle.ui.tray import NOT_FINISHED, PLAY_TIP, UNDONE, TrayIcon


@pytest.fixture
def account(qapp: QApplication) -> FakeAccount:
    return FakeAccount(signed_in=False)


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def tray(account: FakeAccount, jobs: HeldJobs) -> Iterator[TrayIcon]:
    lists = PlaylistController(account, runner=jobs)  # type: ignore[arg-type]
    shuffles = ShuffleController(account, runner=HeldJobs())  # type: ignore[arg-type]
    icon = TrayIcon(
        quit_app=lambda: None,
        account=account,  # type: ignore[arg-type]
        playlists=lists,
        shuffles=shuffles,
    )
    yield icon
    if icon.picker is not None:
        icon.picker.close()
    icon.hide()


@pytest.fixture
def menu_opened(tray: TrayIcon, monkeypatch: pytest.MonkeyPatch) -> list[QPoint]:
    opened: list[QPoint] = []
    monkeypatch.setattr(tray.menu, "popup", lambda point: opened.append(point))
    return opened


def visible_labels(tray: TrayIcon) -> list[str]:
    return [action.text() for action in tray.menu.actions() if action.isVisible()]


def test_the_picker_item_shows_only_while_signed_in(tray: TrayIcon, account: FakeAccount) -> None:
    assert "Shuffle a &playlist…" not in visible_labels(tray)

    account.sign_in()
    assert visible_labels(tray)[:4] == [
        "Signed in as Fake User",
        "Sign &out",
        "",
        "Shuffle a &playlist…",
    ]

    account.sign_out()
    assert "Shuffle a &playlist…" not in visible_labels(tray)


def test_the_item_opens_the_picker_and_loads_the_list(
    tray: TrayIcon, account: FakeAccount, jobs: HeldJobs
) -> None:
    account.sign_in()
    tray.picker_action.trigger()

    assert tray.picker is not None
    assert tray.picker.isVisible()
    assert len(jobs.jobs) == 1


def test_opening_it_again_reuses_the_same_window(tray: TrayIcon, account: FakeAccount) -> None:
    account.sign_in()
    tray.show_picker()
    first = tray.picker
    assert first is not None
    first.hide()
    tray.show_picker()

    assert tray.picker is first
    assert first.isVisible()


def test_a_left_click_opens_the_picker_while_signed_in(
    tray: TrayIcon, account: FakeAccount, menu_opened: list[QPoint]
) -> None:
    account.sign_in()
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    assert tray.picker is not None and tray.picker.isVisible()
    assert menu_opened == []


def test_a_left_click_opens_the_menu_while_signed_out(
    tray: TrayIcon, menu_opened: list[QPoint]
) -> None:
    tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    assert tray.picker is None
    assert len(menu_opened) == 1


def test_signing_out_hides_an_open_picker(tray: TrayIcon, account: FakeAccount) -> None:
    account.sign_in()
    tray.show_picker()
    account.sign_out()

    assert tray.picker is not None
    assert not tray.picker.isVisible()


def test_a_tray_without_playlists_never_offers_the_picker(account: FakeAccount) -> None:
    icon = TrayIcon(quit_app=lambda: None, account=account)  # type: ignore[arg-type]
    account.sign_in()

    assert "Shuffle a &playlist…" not in visible_labels(icon)
    icon.hide()


# The completion notice (#32) ----------------------------------------------------------------


@pytest.fixture
def toasts(tray: TrayIcon, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(tray, "showMessage", lambda title, text, *_: shown.append((title, text)))
    return shown


def finish(tray: TrayIcon, action: Action, outcome: Outcome) -> None:
    tray.show_finished(Finished(action, playlist(1, "Road Trip"), Mode.FAST, outcome))


def test_a_finished_shuffle_tells_how_to_play_it(
    tray: TrayIcon, toasts: list[tuple[str, str]]
) -> None:
    finish(tray, Action.SHUFFLE, Outcome(Result.DONE, changed=True))

    assert toasts == [("Shuffled \u201cRoad Trip\u201d", PLAY_TIP)]
    assert "track 1" in PLAY_TIP and "shuffle off" in PLAY_TIP and "Custom order" in PLAY_TIP


def test_a_finished_undo_says_the_order_is_back(
    tray: TrayIcon, toasts: list[tuple[str, str]]
) -> None:
    note = "2 local files or songs Spotify no longer has couldn't be put back."
    finish(tray, Action.UNDO, Outcome(Result.DONE, changed=True, message=note))

    assert toasts == [("Put back \u201cRoad Trip\u201d", f"{UNDONE} {note}")]


@pytest.mark.parametrize(
    "outcome",
    [
        Outcome(Result.DONE, message="The playlist was already in that order."),
        Outcome(Result.FAILED, message="Spotify is busy. Nothing was changed."),
        Outcome(Result.NEEDS_CONFIRM, losses=2),
        Outcome(Result.CANCELLED),
    ],
)
def test_anything_else_is_left_to_the_picker(
    tray: TrayIcon, toasts: list[tuple[str, str]], outcome: Outcome
) -> None:
    finish(tray, Action.SHUFFLE, outcome)

    assert toasts == []


def test_the_notice_follows_the_controllers_finished_signal(
    tray: TrayIcon, toasts: list[tuple[str, str]], account: FakeAccount
) -> None:
    assert tray._shuffles is not None
    outcome = Outcome(Result.DONE, changed=True)
    tray._shuffles.finished.emit(Finished(Action.SHUFFLE, playlist(2, "Focus"), Mode.FAST, outcome))

    assert toasts == [("Shuffled \u201cFocus\u201d", PLAY_TIP)]


@pytest.mark.parametrize(("action", "what"), [(Action.SHUFFLE, "shuffle"), (Action.UNDO, "Undo")])
@pytest.mark.parametrize("result", [Result.FAILED, Result.NOT_VERIFIED, Result.CANCELLED])
def test_a_run_that_stopped_after_writing_points_at_undo(
    tray: TrayIcon, toasts: list[tuple[str, str]], action: Action, what: str, result: Result
) -> None:
    # The picker may be hidden (signed out mid-run), so the tray says it too.
    finish(tray, action, Outcome(result, changed=True, message="Cut off."))

    assert toasts == [(f"The {what} of \u201cRoad Trip\u201d didn't finish", NOT_FINISHED)]


def test_a_long_name_is_cut_in_the_notice(tray: TrayIcon, toasts: list[tuple[str, str]]) -> None:
    long = Finished(
        Action.SHUFFLE, playlist(1, "y" * 100), Mode.FAST, Outcome(Result.DONE, changed=True)
    )
    tray.show_finished(long)

    assert toasts[0][0] == "Shuffled \u201c" + "y" * 59 + "\u2026\u201d"
