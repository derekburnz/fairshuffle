"""Smoke tests for the test harness: headless Qt works and the Spotify settings are fakes."""

from __future__ import annotations

import os

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSystemTrayIcon


def test_tray_icon_can_be_created_headless(qapp: QApplication) -> None:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("teal"))
    tray = QSystemTrayIcon(QIcon(pixmap), qapp)
    tray.setToolTip("FairShuffle")

    tray.show()

    assert tray.isVisible()
    assert tray.toolTip() == "FairShuffle"
    assert not tray.icon().isNull()
    tray.hide()


def test_qt_uses_the_platform_from_the_environment(qapp: QApplication) -> None:
    assert qapp.platformName() == os.environ["QT_QPA_PLATFORM"]


def test_spotify_settings_are_fakes() -> None:
    assert os.environ["SPOTIFY_CLIENT_ID"] == "fake-client-id-for-tests"
    assert os.environ["SPOTIFY_REDIRECT_URI"] == "http://127.0.0.1:8888/callback"
