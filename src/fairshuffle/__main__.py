"""Entry point for `python -m fairshuffle` and the `fairshuffle` launcher from pyproject.toml."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from fairshuffle import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fairshuffle",
        description="A Windows tray app that gives a Spotify playlist a true Fisher-Yates shuffle.",
    )
    parser.add_argument("--version", action="version", version=f"FairShuffle {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    # Imported here so that --version answers without loading Qt.
    from fairshuffle.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
