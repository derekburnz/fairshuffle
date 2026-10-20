"""FairShuffle's icon in the notification area and its menu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from fairshuffle.ui.about import build_about_box

TOOLTIP = "FairShuffle"


def placeholder_icon() -> QIcon:
    """Draw the placeholder icon: three white bars of uneven length on a blue tile.

    It is drawn in code so there is no image file to package yet. Issue P7-01 replaces it with
    the real icon in light and dark variants.
    """
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0067c0"))  # the default Windows 11 accent blue
    painter.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    painter.setBrush(QColor("white"))
    for top, width in ((14, 36), (28, 22), (42, 30)):
        painter.drawRoundedRect(QRectF(14, top, width, 8), 4, 4)
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    """The icon in the hidden icons flyout behind the ^ arrow on the Windows 11 taskbar.

    Right-click opens the menu. A left-click opens it too, and so does Enter when the icon has
    keyboard focus (Win+B moves the focus to the notification area). Inside the menu the arrow
    keys move and the underlined letters pick an item.
    """

    def __init__(self, quit_app: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(placeholder_icon(), parent)
        self._quit_app = quit_app
        self._about_box: QMessageBox | None = None
        self.setToolTip(TOOLTIP)

        # A QSystemTrayIcon is not a widget, so the menu has no Qt parent. This attribute keeps
        # it alive for as long as the icon exists.
        self.menu = QMenu()
        self.about_action = QAction("&About FairShuffle", self.menu)
        self.about_action.triggered.connect(self.show_about)
        self.quit_action = QAction("&Quit", self.menu)
        self.quit_action.triggered.connect(self.quit)
        self.menu.addAction(self.about_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.setContextMenu(self.menu)

        self.activated.connect(self._on_activated)

    @property
    def about_box(self) -> QMessageBox | None:
        """The About box while it is open, otherwise None."""
        return self._about_box

    def show_about(self) -> None:
        if self._about_box is not None:
            # Already open: bring it forward instead of stacking a second copy.
            self._about_box.raise_()
            self._about_box.activateWindow()
            return
        self._about_box = build_about_box()
        self._about_box.finished.connect(self._forget_about_box)
        self._about_box.open()

    def quit(self) -> None:
        """Take the icon out of the notification area, then end the app with exit code 0."""
        self.hide()
        self._quit_app()

    def _forget_about_box(self) -> None:
        self._about_box = None

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Right-click (Context) already shows the menu through setContextMenu.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            icon_area = self.geometry()
            self.menu.popup(icon_area.center() if icon_area.isValid() else QCursor.pos())
