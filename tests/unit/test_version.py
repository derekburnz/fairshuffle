"""The version string is defined once in the package and matches the installed metadata."""

from importlib.metadata import version

import pytest

import fairshuffle
from fairshuffle.__main__ import main


def test_package_version_matches_installed_metadata() -> None:
    assert fairshuffle.__version__ == version("fairshuffle")


def test_version_flag_prints_version_and_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"FairShuffle {fairshuffle.__version__}"


def test_no_arguments_starts_the_app_and_returns_its_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fairshuffle.app.run", lambda: 7)

    assert main([]) == 7
