"""The playlist picker window (D11 B): search, the playlists you can edit, Shuffle and Undo.

It opens from the tray and is about 380 by 520, like the D11 mockup in docs/screenshots/. Closing
it only hides it, so it opens again where it was with the search and selection kept.

Keyboard: the search box has focus when the window opens; typing filters the list, Down moves
into the list, the arrow keys move between playlists and Esc hides the window. Every row tells a
screen reader its name and item count, and a name too long for the row ends in an ellipsis with
the full name in a tooltip.

When there is nothing to list, the list's space says why instead: no playlists you can edit yet,
a load that failed, or a search with no match. A list of hundreds or thousands of playlists
fills in one go, and while a search narrows it the line underneath says how many it shows.

Shuffle and Undo run through the ShuffleController. While one runs, the line underneath shows
its progress and Cancel appears. When a run needs the user's say (fast mode would drop local
files, P4-2, or a fast Undo would remove songs added since) or may have left the playlist
changed, a dialog asks; otherwise the line underneath says how it went. The "Keep date added
(slower)" box above the buttons picks keep-order mode and is remembered (P4-4).
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    QSortFilterProxyModel,
)
from PySide6.QtGui import QFont, QKeyEvent, QPainter, QStandardItem, QStandardItemModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from fairshuffle.shuffle.runner import Mode, Result
from fairshuffle.spotify.models import Playlist
from fairshuffle.ui.account import AccountController, AccountState, AccountStatus
from fairshuffle.ui.playlists import PlaylistController, PlaylistsState, PlaylistsStatus
from fairshuffle.ui.shuffle import Action, Finished, Progress, ShuffleController

WINDOW_SIZE = QSize(380, 520)
ROW_HEIGHT = 40
UNTITLED = "Untitled playlist"
KEEP_DATE_ADDED = "&Keep date added (slower)"
KEEP_DATE_ADDED_TIP = (
    "Moves the songs one at a time, so each keeps its date added and local files stay. "
    "About 20 seconds for 60 songs. Unticked, FairShuffle rewrites the list in a few seconds."
)
UNDO_TIP = "Put back the order from before this playlist's last shuffle."
CANCEL_TIP = (
    "Stop the shuffle. Keep-order mode stops between moves; fast mode can only stop before it "
    "starts writing."
)
NOT_PUT_BACK = "FairShuffle can't add them back, and neither can Undo."
SIGNED_OUT = "Sign in to Spotify from the tray menu to see your playlists."
EMPTY = (
    "No playlists to shuffle yet. FairShuffle can only reorder playlists you own or collaborate "
    "on. Make one in Spotify, or join one as a collaborator, then press Refresh."
)
LOAD_FAILED = "Couldn't load your playlists. Press Refresh to try again."
KEPT_LIST = "The list shown is from before."
MAX_QUERY_SHOWN = 40  # a longer search is cut in the "no match" line so it still wraps
MAX_NAME_SHOWN = 60  # a longer playlist name is cut in the status line and dialogs

COUNT_ROLE = Qt.ItemDataRole.UserRole + 1  # the "148 items" text shown on the right of a row
ID_ROLE = Qt.ItemDataRole.UserRole + 2  # the playlist's Spotify ID


def count_text(count: int | None) -> str:
    """ "1 item", "1,204 items", or "" when Spotify didn't give a count."""
    if count is None:
        return ""
    return f"{count:,} item" + ("" if count == 1 else "s")


def list_summary(count: int, matching: int | None = None) -> str:
    """ "1,204 playlists you can edit", or "Showing 12 of 1,204 playlists" while searching."""
    if matching is not None:
        return f"Showing {matching:,} of {count:,} playlist" + ("" if count == 1 else "s")
    if count == 1:
        return "1 playlist you can edit"
    return f"{count:,} playlists you can edit"


def no_match(query: str) -> str:
    return f"No playlists match {quoted(query, MAX_QUERY_SHOWN)}."


def quoted(text: str, limit: int = MAX_NAME_SHOWN) -> str:
    """text in curly quotes, cut with an ellipsis past limit characters."""
    text = text.strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return f"\u201c{text}\u201d"


def running_text(progress: Progress) -> str:
    """ "Shuffling “Road trip”… 12 of 59 steps", for the line under the list."""
    name = quoted(progress.playlist.name or UNTITLED)
    verb = "Shuffling" if progress.action is Action.SHUFFLE else "Putting back"
    if progress.total:
        return f"{verb} {name}\u2026 {progress.done:,} of {progress.total:,} steps"
    return f"{verb} {name}\u2026"


