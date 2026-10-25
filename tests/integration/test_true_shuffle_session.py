"""True shuffle (shuffle/session.py) end to end against the fake Spotify and the fake player.

Each test starts with the user listening to their playlist in the Spotify app, Spotify's own
shuffle on, partway through a song, as they would be when they tick True Shuffle in the tray.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from random import Random

import pytest
import responses
from fakes.fake_player import FakePlayer
from fakes.fake_spotify import FakeSpotify

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.shuffle import session as true_shuffle
from fairshuffle.shuffle.engine import shuffled
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.errors import NoActiveDevice, PremiumRequired

SEED = 7
SOURCE = "spotify:playlist:fakeplaylist1"
SONGS = [f"spotify:track:fakesong{number}" for number in range(1, 251)]  # three writes' worth
NOW = SONGS[9]  # the song playing when True Shuffle is ticked


def rng() -> Random:
    return Random(SEED)  # noqa: S311  # tests want repeatable, not secret


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
    listening(fake, SONGS, NOW)
    return fake


def listening(app: FakePlayer, songs: list[str], now: str) -> None:
    """The user plays the source playlist in Spotify, with Spotify's shuffle on."""
    app.shuffle = True
    app.context_uri = SOURCE
    app.order = list(songs)
    app.position = songs.index(now)
    app.progress_ms = 42_000
    app.is_playing = True


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        yield SpotifyClient(SpotifyAuth(http, load_settings(), tokens), sleep=lambda _: None)


def start(client: SpotifyClient, play_playlist_id: str | None = None) -> true_shuffle.Session:
    return true_shuffle.start(client, play_playlist_id, rng=rng(), sleep=lambda _: None)


def expected_order() -> list[str]:
    rest = [song for song in SONGS if song != NOW]
    return [NOW, *shuffled(rest, rng())]


def test_the_song_on_now_carries_on_and_the_rest_follow_in_our_order(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client)

    assert app.shuffle is False
    assert app.order == expected_order()  # not the playlist order, not Spotify's shuffle
    assert app.current == NOW
    assert app.progress_ms == 42_000  # same point in the song, so the music doesn't jump
    assert app.is_playing
    assert session.confirmed
    assert session.order == tuple(expected_order())


