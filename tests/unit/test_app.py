"""Starting the app: Qt settings, the tray icon and the exit code when the user quits."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from fairshuffle import __version__, app
from fairshuffle.ui.tray import TrayIcon


def test_create_application_reuses_qt_and_keeps_running_without_windows(
    qapp: QApplication,
) -> None:
    application = app.create_application()

    assert application is qapp
    assert application.applicationName() == "FairShuffle"
    assert application.applicationVersion() == __version__
    assert application.quitOnLastWindowClosed() is False


def test_run_shows_the_tray_icon_and_exits_with_code_zero_on_quit(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    created: list[TrayIcon] = []

    def tray_that_quits_once_running(quit_app: Callable[[], None]) -> TrayIcon:
        tray = TrayIcon(quit_app=quit_app)
        created.append(tray)
        # Picks Quit from the menu as soon as the event loop is running.
        QTimer.singleShot(0, tray.quit_action.trigger)
        return tray

    monkeypatch.setattr(app, "TrayIcon", tray_that_quits_once_running)

    assert app.run() == 0
    assert len(created) == 1
    assert not created[0].isVisible()


def test_run_explains_and_exits_with_code_one_without_a_notification_area(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda _parent, _title, text: messages.append(text))
    )

    assert app.run() == 1
    assert messages == ["FairShuffle needs the Windows notification area, which is not available."]
