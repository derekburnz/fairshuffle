"""The About dialog shows the version, the license and the source link."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from fairshuffle import __version__
from fairshuffle.ui.about import REPO_URL, about_text, build_about_box


def test_about_text_names_version_license_and_source() -> None:
    text = about_text()

    assert f"FairShuffle {__version__}" in text
    assert "A true shuffle player for Spotify." in text  # the D27 tagline
    assert "MIT License" in text
    assert REPO_URL in text


def test_about_text_has_exactly_one_link_and_it_is_the_https_repo_url() -> None:
    assert re.findall(r'href="([^"]*)"', about_text()) == [REPO_URL]
    assert REPO_URL.startswith("https://")


def test_about_copyright_line_matches_the_license_file() -> None:
    license_text = (Path(__file__).parents[2] / "LICENSE").read_text(encoding="utf-8")
    lines = license_text.splitlines()
    copyright_line = next(line for line in lines if line.startswith("Copyright"))

    assert copyright_line in about_text()


def test_about_box_is_built_closed_and_cleans_up_after_itself(qtbot: QtBot) -> None:
    box = build_about_box()
    qtbot.addWidget(box)

    assert box.windowTitle() == "About FairShuffle"
    assert box.text() == about_text()
    assert box.standardButtons() == QMessageBox.StandardButton.Ok
    assert box.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    assert not box.isVisible()
