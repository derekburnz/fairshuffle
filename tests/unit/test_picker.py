"""The playlist picker window (D11 B): what it lists, search, keyboard and status lines."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetrics, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
from pytestqt.qtbot import QtBot
from ui_fakes import FakeAccount, HeldJobs, playlist

from fairshuffle.spotify.errors import SpotifyUnavailable
from fairshuffle.ui.picker import (
    COUNT_ROLE,
    ROW_HEIGHT,
    SHUFFLE_LATER,
    SIGNED_OUT,
    UNTITLED,
    PlaylistPicker,
    PlaylistRowDelegate,
    count_text,
    list_summary,
)
from fairshuffle.ui.playlists import PlaylistController


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def account(qapp: QApplication) -> FakeAccount:
    return FakeAccount()


@pytest.fixture
def lists(
    account: FakeAccount, jobs: HeldJobs, monkeypatch: pytest.MonkeyPatch
) -> PlaylistController:
    monkeypatch.setattr("fairshuffle.ui.playlists.user_id", lambda _client: "fakeuser")
    return PlaylistController(account, runner=jobs)  # type: ignore[arg-type]


@pytest.fixture
def picker(
    qtbot: QtBot, account: FakeAccount, lists: PlaylistController
) -> Iterator[PlaylistPicker]:
    window = PlaylistPicker(account, lists)  # type: ignore[arg-type]
    qtbot.addWidget(window)
    yield window
    window.hide()


def load(
    jobs: HeldJobs,
    monkeypatch: pytest.MonkeyPatch,
    lists: PlaylistController,
    playlists: list[object],
) -> None:
    monkeypatch.setattr(
        "fairshuffle.ui.playlists.list_editable_playlists", lambda _client, _owner: playlists
    )
    lists.refresh()
    jobs.release()


def shown_names(picker: PlaylistPicker) -> list[str]:
    model = picker.list.model()
    return [str(model.index(row, 0).data()) for row in range(model.rowCount())]


@pytest.mark.parametrize(
    ("count", "text"), [(None, ""), (0, "0 items"), (1, "1 item"), (1204, "1,204 items")]
)
def test_item_counts_read_naturally(count: int | None, text: str) -> None:
    assert count_text(count) == text


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (0, "0 playlists you can edit"),
        (1, "1 playlist you can edit"),
        (12, "12 playlists you can edit"),
    ],
)
def test_the_summary_line_reads_naturally(count: int, text: str) -> None:
    assert list_summary(count) == text


def test_the_window_matches_the_d11_mockup(picker: PlaylistPicker) -> None:
    assert picker.windowTitle() == "FairShuffle"
    assert (picker.width(), picker.height()) == (380, 520)
    assert picker.account_label.text() == "Signed in as Fake User"
    assert picker.heading.text() == "Pick a playlist to shuffle"
    assert picker.search.placeholderText() == "Search playlists"
    assert picker.refresh_button.text() == "&Refresh"
    assert picker.shuffle_button.text() == "&Shuffle"


def test_shuffle_waits_for_the_next_version(picker: PlaylistPicker) -> None:
    assert not picker.shuffle_button.isEnabled()
    assert picker.shuffle_button.toolTip() == SHUFFLE_LATER


def test_opening_loads_the_list_and_focuses_search(
    picker: PlaylistPicker, jobs: HeldJobs, qtbot: QtBot
) -> None:
    picker.open()

    assert picker.isVisible()
    assert len(jobs.jobs) == 1
    assert picker.status_label.text() == "Loading your playlists…"
    assert not picker.refresh_button.isEnabled()
    qtbot.waitUntil(lambda: picker.search.hasFocus())


def test_the_list_shows_names_counts_and_a_summary(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1, "Morning Run", 64), playlist(2, "", None)])

    assert shown_names(picker) == ["Morning Run", UNTITLED]
    first = picker.list.model().index(0, 0)
    assert first.data(COUNT_ROLE) == "64 items"
    assert first.data(Qt.ItemDataRole.ToolTipRole) == "Morning Run\n64 items"
    assert first.data(Qt.ItemDataRole.AccessibleTextRole) == "Morning Run, 64 items"
    second = picker.list.model().index(1, 0)
    assert second.data(Qt.ItemDataRole.AccessibleTextRole) == UNTITLED
    assert picker.status_label.text() == "2 playlists you can edit"
    assert picker.refresh_button.isEnabled()
    assert picker.selected_playlist_id() == "fakeplaylist1"  # the first row starts selected


def test_names_are_shown_as_text_not_markup(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1, "<b>Bold & Co</b>")])

    assert shown_names(picker) == ["<b>Bold & Co</b>"]


def test_search_filters_without_caring_about_case(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load(
        jobs,
        monkeypatch,
        lists,
        [playlist(1, "Morning Run"), playlist(2, "Focus Beats"), playlist(3, "Late Night Run")],
    )

    picker.search.setText("run")
    assert shown_names(picker) == ["Morning Run", "Late Night Run"]
    picker.search.setText("[")  # typed text is matched as text, not as a pattern
    assert shown_names(picker) == []
    picker.search.clear()
    assert len(shown_names(picker)) == 3


def test_down_from_search_moves_into_the_list(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1), playlist(2)])
    picker.open()
    jobs.jobs.clear()
    qtbot.waitUntil(lambda: picker.search.hasFocus())

    qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    assert picker.list.hasFocus()
    qtbot.keyClick(picker.list, Qt.Key.Key_Down)
    assert picker.selected_playlist_id() == "fakeplaylist2"


def test_down_with_nothing_listed_stays_in_search(picker: PlaylistPicker, qtbot: QtBot) -> None:
    picker.open()
    qtbot.waitUntil(lambda: picker.search.hasFocus())

    qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    assert picker.search.hasFocus()


def test_down_selects_the_first_match_when_nothing_is_selected(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1, "Morning Run"), playlist(2, "Focus Beats")])
    picker.search.setText("focus")  # filters the selected row away
    picker.list.setCurrentIndex(picker.list.model().index(-1, -1))
    picker.open()
    jobs.jobs.clear()
    qtbot.waitUntil(lambda: picker.search.hasFocus())

    qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    assert picker.selected_playlist_id() == "fakeplaylist2"


def test_escape_hides_the_window(picker: PlaylistPicker, qtbot: QtBot) -> None:
    picker.open()
    qtbot.keyClick(picker, Qt.Key.Key_Escape)

    assert not picker.isVisible()


def test_other_keys_reach_the_window_as_usual(picker: PlaylistPicker, qtbot: QtBot) -> None:
    picker.open()
    qtbot.keyClick(picker, Qt.Key.Key_A)

    assert picker.isVisible()


def test_refresh_keeps_the_selection(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1), playlist(2), playlist(3)])
    picker.list.setCurrentIndex(picker.list.model().index(2, 0))

    picker.refresh_button.click()
    monkeypatch.setattr(
        "fairshuffle.ui.playlists.list_editable_playlists",
        lambda _client, _owner: [playlist(3), playlist(4)],
    )
    jobs.release()

    assert picker.selected_playlist_id() == "fakeplaylist3"


def test_a_refresh_that_drops_the_selected_playlist_selects_the_first(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1), playlist(2)])
    picker.list.setCurrentIndex(picker.list.model().index(1, 0))

    load(jobs, monkeypatch, lists, [playlist(1), playlist(3)])

    assert picker.selected_playlist_id() == "fakeplaylist1"


def test_a_failed_load_says_why(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(_client: object, _owner: str) -> list[object]:
        raise SpotifyUnavailable("Couldn't reach Spotify (ConnectionError).")

    monkeypatch.setattr("fairshuffle.ui.playlists.list_editable_playlists", unreachable)
    lists.refresh()
    jobs.release()

    assert picker.status_label.text() == "Couldn't reach Spotify (ConnectionError)."
    assert picker.refresh_button.isEnabled()


def test_signing_out_empties_the_window(
    picker: PlaylistPicker,
    account: FakeAccount,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1)])
    account.sign_out()

    assert shown_names(picker) == []
    assert picker.account_label.text() == "Not signed in to Spotify"
    assert picker.status_label.text() == SIGNED_OUT


def test_without_a_name_the_header_still_says_signed_in(
    picker: PlaylistPicker, account: FakeAccount
) -> None:
    account.sign_in(name=None)

    assert picker.account_label.text() == "Signed in to Spotify"


def test_a_long_list_uses_fixed_row_heights(picker: PlaylistPicker) -> None:
    assert picker.list.uniformItemSizes()
    option = QStyleOptionViewItem()
    delegate = picker.list.itemDelegate()
    assert delegate.sizeHint(option, picker.list.model().index(0, 0)).height() == ROW_HEIGHT


def test_a_long_name_is_drawn_cut_with_an_ellipsis(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_name = "The Extremely Long Playlist Name That Goes On " * 4
    load(jobs, monkeypatch, lists, [playlist(1, long_name, 73)])
    drawn: list[str] = []
    real_draw = QPainter.drawText

    def record(painter: QPainter, *args: object) -> None:
        drawn.append(str(args[-1]))
        real_draw(painter, *args)  # type: ignore[call-overload]

    monkeypatch.setattr(QPainter, "drawText", record)
    index = picker.list.model().index(0, 0)
    option = QStyleOptionViewItem()
    option.rect = picker.list.visualRect(index).adjusted(0, 0, 0, 0)
    option.rect.setWidth(300)
    option.rect.setHeight(ROW_HEIGHT)
    option.fontMetrics = QFontMetrics(picker.list.font())
    option.widget = picker.list
    image = QImage(320, ROW_HEIGHT, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    PlaylistRowDelegate().paint(painter, option, index)
    painter.end()

    name, count = drawn
    assert name.endswith("…") and len(name) < len(long_name)
    assert count == "73 items"
    assert index.data(Qt.ItemDataRole.ToolTipRole).startswith(long_name)


def test_a_selected_row_is_drawn_without_a_widget_too(
    picker: PlaylistPicker,
    jobs: HeldJobs,
    lists: PlaylistController,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load(jobs, monkeypatch, lists, [playlist(1, "Gym Mix", None)])
    index = picker.list.model().index(0, 0)
    option = QStyleOptionViewItem()
    option.rect.setRect(0, 0, 300, ROW_HEIGHT)
    option.fontMetrics = QFontMetrics(picker.list.font())
    option.state |= option.state.State_Selected  # type: ignore[attr-defined]
    image = QImage(300, ROW_HEIGHT, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    PlaylistRowDelegate().paint(painter, option, index)  # no widget, no count: must not fail
    painter.end()


def test_the_window_can_be_grabbed(picker: PlaylistPicker) -> None:
    picker.show()
    assert not picker.grab().isNull()
    assert picker.list.indexAt(QPoint(5, 5)).row() in (-1, 0)
