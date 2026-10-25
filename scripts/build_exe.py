"""Builds the FairShuffle folder with FairShuffle.exe in it (D25: PyInstaller, one folder).

    uv run --group build python scripts/build_exe.py         # makes dist/FairShuffle/
    uv run --group build python scripts/build_exe.py --zip   # and dist/FairShuffle-<version>-...zip

PyInstaller follows packaging/fairshuffle.spec. It bundles Python, Qt and FairShuffle's code,
so the folder runs on a PC without Python. It builds for the system it runs on, so run it on
Windows; CI does the same for the pre-release (#34).

The folder also gets the license and .env.example. Never your .env: the Client ID stays on your
PC, and the build refuses to finish if a .env ended up in the folder anyway. The .exe is not
code signed yet (D16), so Smart App Control or SmartScreen may block it on a PC that has them on.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "fairshuffle.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
NAME = "FairShuffle"
EXTRAS = ("LICENSE", ".env.example")  # copied next to the .exe
FORBIDDEN = (".env",)  # must never ship: it holds the developer's Client ID


class BuildError(Exception):
    """The build didn't produce a usable folder. The message says why."""


def version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from fairshuffle import __version__

    return __version__


def zip_name(app_version: str) -> str:
    return f"{NAME}-{app_version}-windows-x64"


def run_pyinstaller() -> None:
    """Run PyInstaller in its own process, as its docs recommend, so nothing leaks between runs."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC),
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
    ]
    if subprocess.run(command, cwd=ROOT, check=False).returncode != 0:  # noqa: S603  # fixed args
        raise BuildError("PyInstaller failed; its output above says why.")


def finish_folder(folder: Path) -> None:
    """Add the extras, then check the folder has the app and nothing it must not have."""
    exe = folder / (f"{NAME}.exe" if sys.platform == "win32" else NAME)
    if not exe.is_file():
        raise BuildError(f"PyInstaller finished but {exe.name} is missing.")
    for extra in EXTRAS:
        shutil.copy2(ROOT / extra, folder / extra)
    found = [path.name for path in folder.rglob("*") if path.name in FORBIDDEN]
    if found:
        raise BuildError("A .env file is in the build folder. Remove it; it must never ship.")


def make_zip(folder: Path, app_version: str) -> Path:
    """Zip the folder so it unpacks as one FairShuffle folder."""
    archive = shutil.make_archive(
        str(folder.parent / zip_name(app_version)), "zip", folder.parent, folder.name
    )
    return Path(archive)


def main(argv: Sequence[str] | None = None, build: Callable[[], None] = run_pyinstaller) -> int:
    parser = argparse.ArgumentParser(description="Build the FairShuffle folder with PyInstaller.")
    parser.add_argument("--zip", action="store_true", help="also zip the folder for a release")
    args = parser.parse_args(argv)
    app_version = version()
    folder = DIST / NAME
    try:
        build()
        finish_folder(folder)
        archive = make_zip(folder, app_version) if args.zip else None
    except BuildError as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    # Paths relative to the project folder, so the output never shows the Windows user name.
    print(f"Built FairShuffle {app_version} in {DIST.name}/{NAME}")
    if archive is not None:
        print(f"Zipped it as {DIST.name}/{archive.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
