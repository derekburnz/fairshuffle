"""Where FairShuffle keeps its files on Windows.

Roaming data (settings, backups) goes in %APPDATA%\\FairShuffle and follows the user between PCs
on a company network. Local data (logs) goes in %LOCALAPPDATA%\\FairShuffle and stays on this PC.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_FOLDER = "FairShuffle"


def local_data_dir() -> Path:
    """%LOCALAPPDATA%\\FairShuffle, or the usual place under the home folder if it is unset."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_FOLDER


def log_dir() -> Path:
    return local_data_dir() / "logs"
