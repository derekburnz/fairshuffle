"""FairShuffle's icon in the notification area and its menu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from fairshuffle.ui.about import build_about_box
from fairshuffle.ui.account import AccountController, AccountState, AccountStatus
from fairshuffle.ui.picker import PlaylistPicker
from fairshuffle.ui.playlists import PlaylistController

TOOLTIP = "FairShuffle"

# For each account state: the greyed-out line at the top of the menu, then the account action's
# label and what it does (None hides the action).
_STATUS_LINES = {
    AccountState.CHECKING: "Checking your Spotify sign-in\u2026",
    AccountState.SIGNED_OUT: "Not signed in to Spotify",
    AccountState.SIGNING_IN: "Waiting for you to sign in in your browser\u2026",
    AccountState.SIGNED_IN: "Signed in to Spotify",
    AccountState.SIGN_IN_AGAIN: "Your Spotify sign-in has expired",
    AccountState.SETUP_NEEDED: "Spotify app not set up yet (see docs/spotify-setup.md)",
    AccountState.UNAVAILABLE: "Couldn't check your Spotify sign-in",
}
_ACTION_LABELS = {
    AccountState.CHECKING: None,
    AccountState.SIGNED_OUT: "&Sign in to Spotify\u2026",
    AccountState.SIGNING_IN: "&Cancel sign-in",
    AccountState.SIGNED_IN: "Sign &out",
    AccountState.SIGN_IN_AGAIN: "&Sign in again\u2026",
    AccountState.SETUP_NEEDED: "&Sign in to Spotify\u2026",
    AccountState.UNAVAILABLE: "&Try again",
}


def _menu_text(text: str) -> str:
    """Show text as it is in a menu: Qt would read a single & as a keyboard shortcut marker."""
    return text.replace("&", "&&")


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

    Right-click opens the menu. A left-click opens the playlist picker while signed in (D11) and
    the menu otherwise, and Enter does the same when the icon has keyboard focus (Win+B moves the
    focus to the notification area). Inside the menu the arrow keys move and the underlined
    letters pick an item.
    """

    def __init__(
        self,
        quit_app: Callable[[], None],
        account: AccountController | None = None,
        playlists: PlaylistController | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(placeholder_icon(), parent)
        self._quit_app = quit_app
        self._account = account
        self._playlists = playlists
        self._about_box: QMessageBox | None = None
        self._picker: PlaylistPicker | None = None
        self.setToolTip(TOOLTIP)

        # A QSystemTrayIcon is not a widget, so the menu has no Qt parent. This attribute keeps
        # it alive for as long as the icon exists.
        self.menu = QMenu()
        self.status_action = QAction(self.menu)
        self.status_action.setEnabled(False)  # a label, not something to click
        self.account_action = QAction(self.menu)
        self.account_action.triggered.connect(self._on_account_action)
        # The ellipsis is the Windows sign that the item opens a window rather than acting.
        self.picker_action = QAction("Shuffle a &playlist\u2026", self.menu)
        self.picker_action.triggered.connect(self.show_picker)
        self.picker_action.setVisible(False)
        if account is not None:
            self.menu.addAction(self.status_action)
            self.menu.addAction(self.account_action)
            self.menu.addSeparator()
            if playlists is not None:
                self.menu.addAction(self.picker_action)
                self.menu.addSeparator()
            account.status_changed.connect(self.show_account_status)
            self.show_account_status(account.status)
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

    @property
    def picker(self) -> PlaylistPicker | None:
        """The playlist picker once it has been opened, otherwise None."""
        return self._picker

    def show_picker(self) -> None:
        """Open the playlist picker, or bring it forward if it is open already."""
        if self._account is None or self._playlists is None:  # pragma: no cover  # no such item
            return
        if self._picker is None:
            self._picker = PlaylistPicker(self._account, self._playlists)
        self._picker.open()

    def show_account_status(self, status: AccountStatus) -> None:
        """Bring the account lines of the menu up to date, and pass on any message once."""
        signed_in = status.state is AccountState.SIGNED_IN
        self.picker_action.setVisible(signed_in and self._playlists is not None)
        if not signed_in and self._picker is not None:
            self._picker.hide()
        line = _STATUS_LINES[status.state]
        if status.state is AccountState.SIGNED_IN and status.name:
            line = f"Signed in as {status.name}"
        self.status_action.setText(_menu_text(line))
        label = _ACTION_LABELS[status.state]
        self.account_action.setVisible(label is not None)
        self.account_action.setText(label or "")
        self.setToolTip(f"{TOOLTIP}\n{line}")
        if status.message:
            self.showMessage(TOOLTIP, status.message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def show_already_running(self) -> None:
        """Answer a second launch by pointing at this icon instead of adding another one."""
        self.showMessage(
            "FairShuffle is already running",
            "It lives here in the notification area. Right-click the icon for the menu.",
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def quit(self) -> None:
        """Take the icon out of the notification area, then end the app with exit code 0."""
        self.hide()
        self._quit_app()

    def _on_account_action(self) -> None:
        account = self._account
        if account is None:  # pragma: no cover  # the action is only in the menu with an account
            return
        state = account.status.state
        if state is AccountState.SIGNING_IN:
            account.cancel_sign_in()
        elif state is AccountState.SIGNED_IN:
            account.sign_out()
        elif state is AccountState.UNAVAILABLE:
            account.start()
        else:
            account.sign_in()

    def _forget_about_box(self) -> None:
        self._about_box = None

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Right-click (Context) already shows the menu through setContextMenu.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.picker_action.isVisible():
                self.show_picker()
                return
            icon_area = self.geometry()
            self.menu.popup(icon_area.center() if icon_area.isValid() else QCursor.pos())
