"""The tray icon: tooltip, menu, About, Quit and opening the menu without a right-click."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from pytestqt.qtbot import QtBot

from fairshuffle.ui.tray import TOOLTIP, TrayIcon, placeholder_icon


class QuitRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


@pytest.fixture
def quit_app() -> QuitRecorder:
    return QuitRecorder()


@pytest.fixture
def tray(qapp: QApplication, quit_app: QuitRecorder) -> Iterator[TrayIcon]:
    icon = TrayIcon(quit_app=quit_app)
    yield icon
    icon.hide()
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QMessageBox):
            widget.close()


def test_placeholder_icon_is_drawn(qapp: QApplication) -> None:
    icon = placeholder_icon()

    assert not icon.isNull()
    assert not icon.pixmap(16, 16).isNull()


def test_tooltip_reads_fairshuffle(tray: TrayIcon) -> None:
    assert tray.toolTip() == TOOLTIP == "FairShuffle"
    assert not tray.icon().isNull()


def test_menu_has_about_then_quit_with_keyboard_shortcuts(tray: TrayIcon) -> None:
    labels = [action.text() for action in tray.menu.actions() if not action.isSeparator()]

    assert tray.contextMenu() is tray.menu
    # The & marks the underlined letter that picks the item from the keyboard.
    assert labels == ["&About FairShuffle", "&Quit"]


def test_quit_removes_the_icon_then_ends_the_app(tray: TrayIcon, quit_app: QuitRecorder) -> None:
    tray.show()
    assert tray.isVisible()

    tray.quit_action.trigger()

    assert not tray.isVisible()
    assert quit_app.calls == 1


def test_about_opens_one_box_at_a_time(tray: TrayIcon) -> None:
    tray.about_action.trigger()
    tray.about_action.trigger()

    boxes = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox)]
    visible = [box for box in boxes if box.isVisible()]
    assert len(visible) == 1
    assert visible[0].windowTitle() == "About FairShuffle"


def test_about_can_open_again_after_it_is_closed(tray: TrayIcon, qtbot: QtBot) -> None:
    tray.show_about()
    first = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox))
    first.accept()
    qtbot.waitUntil(lambda: tray.about_box is None)

    tray.show_about()

    assert tray.about_box is not None
    assert tray.about_box is not first
    assert tray.about_box.isVisible()


@pytest.mark.parametrize(
    ("reason", "opens_menu"),
    [
        (QSystemTrayIcon.ActivationReason.Trigger, True),
        (QSystemTrayIcon.ActivationReason.Context, False),
        (QSystemTrayIcon.ActivationReason.DoubleClick, False),
    ],
)
def test_left_click_or_enter_opens_the_menu(
    tray: TrayIcon,
    monkeypatch: pytest.MonkeyPatch,
    reason: QSystemTrayIcon.ActivationReason,
    opens_menu: bool,
) -> None:
    popups: list[QPoint] = []
    monkeypatch.setattr(tray.menu, "popup", lambda pos, *_: popups.append(pos))

    tray.activated.emit(reason)

    assert bool(popups) is opens_menu


def test_already_running_message_points_at_the_icon(
    tray: TrayIcon, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(tray, "showMessage", lambda title, text, *_: shown.append((title, text)))

    tray.show_already_running()

    assert shown == [
        (
            "FairShuffle is already running",
            "It lives here in the notification area. Right-click the icon for the menu.",
        )
    ]
