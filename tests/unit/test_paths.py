"""Where FairShuffle's files go on Windows."""

from __future__ import annotations

from pathlib import Path

import pytest

from fairshuffle.storage import paths


def test_logs_go_under_local_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert paths.log_dir() == tmp_path / "FairShuffle" / "logs"


def test_without_local_app_data_the_usual_folder_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert paths.local_data_dir() == tmp_path / "AppData" / "Local" / "FairShuffle"
