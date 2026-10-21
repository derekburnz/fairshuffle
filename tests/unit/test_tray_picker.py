"""Opening the playlist picker from the tray (D11 B)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from ui_fakes import FakeAccount, HeldJobs

from fairshuffle.ui.playlists import PlaylistController
from fairshuffle.ui.tray import TrayIcon


@pytest.fixture
def account(qapp: QApplication) -> FakeAccount:
    return FakeAccount(signed_in=False)


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def tray(account: FakeAccount, jobs: HeldJobs) -> Iterator[TrayIcon]:
    lists = PlaylistController(account, runner=jobs)  # type: ignore[arg-type]
    icon = TrayIcon(quit_app=lambda: None, account=account, playlists=lists)  # type: ignore[arg-type]
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
