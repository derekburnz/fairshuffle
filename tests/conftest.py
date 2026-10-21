"""Shared setup for every FairShuffle test.

Qt runs headless, so tests never draw on screen and need no desktop session, and every test
sees fake Spotify settings, so no test can pick up a real Client ID from .env or the shell.
pytest-socket (pyproject.toml) refuses every connection except to this PC, and no test may use a
proxy, so no test can reach the real network.
Each test also gets its own single-instance key and its own logs folder, so tests never collide
with each other or with a FairShuffle copy the developer has running, and an in-memory password
store in place of Windows Credential Manager, so no test can read or overwrite a real sign-in.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import PasswordDeleteError
from PySide6.QtCore import qInstallMessageHandler

from fairshuffle.storage import logging_setup
from fairshuffle.storage.logging_setup import stop_logging

# Qt reads this when the first QApplication starts, so it must be set before any test runs.
# CI sets it too (ci.yml). setdefault keeps a developer's own choice, for example "windows"
# to watch a tray test on screen.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Until a test's in-memory store is in place, and in any child process a test starts, keyring
# uses its "fail" backend, which refuses every call. So nothing can reach the real Credential
# Manager, and keyring never runs its search for the machine's own backend.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
keyring.set_keyring(fail.Keyring())

FAKE_CLIENT_ID = "fake-client-id-for-tests"
FAKE_REDIRECT_URI = "http://127.0.0.1:8888/callback"


@pytest.fixture(autouse=True)
def fake_spotify_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test obvious fake Spotify settings in place of any real ones."""
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", FAKE_CLIENT_ID)
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", FAKE_REDIRECT_URI)


PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


@pytest.fixture(autouse=True)
def no_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop requests from using a proxy, so pytest-socket's loopback-only rule holds.

    pytest-socket allows 127.0.0.1, and a proxy on 127.0.0.1 (Fiddler, a company agent, a cloud
    sandbox) would carry a request out to the internet. requests finds proxies in these variables
    and, on Windows, in the system settings, so both are switched off.
    """
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr("requests.utils.getproxies", dict)


@pytest.fixture(autouse=True)
def no_dev_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the settings loader at a .env that doesn't exist, so no test reads the real one."""
    monkeypatch.setattr("fairshuffle.config.dev_env_file", lambda: tmp_path / "no-such.env")


@pytest.fixture(autouse=True)
def instance_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Give every test a single-instance key of its own in place of the real per-user one."""
    key = f"FairShuffleTest-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr("fairshuffle.app.default_instance_key", lambda: key)
    return key


@pytest.fixture(autouse=True)
def isolated_logging(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Point the logs folder at a temp folder, then undo any logging setup the test did."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("LocalAppData")))
    root = logging.getLogger()
    level = root.level
    yield
    stop_logging()
    logging_setup._masked_values.clear()
    qInstallMessageHandler(None)  # app.start_logging sends Qt's messages to Python logging
    root.setLevel(level)


class MemoryKeyring(KeyringBackend):
    """A password store that lives only as long as one test."""

    priority = 1  # type: ignore[assignment]  # keyring's class property; any value works here

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.passwords.pop((service, username), None) is None:
            raise PasswordDeleteError("not found")


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    """Give the test an in-memory password store, then go back to the one that refuses."""
    fake = MemoryKeyring()
    keyring.set_keyring(fake)
    yield fake
    keyring.set_keyring(fail.Keyring())
