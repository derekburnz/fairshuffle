"""True shuffle (shuffle/session.py) end to end against the fake Spotify and the fake player."""

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
from fairshuffle.spotify.models import Playlist

SEED = 7


def rng() -> Random:
    return Random(SEED)  # noqa: S311  # tests want repeatable, not secret


SONGS = [f"spotify:track:fakesong{number}" for number in range(1, 251)]  # three writes' worth
PICKED = Playlist("fakeplaylist1", "Shuffle Test", "fakeuser", False, "fake-snapshot", 250)


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
    fake.shuffle = True  # the user had Spotify's own shuffle on
    return fake


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        yield SpotifyClient(SpotifyAuth(http, load_settings(), tokens), sleep=lambda _: None)


def start(client: SpotifyClient, play_playlist_id: str | None = None) -> true_shuffle.Session:
    return true_shuffle.start(client, PICKED, play_playlist_id, rng=rng(), sleep=lambda _: None)


def test_our_order_plays_with_spotifys_shuffle_off(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    session = start(client)

    expected = shuffled(SONGS, rng())
    assert app.shuffle is False
    assert app.order == expected  # not the playlist order, and not Spotify's reversed shuffle
    assert app.current == expected[0]
    assert session.confirmed
    assert session.order == tuple(expected)


def test_the_picked_playlist_is_never_changed(
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


def test_local_files_and_missing_songs_are_left_out_and_counted(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    spotify.add_playlist(
        "fakeplaylist1", ["spotify:local:A:B:C:180", None, *SONGS[:3]], local=frozenset({0})
    )

    session = start(client)

    assert session.skipped == 2
    assert sorted(session.order) == sorted(SONGS[:3])


def test_a_playlist_of_only_local_files_has_nothing_to_play(
    client: SpotifyClient, spotify: FakeSpotify, app: FakePlayer
) -> None:
    spotify.add_playlist("fakeplaylist1", ["spotify:local:A:B:C:180"], local=frozenset({0}))

    with pytest.raises(true_shuffle.NothingToPlay):
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

    assert true_shuffle.stop(client, session)

    assert app.context_uri == "spotify:playlist:fakeplaylist1"
    assert app.shuffle is True  # back to how the user had it
    assert now is not None and SONGS.index(now) in (app.position, len(SONGS) - 1 - app.position)


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

    assert app.context_uri == "spotify:playlist:fakeplaylist1"
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
    assert "Shuffle Test" not in caplog.text
    assert "250 songs" in caplog.text
    assert "fakesong" not in repr(session)
