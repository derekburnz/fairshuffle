"""The user's FairShuffle settings, kept between runs in %APPDATA%\\FairShuffle\\settings.json.

It holds whether shuffles keep each song's "date added" (keep-order mode, P4-4) and the ID of
the private playlist the true shuffle player plays from (M6). A missing or damaged file gives
the defaults, and a file that can't be saved only means the choice is forgotten at the next
start, so neither ever stops the app.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fairshuffle.storage.paths import settings_file

MAX_FILE_BYTES = 100_000  # a few bytes in practice; anything bigger isn't ours
_ID = re.compile(r"[0-9A-Za-z]{1,64}")  # a Spotify playlist ID

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    keep_date_added: bool = False  # fast mode is the default (D12)
    true_shuffle_playlist: str | None = None  # made by the player on first use (P6-04)


def load() -> Settings:
    """The saved settings, or the defaults when there are none or they can't be read."""
    path = settings_file()
    try:
        if not path.is_file():
            return Settings()
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("too big")
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except OSError, ValueError, RecursionError:  # RecursionError: deeply nested JSON
        # The OS message can quote the path, which holds the Windows user name.
        log.warning("The settings file couldn't be read; using the defaults")
        return Settings()
    keep = data.get("keep_date_added", False)
    playlist = data.get("true_shuffle_playlist")
    return Settings(
        keep_date_added=keep if isinstance(keep, bool) else False,
        true_shuffle_playlist=playlist
        if isinstance(playlist, str) and _ID.fullmatch(playlist)
        else None,
    )


def update(**changes: Any) -> Settings:
    """Change some settings and keep the rest as saved, so the shuffle controller and the player
    never write over each other's choices. Returns the new settings, saved or not."""
    new = replace(load(), **changes)
    save(new)
    return new


def save(settings: Settings) -> bool:
    """Save the settings. Returns False (and logs) when they couldn't be written."""
    path = settings_file()
    data = {
        "keep_date_added": settings.keep_date_added,
        "true_shuffle_playlist": settings.true_shuffle_playlist,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(path, json.dumps(data))
    except OSError:
        log.warning("Saving the settings failed")
        return False
    return True


def _write_atomically(path: Path, text: str) -> None:
    """Write a temp file next to path, then swap it in, so a crash never leaves half a file."""
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    os.close(handle)
    try:
        with open(temp_name, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
