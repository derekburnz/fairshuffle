"""The playlist picker window (D11 B): search, the playlists you can edit, Refresh and Shuffle.

It opens from the tray and is about 380 by 520, like the D11 mockup in docs/screenshots/. Closing
it only hides it, so it opens again where it was with the search and selection kept.

Keyboard: the search box has focus when the window opens; typing filters the list, Down moves
into the list, the arrow keys move between playlists and Esc hides the window. Every row tells a
screen reader its name and item count, and a name too long for the row ends in an ellipsis with
the full name in a tooltip.

When there is nothing to list, the list's space says why instead: no playlists you can edit yet,
a load that failed, or a search with no match. A list of hundreds or thousands of playlists
fills in one go, and while a search narrows it the line underneath says how many it shows.
"""

from __future__ import annotations

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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from fairshuffle.spotify.models import Playlist
from fairshuffle.ui.account import AccountController, AccountState, AccountStatus
from fairshuffle.ui.playlists import PlaylistController, PlaylistsState, PlaylistsStatus

WINDOW_SIZE = QSize(380, 520)
ROW_HEIGHT = 40
UNTITLED = "Untitled playlist"
SHUFFLE_LATER = "Shuffling arrives in FairShuffle 0.4."
SIGNED_OUT = "Sign in to Spotify from the tray menu to see your playlists."
EMPTY = (
    "No playlists to shuffle yet. FairShuffle can only reorder playlists you own or collaborate "
    "on. Make one in Spotify, or join one as a collaborator, then press Refresh."
)
LOAD_FAILED = "Couldn't load your playlists. Press Refresh to try again."
KEPT_LIST = "The list shown is from before."
MAX_QUERY_SHOWN = 40  # a longer search is cut in the "no match" line so it still wraps

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
    query = query.strip()
    if len(query) > MAX_QUERY_SHOWN:
        query = query[: MAX_QUERY_SHOWN - 1].rstrip() + "…"
    return f"No playlists match \u201c{query}\u201d."


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._account = account
        self._playlists = playlists
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

        self.refresh_button = QPushButton("&Refresh")
        self.refresh_button.clicked.connect(playlists.refresh)
        self.shuffle_button = QPushButton("&Shuffle")
        self.shuffle_button.setEnabled(False)  # M4 builds the shuffle itself
        self.shuffle_button.setToolTip(SHUFFLE_LATER)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        buttons.addWidget(self.shuffle_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.account_label)
        layout.addWidget(self.heading)
        layout.addWidget(self.search)
        layout.addWidget(self.body, stretch=1)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

        account.status_changed.connect(self.show_account_status)
        playlists.status_changed.connect(self.show_playlists)
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

    def show_playlists(self, status: PlaylistsStatus) -> None:
        """Fill the list from status and say what is going on underneath it."""
        if status.playlists != self._shown_playlists:
            self._fill(status.playlists)
        self.refresh_button.setEnabled(status.state is not PlaylistsState.LOADING)
        total = len(status.playlists)
        matching = self.filtered.rowCount() if self.search.text() else None
        if status.state is PlaylistsState.LOADING:
            self.status_label.setText("Loading your playlists…")
        elif status.state is PlaylistsState.FAILED:
            message = status.message or "Couldn't load your playlists."
            self.status_label.setText(f"{message} {KEPT_LIST}" if total else message)
        elif status.state is PlaylistsState.READY:
            self.status_label.setText(list_summary(total, matching) if total else "")
        else:
            self.status_label.setText(SIGNED_OUT)
        self._show_placeholder(self._placeholder_text(status, total, matching))

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