def test_the_playlist_playing_is_never_changed(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    start(client)

    assert spotify.playlists["fakeplaylist1"].uris == SONGS
    assert all("/fakeplaylist1/" not in call.path for call in spotify.writes())


def test_the_order_goes_into_one_private_playlist_of_our_own(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client)

    [made] = spotify.created
    assert made.public is False
    assert session.play_playlist_id == made.id
    assert made.uris == list(session.order)
    assert app.context_uri == f"spotify:playlist:{made.id}"
    create = next(call for call in spotify.calls if call.path == "/v1/me/playlists")
    assert create.body is not None and create.body["name"] == true_shuffle.PLAYLIST_NAME


def test_the_next_start_reuses_that_playlist(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    first = start(client)
    listening(app, SONGS, NOW)
    second = start(client, first.play_playlist_id)

    assert len(spotify.created) == 1
    assert second.play_playlist_id == first.play_playlist_id


def test_a_deleted_playlist_is_made_again(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client, "fakegone1")

    assert len(spotify.created) == 1
    assert session.play_playlist_id == spotify.created[0].id


def test_next_and_previous_in_spotify_follow_our_order(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client)

    app.press_next()
    app.press_next()
    app.press_previous()

    assert app.current == session.order[1]
    assert app.shuffle is False


def test_shuffle_off_that_lands_after_the_play_is_sent_again(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    app.deferred_shuffle = True  # "The order of execution is not guaranteed"

    session = start(client)

    assert session.confirmed
    assert app.shuffle is False
    assert app.order == list(session.order)
    plays = [call for call in app.commands() if call.path.endswith("/play")]
    assert len(plays) == 2  # the first started on Spotify's pick of song, so it went again


def test_ticked_while_paused_it_stays_paused(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    app.is_playing = False

    start(client)

    assert app.current == NOW
    assert app.is_playing is False


def test_local_files_and_missing_songs_are_left_out_and_counted(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    spotify.add_playlist(
        "fakeplaylist1", ["spotify:local:A:B:C:180", None, *SONGS[:3]], local=frozenset({0})
    )
    listening(app, SONGS[:3], SONGS[1])

    session = start(client)

    assert session.skipped == 2
    assert session.order[0] == SONGS[1]
    assert sorted(session.order) == sorted(SONGS[:3])


def test_a_song_listed_twice_still_plays_twice(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    songs = [SONGS[0], SONGS[1], SONGS[0]]
    spotify.add_playlist("fakeplaylist1", list[str | None](songs))
    listening(app, songs, SONGS[0])

    session = start(client)

    assert sorted(session.order) == sorted(songs)


@pytest.mark.parametrize(
    "context",
    [None, "spotify:album:fakealbum1", "spotify:collection:fakeuser", "spotify:playlist:fakemine"],
    ids=["nothing", "album", "liked-songs", "already-ours"],
)
def test_only_a_playlist_playing_now_can_be_true_shuffled(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer, context: str | None
) -> None:
    app.context_uri = context

    with pytest.raises(true_shuffle.NothingToPlay, match="Play one of your playlists"):
        true_shuffle.start(client, "fakemine", sleep=lambda _: None)

    assert spotify.writes() == []


def test_someone_elses_playlist_is_explained(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    spotify.add_playlist("fakeplaylist1", list(SONGS), editable=False)

    with pytest.raises(true_shuffle.NothingToPlay, match="you made or collaborate on"):
        start(client)

    assert app.shuffle is True  # nothing changed in Spotify


def test_a_playlist_of_only_local_files_has_nothing_to_play(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    spotify.add_playlist("fakeplaylist1", ["spotify:local:A:B:C:180"], local=frozenset({0}))

    with pytest.raises(true_shuffle.NothingToPlay, match="Local files"):
        start(client)

    assert spotify.created == []


def test_with_no_spotify_app_open_nothing_is_written(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    app.devices[0].is_active = False

    with pytest.raises(NoActiveDevice):
        start(client)

    assert spotify.writes() == []


def test_a_free_account_is_told_before_playback_changes(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    app.premium = False

    with pytest.raises(PremiumRequired):
        start(client)

    assert app.shuffle is True  # the user's own shuffle setting is untouched


def test_turning_it_off_goes_back_to_the_playlist_from_the_song_playing_now(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client)
    app.press_next()
    now = app.current
    assert now is not None

    assert true_shuffle.stop(client, session)

    assert app.context_uri == SOURCE
    assert app.shuffle is True  # back to how the user had it
    # With Spotify's shuffle back on, the fake plays the playlist back to front from there.
    assert app.order[app.position] == list(reversed(SONGS))[SONGS.index(now)]


def test_turning_it_off_after_moving_on_in_spotify_changes_nothing(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client)
    app.context_uri = "spotify:playlist:fakeotherplaylist"
    before = len(app.commands())

    assert not true_shuffle.stop(client, session)

    assert len(app.commands()) == before


def test_turning_it_off_while_paused_stays_paused(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client)
    app.is_playing = False

    true_shuffle.stop(client, session)

    assert app.context_uri == SOURCE
    assert app.is_playing is False


def test_the_log_has_counts_but_no_songs_or_playlists(
    client: SpotifyClient,
    spotify: FakeSpotify,
    app: FakePlayer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    session = start(client)
    true_shuffle.stop(client, session)

    assert "fakesong" not in caplog.text
    assert "fakeplaylist1" not in caplog.text
    assert "fakecreated" not in caplog.text
    assert "250 songs" in caplog.text
    assert "fakesong" not in repr(session)
