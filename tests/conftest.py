"""Shared setup for every FairShuffle test.

Qt runs headless, so tests never draw on screen and need no desktop session, and every test
sees fake Spotify settings, so no test can pick up a real Client ID from .env or the shell.
Each test also gets its own single-instance key, so tests never collide with each other or with
a FairShuffle copy the developer has running.
"""

from __future__ import annotations

import os
import uuid

import pytest

# Qt reads this when the first QApplication starts, so it must be set before any test runs.
# CI sets it too (ci.yml). setdefault keeps a developer's own choice, for example "windows"
# to watch a tray test on screen.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAKE_CLIENT_ID = "fake-client-id-for-tests"
FAKE_REDIRECT_URI = "http://127.0.0.1:8888/callback"


@pytest.fixture(autouse=True)
def fake_spotify_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test obvious fake Spotify settings in place of any real ones."""
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", FAKE_CLIENT_ID)
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", FAKE_REDIRECT_URI)


@pytest.fixture(autouse=True)
def instance_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Give every test a single-instance key of its own in place of the real per-user one."""
    key = f"FairShuffleTest-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr("fairshuffle.app.default_instance_key", lambda: key)
    return key
