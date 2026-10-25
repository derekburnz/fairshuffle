"""Reads FairShuffle's Spotify settings: the Client ID and the Redirect URI.

In development they come from the environment first, then from the gitignored .env file at the
top of the project folder (P2-3), so a value set in the shell always wins over the file. That
also lets tests give every run fake values without ever reading a developer's real .env. The
prototype .exe reads a .env the user puts next to FairShuffle.exe instead (P5-4); the build never
ships one. How the public release gets a Client ID is decided later (D17).

The Client ID is registered with mask_secret() as soon as it is read, so it can't reach a log.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from fairshuffle.auth.loopback import InvalidRedirectUri, RedirectTarget
from fairshuffle.storage.logging_setup import mask_secret

CLIENT_ID_VARIABLE = "SPOTIFY_CLIENT_ID"
REDIRECT_URI_VARIABLE = "SPOTIFY_REDIRECT_URI"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
PLACEHOLDER_CLIENT_ID = "your-client-id-here"  # the value in .env.example
SETUP_GUIDE = "docs/spotify-setup.md"


class ConfigError(Exception):
    """A Spotify setting is missing or unusable. The message says how to fix it."""


@dataclass(frozen=True, slots=True)
class SpotifySettings:
    client_id: str = field(repr=False)
    redirect_uri: str
    redirect: RedirectTarget


def dev_env_file() -> Path | None:
    """The .env to read: next to FairShuffle.exe in a PyInstaller build (P5-4), in the project
    folder when running from a source checkout, else None."""
    if _built():
        return Path(sys.executable).resolve().parent / ".env"
    project = Path(__file__).resolve().parents[2]  # src/fairshuffle/config.py -> project folder
    if not (project / "pyproject.toml").is_file():
        return None
    return project / ".env"


def _built() -> bool:
    """True in the PyInstaller build, which sets sys.frozen."""
    return bool(getattr(sys, "frozen", False))


def load_settings(env_file: Path | None = None) -> SpotifySettings:
    """Read the settings from the environment, falling back to env_file (default: dev .env)."""
    path = env_file if env_file is not None else dev_env_file()
    file_values = dotenv_values(path) if path is not None and path.is_file() else {}

    def read(name: str) -> str:
        return (os.environ.get(name) or file_values.get(name) or "").strip()

    client_id = read(CLIENT_ID_VARIABLE)
    if not client_id or client_id == PLACEHOLDER_CLIENT_ID:
        where = "a .env file next to FairShuffle.exe" if _built() else ".env"
        raise ConfigError(
            f"{CLIENT_ID_VARIABLE} is not set. Register your Spotify app and put its Client ID "
            f"in {where}, as {SETUP_GUIDE} in FairShuffle's GitHub repository describes."
        )
    mask_secret(client_id)

    redirect_uri = read(REDIRECT_URI_VARIABLE) or DEFAULT_REDIRECT_URI
    try:
        redirect = RedirectTarget.parse(redirect_uri)
    except InvalidRedirectUri as error:
        raise ConfigError(f"{REDIRECT_URI_VARIABLE} can't be used: {error}") from None
    return SpotifySettings(client_id=client_id, redirect_uri=redirect_uri, redirect=redirect)
