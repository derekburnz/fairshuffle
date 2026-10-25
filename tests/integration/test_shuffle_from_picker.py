"""The whole path from the picker's buttons to Spotify and back, against the fake Spotify (#32).

The picker, the ShuffleController, the runner, the real SpotifyClient, the backups and the
read-back check all run; only Spotify and the thread pool are stand-ins. Jobs run on the test's
own thread when the test releases them.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterator, Sequence

import pytest
import responses
from fakes.fake_spotify import FakeSpotify
from fakes.ui_fakes import FakeAccount, HeldJobs
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.shuffle import engine, runner
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.models import Playlist
from fairshuffle.spotify.ratelimit import RetryPolicy
from fairshuffle.ui.picker import PlaylistPicker
from fairshuffle.ui.playlists import PlaylistController
from fairshuffle.ui.shuffle import ShuffleController
from fairshuffle.ui.tray import PLAY_TIP, TrayIcon

LOCAL = "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"
SONGS: list[str | None] = [f"spotify:track:fake{number:05d}" for number in range(12)]


@pytest.fixture(autouse=True)
def repeatable_shuffle(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = random.Random(4)  # noqa: S311  # tests want repeatable, not secret
    monkeypatch.setattr(runner, "shuffled", lambda items: engine.shuffled(items, rng))


@pytest.fixture
def fake() -> Iterator[FakeSpotify]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield FakeSpotify(mock)


@pytest.fixture
def account(qapp: QApplication) -> Iterator[FakeAccount]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        signed_in = FakeAccount()
        auth = SpotifyAuth(http, load_settings(), tokens)
        signed_in.client = SpotifyClient(auth, RetryPolicy(max_attempts=3), sleep=lambda _: None)
        yield signed_in


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    planned: list[int] = []

    def choose(
        _parent: QWidget, _title: str, _text: str, _buttons: Sequence[str], default: int
    ) -> int:
        return planned.pop(0)

    monkeypatch.setattr("fairshuffle.ui.picker.choose", choose)
    return planned


@pytest.fixture
def app_parts(
    qtbot: QtBot,
    fake: FakeSpotify,
    account: FakeAccount,
    jobs: HeldJobs,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TrayIcon, PlaylistPicker]]:
    """The tray icon with the picker open on the fake "Road Trip" playlist."""
    listed = Playlist("fakelist", "Road Trip", "fakeuser", False, "fake-snapshot", len(SONGS))
    monkeypatch.setattr("fairshuffle.ui.playlists.user_id", lambda _client: "fakeuser")
    monkeypatch.setattr(
        "fairshuffle.ui.playlists.list_editable_playlists", lambda _client, _owner: [listed]
    )
    lists = PlaylistController(account, runner=jobs)  # type: ignore[arg-type]
    shuffles = ShuffleController(account, runner=jobs)  # type: ignore[arg-type]
    tray = TrayIcon(lambda: None, account, lists, shuffles)  # type: ignore[arg-type]
    tray.show_picker()
    jobs.release()  # the playlist list
    picker = tray.picker
    assert picker is not None
    qtbot.addWidget(picker)
    yield tray, picker
    tray.hide()


def test_shuffle_then_undo_from_the_picker(
    fake: FakeSpotify,
    jobs: HeldJobs,
    app_parts: tuple[TrayIcon, PlaylistPicker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tray, picker = app_parts
    playlist = fake.add_playlist("fakelist", list(SONGS))
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(tray, "showMessage", lambda title, text, *_: toasts.append((title, text)))

    picker.shuffle_button.click()
    jobs.release()

    assert Counter(playlist.uris) == Counter(SONGS)
    assert playlist.uris != SONGS
    assert toasts == [("Shuffled Road Trip", PLAY_TIP)]
    assert picker.undo_button.isEnabled()

    picker.undo_button.click()
    jobs.release()

    assert playlist.uris == SONGS
    assert toasts[-1][0] == "Put back Road Trip"


def test_keep_order_from_the_box_keeps_every_date_added(
    fake: FakeSpotify, jobs: HeldJobs, app_parts: tuple[TrayIcon, PlaylistPicker]
) -> None:
    _tray, picker = app_parts
    playlist = fake.add_playlist("fakelist", list(SONGS))
    dates = {entry.uri: entry.added_at for entry in playlist.entries}

    picker.keep_date_added.setChecked(True)
    picker.shuffle_button.click()
    jobs.release()

    assert playlist.uris != SONGS
    assert {entry.uri: entry.added_at for entry in playlist.entries} == dates
    assert all(
        call.method == "PUT" and call.body and "range_start" in call.body for call in fake.writes()
    )


def test_local_files_ask_first_and_keep_order_keeps_them(
    fake: FakeSpotify,
    jobs: HeldJobs,
    answers: list[int],
    app_parts: tuple[TrayIcon, PlaylistPicker],
) -> None:
    _tray, picker = app_parts
    uris = [*SONGS, LOCAL]
    playlist = fake.add_playlist("fakelist", uris, local=frozenset({len(SONGS)}))
    answers.append(0)  # "Use keep-order mode"

    picker.shuffle_button.click()
    jobs.release()  # stops before writing and asks
    assert fake.writes() == []
    jobs.release()  # the keep-order rerun

    assert Counter(playlist.uris) == Counter(uris)
    assert LOCAL in playlist.uris
