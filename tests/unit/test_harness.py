"""Smoke tests for the test harness: headless Qt, fake Spotify settings, no real network."""

from __future__ import annotations

import os
import socket

import pytest
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from pytest_socket import SocketConnectBlockedError


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


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_no_test_can_reach_the_real_network() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("192.0.2.1", 443), timeout=1)  # TEST-NET-1, never routed


def test_no_test_reads_the_real_env_file() -> None:
    from fairshuffle import config

    path = config.dev_env_file()

    assert path is not None
    assert not path.exists()
