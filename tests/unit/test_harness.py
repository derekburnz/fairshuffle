"""Smoke tests for the test harness: headless Qt, fake Spotify settings, no real network."""

from __future__ import annotations

import os
import socket

import pytest
import requests
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from pytest_socket import SocketBlockedError, SocketConnectBlockedError


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


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_a_proxy_on_this_pc_cannot_carry_a_request_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A loopback proxy is allowed by pytest-socket, so requests must never use one in tests."""
    with socket.create_server(("127.0.0.1", 0)) as proxy:
        proxy.setblocking(False)
        port = proxy.getsockname()[1]
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("https_proxy", f"http://127.0.0.1:{port}")

        with pytest.raises(SocketConnectBlockedError):
            requests.get("https://192.0.2.1/", timeout=1)  # TEST-NET-1, never routed

        with pytest.raises(BlockingIOError):
            proxy.accept()  # nobody connected to the proxy


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_no_test_can_look_up_a_real_host_name() -> None:
    with pytest.raises(SocketBlockedError):
        socket.getaddrinfo("api.spotify.com", 443)


def test_this_pc_can_still_be_looked_up() -> None:
    assert socket.getaddrinfo("127.0.0.1", 80)


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_a_stray_real_request_fails_loudly() -> None:
    """requests doesn't catch the block, so a call nobody faked can't pass as a network error."""
    with pytest.raises(SocketBlockedError):
        requests.get("https://api.spotify.com/v1/me", timeout=1)