def finished_text(finished: Finished) -> str:
    """How a run ended, for the line under the list."""
    outcome = finished.outcome
    name = quoted(finished.playlist.name or UNTITLED)
    if outcome.result is Result.DONE and outcome.changed:
        if finished.action is Action.SHUFFLE:
            done = f"Shuffled {name}. Play it from track 1 with shuffle off."
        else:
            done = f"Put back the order of {name} from before the shuffle."
        return f"{done} {outcome.message}".strip()
    return outcome.message


def choose(parent: QWidget, title: str, text: str, buttons: Sequence[str], default: int) -> int:
    """Ask with a dialog and return the index of the button pressed. The last button is the
    one Esc and the close button press, so it must be the safe choice."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, QMessageBox.StandardButton.NoButton)
    box.setParent(parent, box.windowFlags())
    box.setTextFormat(Qt.TextFormat.PlainText)  # the text quotes a playlist name
    pressed = [box.addButton(label, QMessageBox.ButtonRole.ActionRole) for label in buttons]
    box.setDefaultButton(pressed[default])
    box.setEscapeButton(pressed[-1])
    box.exec()
    clicked = box.clickedButton()
    box.deleteLater()
    return pressed.index(clicked) if clicked in pressed else len(buttons) - 1  # type: ignore[arg-type]


class PlaylistRowDelegate(QStyledItemDelegate):
    """Draws a row as the name on the left, cut with an ellipsis if needed, and the count on the
    right, at a fixed height so long lists scroll smoothly."""

    MARGIN = 12

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        self.initStyleOption(option, index)
        name = option.text
        option.text = ""  # the style draws the background, selection and focus; we draw text
        style = option.widget.style() if option.widget is not None else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        count = str(index.data(COUNT_ROLE) or "")
        rect = option.rect.adjusted(self.MARGIN, 0, -self.MARGIN, 0)
        metrics = option.fontMetrics
        count_width = metrics.horizontalAdvance(count) + (self.MARGIN if count else 0)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        roles = option.palette.ColorRole
        role = roles.HighlightedText if selected else roles.Text
        painter.save()
        painter.setPen(option.palette.color(role))
        name_rect = rect.adjusted(0, 0, -count_width, 0)
        elided = metrics.elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width())
        align = Qt.AlignmentFlag.AlignVCenter
        painter.drawText(name_rect, align | Qt.AlignmentFlag.AlignLeft, elided)
        painter.drawText(rect, align | Qt.AlignmentFlag.AlignRight, count)
        painter.restore()


class PlaylistPicker(QWidget):
    """The window that lists the playlists FairShuffle can reorder."""

    def __init__(
        self,
        account: AccountController,
        playlists: PlaylistController,
        shuffles: ShuffleController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._account = account
        self._playlists = playlists
        self._shuffles = shuffles
        self._shown_playlists: tuple[Playlist, ...] = ()
        self.setWindowTitle("FairShuffle")
        self.resize(WINDOW_SIZE)
        self.setMinimumSize(320, 360)

        # Labels would show text that looks like HTML as HTML; these only ever show plain text.
        self.account_label = QLabel()
        self.account_label.setTextFormat(Qt.TextFormat.PlainText)
        self.heading = QLabel("Pick a playlist to shuffle")
        heading_font = QFont(self.heading.font())
        heading_font.setPointSizeF(heading_font.pointSizeF() * 1.5)
        heading_font.setWeight(QFont.Weight.DemiBold)
        self.heading.setFont(heading_font)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search playlists")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search playlists")
        self.search.installEventFilter(self)

        self.model = QStandardItemModel(self)
        self.filtered = QSortFilterProxyModel(self)
        self.filtered.setSourceModel(self.model)
        self.filtered.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search.textChanged.connect(self.filtered.setFilterFixedString)
        self.search.textChanged.connect(lambda _text: self.show_playlists(playlists.status))

        self.list = QListView()
        self.list.setModel(self.filtered)
        self.list.setItemDelegate(PlaylistRowDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setAccessibleName("Playlists you can edit")
        self.list.selectionModel().currentChanged.connect(lambda *_: self._update_buttons())

        # Shown in the list's place when there is nothing to list, saying why.
        self.placeholder = QLabel()
        self.placeholder.setTextFormat(Qt.TextFormat.PlainText)
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setContentsMargins(16, 16, 16, 16)
        self.body = QStackedWidget()
        self.body.addWidget(self.list)
        self.body.addWidget(self.placeholder)

        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)

        self.keep_date_added = QCheckBox(KEEP_DATE_ADDED)
        self.keep_date_added.setToolTip(KEEP_DATE_ADDED_TIP)
        self.keep_date_added.setChecked(shuffles.keep_date_added)
        self.keep_date_added.toggled.connect(shuffles.set_keep_date_added)

        self.refresh_button = QPushButton("&Refresh")
        self.refresh_button.clicked.connect(playlists.refresh)
        self.undo_button = QPushButton("&Undo")
        self.undo_button.setToolTip(UNDO_TIP)
        self.undo_button.clicked.connect(self.undo)
        self.cancel_button = QPushButton("&Cancel")
        self.cancel_button.setToolTip(CANCEL_TIP)
        self.cancel_button.clicked.connect(shuffles.cancel)
        self.cancel_button.setVisible(False)
        self.shuffle_button = QPushButton("&Shuffle")
        self.shuffle_button.clicked.connect(self.shuffle)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        buttons.addWidget(self.undo_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.shuffle_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.account_label)
        layout.addWidget(self.heading)
        layout.addWidget(self.search)
        layout.addWidget(self.body, stretch=1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.keep_date_added)
        layout.addLayout(buttons)

        account.status_changed.connect(self.show_account_status)
        playlists.status_changed.connect(self.show_playlists)
        shuffles.running_changed.connect(self.show_running)
        shuffles.finished.connect(self.show_finished)
        self.show_account_status(account.status)
        self.show_playlists(playlists.status)

    def open(self) -> None:
        """Show the window in front, with focus in the search box, and load the list if needed."""
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
        self._playlists.load_if_needed()

    def show_account_status(self, status: AccountStatus) -> None:
        if status.state is AccountState.SIGNED_IN and status.name:
            self.account_label.setText(f"Signed in as {status.name}")
        elif status.state is AccountState.SIGNED_IN:
            self.account_label.setText("Signed in to Spotify")
        else:
            self.account_label.setText("Not signed in to Spotify")
        self._update_buttons()

    def selected_playlist(self) -> Playlist | None:
        playlist_id = self.selected_playlist_id()
        if playlist_id is None or self.body.currentWidget() is not self.list:
            return None
        return next((p for p in self._shown_playlists if p.id == playlist_id), None)

    def shuffle(self) -> None:
        playlist = self.selected_playlist()
        if playlist is not None:
            self._shuffles.shuffle(playlist)

    def undo(self) -> None:
        playlist = self.selected_playlist()
        if playlist is not None:
            self._shuffles.undo(playlist)

    def show_running(self, progress: Progress | None) -> None:
        if progress is not None:
            self.status_label.setText(running_text(progress))
        self._update_buttons()

    def show_finished(self, finished: Finished) -> None:
        """Say how a run ended, asking first when the user has a choice to make."""
        outcome = finished.outcome
        self.status_label.setText(finished_text(finished))
        self._update_buttons()
        if self._account.status.state is not AccountState.SIGNED_IN:
            return  # signed out mid-run: nothing more can be done for this account here
        if outcome.result is Result.NEEDS_CONFIRM:
            self._bring_forward()
            if finished.action is Action.SHUFFLE:
                self._ask_fast_losses(finished)
            else:
                self._ask_undo_losses(finished)
        elif outcome.changed and outcome.result is not Result.DONE:
            self._bring_forward()
            self._offer_undo(finished)

    def _ask_fast_losses(self, finished: Finished) -> None:
        """P4-2: fast mode would drop local files or songs Spotify no longer has."""
        playlist, losses = finished.playlist, finished.outcome.losses
        answer = choose(
            self,
            f"Shuffle {quoted(playlist.name or UNTITLED)}?",
            f"{finished.outcome.message} {NOT_PUT_BACK}",
            ["Use &keep-order mode", "Shuffle &fast anyway", "Cancel"],
            default=0,
        )
        if answer == 0:
            self._shuffles.shuffle(playlist, Mode.KEEP_ORDER)
        elif answer == 1:
            self._shuffles.shuffle(playlist, Mode.FAST, allowed_losses=losses)
        else:
            self.status_label.setText("Cancelled. Nothing was changed.")

    def _ask_undo_losses(self, finished: Finished) -> None:
        playlist, losses = finished.playlist, finished.outcome.losses
        answer = choose(
            self,
            f"Undo the shuffle of {quoted(playlist.name or UNTITLED)}?",
            finished.outcome.message,
            ["&Undo anyway", "Cancel"],
            default=1,
        )
        if answer == 0:
            self._shuffles.undo(playlist, Mode.FAST, allowed_losses=losses)
        else:
            self.status_label.setText("Cancelled. Nothing was changed.")

    def _offer_undo(self, finished: Finished) -> None:
        """The run stopped after something may have been written: offer the backup."""
        what = "shuffle" if finished.action is Action.SHUFFLE else "Undo"
        answer = choose(
            self,
            f"The {what} didn't finish",
            finished.outcome.message,
            ["&Undo now", "&Leave it"],
            default=0,
        )
        if answer == 0:
            # Undo in the mode that was running: after a fast run cut off between its replace
            # and its adds, the playlist is short, and only a fast Undo can fill it back in.
            self._shuffles.undo(finished.playlist, finished.mode)

    def _bring_forward(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _update_buttons(self) -> None:
        running = self._shuffles.running is not None
        signed_in = self._account.status.state is AccountState.SIGNED_IN
        playlist = self.selected_playlist() if signed_in else None
        ready = playlist is not None and not running
        self.shuffle_button.setEnabled(ready)
        self.undo_button.setEnabled(ready and self._shuffles.has_backup(playlist.id))  # type: ignore[union-attr]
        self.cancel_button.setVisible(running)
        self.keep_date_added.setEnabled(not running)
        loading = self._playlists.status.state is PlaylistsState.LOADING
        self.refresh_button.setEnabled(not loading and not running)

    def show_playlists(self, status: PlaylistsStatus) -> None:
        """Fill the list from status and say what is going on underneath it."""
        if status.playlists != self._shown_playlists:
            self._fill(status.playlists)
        total = len(status.playlists)
        matching = self.filtered.rowCount() if self.search.text() else None
        running = self._shuffles.running
        if running is not None:
            self.status_label.setText(running_text(running))  # the run's progress comes first
        elif status.state is PlaylistsState.LOADING:
            self.status_label.setText("Loading your playlists…")
        elif status.state is PlaylistsState.FAILED:
            message = status.message or "Couldn't load your playlists."
            self.status_label.setText(f"{message} {KEPT_LIST}" if total else message)
        elif status.state is PlaylistsState.READY:
            self.status_label.setText(list_summary(total, matching) if total else "")
        else:
            self.status_label.setText(SIGNED_OUT)
        self._show_placeholder(self._placeholder_text(status, total, matching))
        self._update_buttons()

    def _placeholder_text(self, status: PlaylistsStatus, total: int, matching: int | None) -> str:
        """Why the list is empty, or "" when it has rows (or is still loading its first rows)."""
        if total and matching == 0:
            return no_match(self.search.text())
        if total:
            return ""
        if status.state is PlaylistsState.FAILED:
            return LOAD_FAILED
        if status.state is PlaylistsState.READY:
            return EMPTY
        return ""

    def _show_placeholder(self, text: str) -> None:
        self.placeholder.setText(text)
        self.body.setCurrentWidget(self.placeholder if text else self.list)

    def _fill(self, playlists: tuple[Playlist, ...]) -> None:
        selected = self.selected_playlist_id()
        self.model.clear()
        rows: list[QStandardItem] = []
        for playlist in playlists:
            name = playlist.name or UNTITLED
            count = count_text(playlist.item_count)
            row = QStandardItem(name)
            row.setData(count, COUNT_ROLE)
            row.setData(playlist.id, ID_ROLE)
            # Qt shows a tooltip that looks like HTML as HTML, and a collaborator can name a
            # playlist "<img src=...>", so the tooltip is always our own HTML with the name escaped.
            tooltip = f"{name}\n{count}" if count else name
            row.setToolTip(Qt.convertFromPlainText(tooltip, Qt.WhiteSpaceMode.WhiteSpaceNormal))
            row.setData(f"{name}, {count}" if count else name, Qt.ItemDataRole.AccessibleTextRole)
            rows.append(row)
        if rows:
            self.model.invisibleRootItem().appendRows(rows)  # one update for thousands of rows
        self._shown_playlists = playlists
        self._select(selected)

    def selected_playlist_id(self) -> str | None:
        index = self.list.currentIndex()
        value = index.data(ID_ROLE) if index.isValid() else None
        return value if isinstance(value, str) else None

    def _select(self, playlist_id: str | None) -> None:
        """Select playlist_id again after a refresh, or the first row if it is gone."""
        model: QAbstractItemModel = self.filtered
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if index.data(ID_ROLE) == playlist_id:
                self.list.setCurrentIndex(index)
                return
        if model.rowCount() > 0:
            self.list.setCurrentIndex(model.index(0, 0))

    def eventFilter(self, watched: object, event: object) -> bool:
        """Down in the search box moves into the list, as in Windows' own search boxes."""
        if (
            watched is self.search
            and isinstance(event, QKeyEvent)
            and event.type() == QKeyEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Down
            and self.filtered.rowCount() > 0
        ):
            self.list.setFocus()
            if not self.list.currentIndex().isValid():
                self.list.setCurrentIndex(self.filtered.index(0, 0))
            return True
        return super().eventFilter(watched, event)  # type: ignore[arg-type]

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
