"""Starting the app: Qt settings, logging, the tray icon and the exit code when the user quits."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QMessageLogContext, QTimer, QtMsgType, qWarning
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from fairshuffle import __version__, app
from fairshuffle.storage.logging_setup import HOME_MASK
from fairshuffle.ui.account import AccountController
from fairshuffle.ui.playlists import PlaylistController
from fairshuffle.ui.tray import TrayIcon


def read_log() -> str:
    """The log file the test wrote, under the temp LOCALAPPDATA that conftest set."""
    for handler in logging.getLogger().handlers:
        handler.flush()
    log_file = Path(os.environ["LOCALAPPDATA"]) / "FairShuffle" / "logs" / "fairshuffle.log"
    return log_file.read_text(encoding="utf-8")


def tray_that_quits_once_running(
    quit_app: Callable[[], None],
    account: AccountController | None = None,
    playlists: PlaylistController | None = None,
) -> TrayIcon:
    tray = TrayIcon(quit_app=quit_app, account=account, playlists=playlists)
    # Picks Quit from the menu as soon as the event loop is running.
    QTimer.singleShot(0, tray.quit_action.trigger)
    return tray


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

    accounts: list[AccountController | None] = []
    lists: list[PlaylistController | None] = []

    def record_tray(
        quit_app: Callable[[], None],
        account: AccountController | None = None,
        playlists: PlaylistController | None = None,
    ) -> TrayIcon:
        accounts.append(account)
        lists.append(playlists)
        created.append(tray_that_quits_once_running(quit_app, account, playlists))
        return created[-1]

    monkeypatch.setattr(app, "TrayIcon", record_tray)

    assert app.run() == 0
    assert len(created) == 1
    assert not created[0].isVisible()
    assert isinstance(accounts[0], AccountController)  # the menu has the account items
    assert isinstance(lists[0], PlaylistController)  # and the playlist picker


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


def test_run_steps_aside_when_fairshuffle_is_already_running(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, instance_key: str
) -> None:
    first_copy = app.SingleInstance(key=instance_key)
    assert first_copy.acquire()

    def no_second_icon(**_: object) -> TrayIcon:
        raise AssertionError("a second launch must not create a tray icon")

    monkeypatch.setattr(app, "TrayIcon", no_second_icon)
    try:
        assert app.run() == 0
    finally:
        first_copy.release()


def test_a_later_launch_makes_the_running_copy_point_at_its_icon(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, instance_key: str
) -> None:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    titles: list[str] = []

    def tray_that_records_messages(quit_app: Callable[[], None], **_: object) -> TrayIcon:
        tray = TrayIcon(quit_app=quit_app)  # no account: its notices would race this one

        def record_then_quit(title: str, *_: object) -> None:
            titles.append(title)
            tray.quit_action.trigger()

        monkeypatch.setattr(tray, "showMessage", record_then_quit)
        # Launches FairShuffle again once the first copy's event loop is running.
        QTimer.singleShot(0, lambda: app.SingleInstance(key=instance_key).acquire())
        return tray

    monkeypatch.setattr(app, "TrayIcon", tray_that_records_messages)

    assert app.run() == 0
    assert titles == ["FairShuffle is already running"]


def test_run_logs_the_start_and_the_quit(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(app, "TrayIcon", tray_that_quits_once_running)

    assert app.run() == 0

    text = read_log()
    assert f"INFO fairshuffle.app: FairShuffle {__version__} starting" in text
    assert "INFO fairshuffle.app: FairShuffle quit with exit code 0" in text


def test_qt_messages_reach_the_log_with_the_home_folder_masked(qapp: QApplication) -> None:
    app.start_logging()

    qWarning(f"QLockFile: could not open {Path.home() / 'Temp' / 'x.lock'}")

    text = read_log()
    assert "WARNING fairshuffle.qt: QLockFile: could not open " in text
    assert str(Path.home()) not in text
    assert HOME_MASK in text


@pytest.mark.parametrize(
    ("mode", "level"),
    [
        (QtMsgType.QtDebugMsg, logging.DEBUG),
        (QtMsgType.QtInfoMsg, logging.INFO),
        (QtMsgType.QtWarningMsg, logging.WARNING),
        (QtMsgType.QtCriticalMsg, logging.ERROR),
        (QtMsgType.QtFatalMsg, logging.CRITICAL),
    ],
)
def test_qt_message_levels_map_to_logging_levels(
    mode: QtMsgType, level: int, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="fairshuffle.qt"):
        app._log_qt_message(mode, QMessageLogContext(), "100% done")

    assert [(r.name, r.levelno, r.getMessage()) for r in caplog.records] == [
        ("fairshuffle.qt", level, "100% done")
    ]


def test_a_logging_problem_never_stops_the_app(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def logs_folder_locked(**_: object) -> None:
        raise PermissionError(13, "Permission denied", "C:/Users/fake-user/AppData/Local")

    monkeypatch.setattr(app, "setup_logging", logs_folder_locked)

    app.start_logging()

    assert caplog.messages == ["Logging to a file is off: Permission denied"]
