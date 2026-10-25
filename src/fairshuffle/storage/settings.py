"""The user's FairShuffle settings, kept between runs in %APPDATA%\\FairShuffle\\settings.json.

For now it holds one choice: whether shuffles keep each song's "date added" (keep-order mode,
P4-4). A missing or damaged file gives the defaults, and a file that can't be saved only means
the choice is forgotten at the next start, so neither ever stops the app.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fairshuffle.storage.paths import settings_file

MAX_FILE_BYTES = 100_000  # a few bytes in practice; anything bigger isn't ours

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    keep_date_added: bool = False  # fast mode is the default (D12)


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
    except OSError, ValueError:
        # The OS message can quote the path, which holds the Windows user name.
        log.warning("The settings file couldn't be read; using the defaults")
        return Settings()
    keep = data.get("keep_date_added", False)
    return Settings(keep_date_added=keep if isinstance(keep, bool) else False)


def save(settings: Settings) -> bool:
    """Save the settings. Returns False (and logs) when they couldn't be written."""
    path = settings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(path, json.dumps({"keep_date_added": settings.keep_date_added}))
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
