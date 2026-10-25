"""The build script around PyInstaller (D25): what it adds, refuses and zips.

PyInstaller itself is not run here (a minute or more, and the CI build job covers it, #34). The
tests point the script at a temp folder and stand in for PyInstaller with a fake build.
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_exe.py"


@pytest.fixture
def build_exe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("build_exe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DIST", tmp_path / "dist")
    yield module


def fake_build(module: ModuleType, extra: str | None = None) -> None:
    """What PyInstaller leaves: the app folder with the .exe and its _internal folder."""
    folder = module.DIST / module.NAME
    (folder / "_internal").mkdir(parents=True)
    exe = "FairShuffle.exe" if sys.platform == "win32" else "FairShuffle"
    (folder / exe).write_bytes(b"MZ fake exe")
    if extra is not None:
        (folder / extra).write_text("SPOTIFY_CLIENT_ID=fake-client-id-for-tests\n")


def test_the_folder_gets_the_license_and_env_example(build_exe: ModuleType) -> None:
    assert build_exe.main([], build=lambda: fake_build(build_exe)) == 0

    folder = build_exe.DIST / "FairShuffle"
    assert (folder / "LICENSE").read_text().startswith("MIT License")
    assert "your-client-id-here" in (folder / ".env.example").read_text()


def test_zip_unpacks_as_one_fairshuffle_folder(build_exe: ModuleType) -> None:
    assert build_exe.main(["--zip"], build=lambda: fake_build(build_exe)) == 0

    archive = build_exe.DIST / f"FairShuffle-{build_exe.version()}-windows-x64.zip"
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
    assert all(name.startswith("FairShuffle/") for name in names)
    assert "FairShuffle/LICENSE" in names
    assert not any(name.endswith("/.env") for name in names)


@pytest.mark.parametrize("where", [".env", "_internal/.env"])
def test_a_env_file_in_the_folder_stops_the_build(
    build_exe: ModuleType, where: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert build_exe.main(["--zip"], build=lambda: fake_build(build_exe, where)) == 1

    assert "must never ship" in capsys.readouterr().err
    assert not list(build_exe.DIST.glob("*.zip"))


def test_a_missing_exe_stops_the_build(
    build_exe: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert build_exe.main([], build=lambda: None) == 1

    assert "is missing" in capsys.readouterr().err


def test_a_failed_pyinstaller_run_stops_the_build(
    build_exe: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Failed:
        returncode = 1

    commands: list[list[str]] = []
    monkeypatch.setattr(
        build_exe.subprocess, "run", lambda command, **_: commands.append(command) or Failed()
    )

    assert build_exe.main([]) == 1
    assert commands[0][1:4] == ["-m", "PyInstaller", str(build_exe.SPEC)]
    assert "--noconfirm" in commands[0] and "--clean" in commands[0]
    assert "PyInstaller failed" in capsys.readouterr().err


def test_the_spec_builds_one_windowed_folder_without_upx() -> None:
    spec = (SCRIPT.parents[1] / "packaging" / "fairshuffle.spec").read_text()

    assert "console=False" in spec
    assert spec.count("upx=False") == 2  # on the EXE and on the COLLECT
    assert "COLLECT(" in spec  # one folder, not one file
