"""Builds the Qt application, puts the tray icon in place and runs until the user quits."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from fairshuffle import __version__
from fairshuffle.ui.tray import TrayIcon

APP_NAME = "FairShuffle"


def create_application() -> QApplication:
    """Return the QApplication, creating it on first use (tests share one that pytest-qt made)."""
    existing = QApplication.instance()
    # Qt's own command-line options are not used, so Qt only gets the program name.
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    # A tray app has no main window, so closing the About box must not end the app.
    app.setQuitOnLastWindowClosed(False)
    return app


def run() -> int:
    """Start FairShuffle and return its exit code once the user picks Quit."""
    app = create_application()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            APP_NAME,
            "FairShuffle needs the Windows notification area, which is not available.",
        )
        return 1
    tray = TrayIcon(quit_app=app.quit)
    tray.show()
    return app.exec()
