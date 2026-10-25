"""The About dialog: version, license and where the source lives."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from fairshuffle import __version__

REPO_URL = "https://github.com/derekburnz/fairshuffle"


def about_text() -> str:
    """The box's rich text. Its one link is the fixed repo URL; nothing else is clickable."""
    return (
        f"<b>FairShuffle {html.escape(__version__)}</b>"
        "<p>A true shuffle player for Spotify.</p>"
        "<p>A true Fisher-Yates shuffle for your Spotify playlists.</p>"
        "<p>Copyright (c) 2026 Derek Burns<br>Released under the MIT License.</p>"
        f'<p><a href="{REPO_URL}">{REPO_URL}</a></p>'
    )


def build_about_box(parent: QWidget | None = None) -> QMessageBox:
    """Build the About box without showing it, so tests can inspect it before it opens."""
    box = QMessageBox(parent)
    box.setWindowTitle("About FairShuffle")
    box.setIcon(QMessageBox.Icon.Information)
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(about_text())
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    return box
