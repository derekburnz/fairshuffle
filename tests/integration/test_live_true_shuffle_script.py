"""The True Shuffle live check (#117) runs its steps and prints no songs, against the fakes.

The script itself is run by hand against Derek's Spotify app; these tests run it on the fake
Spotify and the fake player so a mistake in it shows up here first.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import responses
from fakes.fake_player import FakePlayer
from fakes.fake_spotify import FakeSpotify
from PySide6.QtWidgets import QApplication

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.shuffle import session as true_shuffle
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.models import Playlist

SCRIPT = Path(__file__).parents[2] / "scripts" / "live_true_shuffle_check.py"
SONGS: list[str | None] = [f"spotify:track:fakesong{number}" for number in range(1, 31)]
# The fake plays Spotify's shuffle back to front, so playing the playlist at an offset with
# shuffle back on lands on another song. Whether the real Spotify starts on the offset song is
# what this check asks it on the live run.
FAKE_ONLY_FAILURE = "From the song that was on"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_true_shuffle_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


script = load_script()


@pytest.fixture
def mock() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def spotify(mock: responses.RequestsMock) -> FakeSpotify:
    fake = FakeSpotify(mock)
    fake.add_playlist("fakeplaylist1", list(SONGS))
    return fake


@pytest.fixture
def app(mock: responses.RequestsMock, spotify: FakeSpotify) -> FakePlayer:
    def resolve(uri: str) -> list[str] | None:
        found = spotify.playlists.get(uri.rsplit(":", 1)[-1])
        return [entry for entry in found.uris if entry] if found else None

    fake = FakePlayer(mock, resolve=resolve)
    fake.add_device()
    return fake


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        yield SpotifyClient(SpotifyAuth(http, load_settings(), tokens), sleep=lambda _: None)


def check(client: SpotifyClient, lines: list[str]) -> object:
    return script.live_check(
        client, "fakeplaylist1", lines.append, sleep=lambda _: None, probe_sizes=(100, 200)
    )


def test_every_step_runs_and_passes_on_the_fakes(
    qapp: QApplication,
    client: SpotifyClient,
    spotify: FakeSpotify,
    app: FakePlayer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(true_shuffle, "MAX_SONGS", 100)
    lines: list[str] = []

    report = check(client, lines)

    failed = [name for name, passed in report.results if not passed]  # type: ignore[attr-defined]
    assert failed == [FAKE_ONLY_FAILURE], lines
    assert len(report.results) >= 15  # type: ignore[attr-defined]
    assert any("Pause while paused: PlayerRefused, reason UNKNOWN" in line for line in lines)
    assert any("doesn't exist: NoActiveDevice, reason none" in line for line in lines)
    assert any(
        "200 songs: starts on the first True, skips to the second True" in line for line in lines
    )


def test_it_writes_nothing_and_puts_playback_back(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    check(client, [])

    assert spotify.writes() == []
    assert spotify.playlists["fakeplaylist1"].uris == SONGS
    assert app.is_playing is False
    assert app.shuffle is False  # as it was before the check


def test_the_output_names_no_songs_or_playlists(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    lines: list[str] = []

    check(client, lines)

    assert lines
    assert not any("spotify:" in line or "fake" in line for line in lines)


def test_with_no_spotify_app_open_it_stops_before_any_command(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    app.devices[0].is_active = False

    with pytest.raises(script.player.NoActiveDevice):
        check(client, [])

    assert app.commands() == []


def test_a_playlist_with_too_few_songs_is_refused(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    spotify.add_playlist("fakeplaylist1", list(SONGS[:2]))

    with pytest.raises(script.Stop, match="at least 3 songs"):
        check(client, [])


def test_a_playlist_too_long_for_a_test_playlist_is_refused(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    spotify.add_playlist("fakeplaylist1", [f"spotify:track:fakesong{n}" for n in range(101)])

    with pytest.raises(script.Stop, match="More than 100 songs"):
        check(client, [])

    assert app.commands() == []


def test_only_the_one_owned_shuffle_test_playlist_is_used() -> None:
    def playlist(playlist_id: str, name: str, owner: str) -> Playlist:
        return Playlist(playlist_id, name, owner, False, "fake-snapshot", 30)

    mine = playlist("b2", "Shuffle Test", "fake-user")
    assert (
        script.find_test_playlist([playlist("a1", "Road Trip", "fake-user"), mine], "fake-user")
        == mine
    )
    for lists in (
        [],
        [playlist("a1", "Shuffle Test", "someone-else")],
        [mine, playlist("c3", "Shuffle Test", "fake-user")],
    ):
        with pytest.raises(script.Stop):
            script.find_test_playlist(lists, "fake-user")


def test_when_starting_the_playlist_turns_shuffle_off_step_1_sends_it_again(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    app.play_resets_shuffle = True
    lines: list[str] = []

    report = check(client, lines)

    assert ("Spotify is playing the test playlist, shuffle on", True) in report.results  # type: ignore[attr-defined]


def test_a_failed_step_1_says_what_spotify_reports_without_any_ids(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    app.context_format = "spotify:user:{user}:playlist:{id}"  # the old form of a playlist URI
    lines: list[str] = []

    with pytest.raises(script.Stop, match="with shuffle on"):
        check(client, lines)

    failure = next(line for line in lines if "FAIL" in line)
    assert "a context written 'spotify:user:<id>:playlist:<id>'" in failure
    assert "(the test playlist's ID)" in failure
    assert "shuffle_state true" in failure and "item track" in failure
    assert not any("spotify:track" in line or "fake" in line for line in lines)


@pytest.mark.parametrize(
    ("uri", "shape"),
    [
        ("spotify:playlist:abc123", "'spotify:playlist:<id>'"),
        ("spotify:user:someone:collection", "'spotify:user:<id>:collection'"),
        ("https://open.spotify.com/playlist/abc123", "as a link or other text, not a spotify: URI"),
    ],
)
def test_uri_shapes_keep_only_the_known_words(uri: str, shape: str) -> None:
    assert script.uri_shape(uri) == shape


def test_step_2_prints_where_the_song_on_sits_by_position_only(
    qapp: QApplication, client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    lines: list[str] = []

    check(client, lines)

    reads = [line for line in lines if line.strip().startswith("Read ")]
    assert len(reads) == script.SETTLE_READS
    assert all("at 1 of our order" in line and "context none" in line for line in reads)
    assert any("Our first song is the song that was on: yes" in line for line in lines)


def test_a_refused_command_says_what_spotify_reports_then_stops(
    qapp: QApplication,
    client: SpotifyClient,
    spotify: FakeSpotify,
    app: FakePlayer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        error = script.player.PlayerRefused("Spotify refused that playback command (UNKNOWN).")
        error.reason = "UNKNOWN"
        raise error

    monkeypatch.setattr(script.player, "next_track", refuse)
    lines: list[str] = []

    with pytest.raises(script.player.PlayerRefused):
        check(client, lines)

    failure = next(line for line in lines if "Spotify accepted every command" in line)
    assert "PlayerRefused, reason UNKNOWN" in failure and "Spotify reports" in failure
    assert not any("spotify:track" in line or "fake" in line for line in lines)


class StubClient:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    def get(self, _path: str, _params: object = None) -> dict[str, object]:
        return self.data


def test_song_picture_names_a_relinked_song_by_position_and_lists_disallows() -> None:
    data: dict[str, object] = {
        "item": {
            "type": "track",
            "uri": "spotify:track:other",
            "linked_from": {"uri": "spotify:track:b"},
        },
        "progress_ms": 0,
        "shuffle_state": False,
        "is_playing": True,
        "context": None,
        "actions": {"disallows": {"skipping_next": True, "resuming": False, "Bad Key": True}},
    }

    picture = script.song_picture(
        StubClient(data),  # type: ignore[arg-type]
        songs=["spotify:track:a", "spotify:track:b"],
        order=("spotify:track:b", "spotify:track:a"),
        before="spotify:track:a",
    )

    assert picture == (
        "not ours, not in it, not the one that was on; relinked from a song at 1 of our order, "
        "at 2 of the playlist, not the one that was on; 0 s in; shuffle_state false, "
        "is_playing true; context none; disallows skipping_next and 1 other"
    )
