"""The player client (spotify/player.py) against the fake Spotify Connect player."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
import responses
from fakes.fake_player import FakePlayer

from fairshuffle.auth.oauth import SpotifyAuth, Tokens
from fairshuffle.config import load_settings
from fairshuffle.spotify import player
from fairshuffle.spotify.client import API_BASE, SpotifyClient, new_session
from fairshuffle.spotify.errors import (
    DeviceRestricted,
    NoActiveDevice,
    PlayerRefused,
    PremiumRequired,
    RateLimited,
)

PLAYLIST = "spotify:playlist:fakeplaylist1"
SONGS = [f"spotify:track:fakesong{number}" for number in range(1, 6)]


@pytest.fixture
def spotify() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def fake(spotify: responses.RequestsMock) -> FakePlayer:
    fake = FakePlayer(spotify, resolve=lambda uri: list(SONGS) if uri == PLAYLIST else None)
    fake.add_device()
    return fake


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    with new_session() as http:
        tokens = Tokens("fake-access-token-1", "fake-refresh-token-for-tests", 3600, frozenset())
        yield SpotifyClient(SpotifyAuth(http, load_settings(), tokens), sleep=lambda _: None)


# Reading


def test_nothing_playing_anywhere_reads_as_none(fake: FakePlayer, client: SpotifyClient) -> None:
    fake.devices[0].is_active = False

    assert player.playback_state(client) is None


def test_the_state_says_what_is_playing_and_where(fake: FakePlayer, client: SpotifyClient) -> None:
    player.play(client, context_uri=PLAYLIST)

    state = player.playback_state(client)

    assert state is not None
    assert state.is_playing
    assert not state.shuffle
    assert state.repeat == "off"
    assert state.context_uri == PLAYLIST
    assert state.device is not None and state.device.name == "Fake PC"
    assert state.item is not None
    assert state.item.uri == SONGS[0]
    assert state.item.artists == "Fake Artist"
    assert state.item.image_url == "https://i.scdn.co/image/fake-cover"
    assert fake.calls[-1].query["additional_types"] == ["track,episode"]


def test_the_state_tolerates_odd_fields(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(
        f"{API_BASE}/me/player",
        json={
            "device": "not an object",
            "shuffle_state": "yes",
            "repeat_state": "sometimes",
            "context": {"uri": "javascript:alert(1)"},
            "item": {"type": "ad"},
            "is_playing": 1,
            "progress_ms": -5,
        },
    )

    state = player.playback_state(client)

    assert state == player.PlaybackState(
        device=None,
        is_playing=False,
        shuffle=False,
        repeat="off",
        context_uri=None,
        item=player.NowPlaying(None, "Unknown title", "Unknown artist", None, None),
        progress_ms=None,
    )


def test_an_episode_shows_its_show_and_cover(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.get(
        f"{API_BASE}/me/player",
        json={
            "is_playing": True,
            "item": {
                "type": "episode",
                "uri": "spotify:episode:fakeepisode1",
                "name": "Episode 1",
                "show": {"name": "Fake Show"},
                "images": [{"url": "https://i.scdn.co/image/fake-episode", "width": 64}],
                "duration_ms": 60_000,
            },
        },
    )

    state = player.playback_state(client)

    assert state is not None and state.item is not None
    assert (state.item.title, state.item.artists) == ("Episode 1", "Fake Show")
    assert state.item.image_url == "https://i.scdn.co/image/fake-episode"
    assert state.item.duration_ms == 60_000


def test_devices_are_listed(fake: FakePlayer, client: SpotifyClient) -> None:
    fake.add_device("fake-device-2", name="Fake Phone", type="Smartphone", is_active=False)

    found = player.devices(client)

    assert [(device.id, device.type, device.is_active) for device in found] == [
        ("fake-device-1", "Computer", True),
        ("fake-device-2", "Smartphone", False),
    ]


def test_device_names_and_songs_stay_out_of_reprs(fake: FakePlayer, client: SpotifyClient) -> None:
    player.play(client, context_uri=PLAYLIST)

    state = player.playback_state(client)

    assert "Fake PC" not in repr(state)
    assert "fakesong" not in repr(state)
    assert "Fake Artist" not in repr(state)


def test_the_controllable_device_is_the_active_one(fake: FakePlayer, client: SpotifyClient) -> None:
    fake.add_device("fake-device-2", is_active=False)

    assert player.controllable_device(client).id == "fake-device-1"


def test_no_active_device_is_reported_before_any_command(
    fake: FakePlayer, client: SpotifyClient
) -> None:
    fake.devices[0].is_active = False

    with pytest.raises(NoActiveDevice, match="Open the Spotify app"):
        player.controllable_device(client)

    assert fake.commands() == []


def test_a_restricted_device_is_reported_before_any_command(
    fake: FakePlayer, client: SpotifyClient
) -> None:
    fake.devices[0].is_restricted = True

    with pytest.raises(DeviceRestricted):
        player.controllable_device(client)


# Commands


def test_shuffle_turns_off_and_on(fake: FakePlayer, client: SpotifyClient) -> None:
    fake.shuffle = True

    player.set_shuffle(client, False)
    assert fake.shuffle is False
    player.set_shuffle(client, True, device_id="fake-device-1")
    assert fake.shuffle is True

    assert [call.query for call in fake.commands()] == [
        {"state": ["false"]},
        {"state": ["true"], "device_id": ["fake-device-1"]},
    ]


def test_a_playlist_plays_from_the_offset(fake: FakePlayer, client: SpotifyClient) -> None:
    player.play(client, context_uri=PLAYLIST, offset=2)

    assert fake.current == SONGS[2]
    assert fake.commands()[-1].body == {"context_uri": PLAYLIST, "offset": {"position": 2}}


def test_a_list_of_songs_plays_in_that_order(fake: FakePlayer, client: SpotifyClient) -> None:
    order = list(reversed(SONGS))

    player.play(client, uris=order)

    assert fake.order == order
    assert fake.commands()[-1].body == {"uris": order}


def test_pause_resume_next_and_previous(fake: FakePlayer, client: SpotifyClient) -> None:
    player.play(client, context_uri=PLAYLIST)

    player.pause(client)
    assert not fake.is_playing
    player.resume(client)
    assert fake.is_playing
    player.next_track(client)
    player.next_track(client)
    assert fake.current == SONGS[2]
    player.previous_track(client)
    assert fake.current == SONGS[1]

    assert [(call.method, call.path) for call in fake.commands()][1:] == [
        ("PUT", "/v1/me/player/pause"),
        ("PUT", "/v1/me/player/play"),
        ("POST", "/v1/me/player/next"),
        ("POST", "/v1/me/player/next"),
        ("POST", "/v1/me/player/previous"),
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"context_uri": PLAYLIST, "uris": SONGS},
        {"context_uri": "spotify:album:fakealbum1"},
        {"context_uri": "https://evil.example/playlist"},
        {"context_uri": PLAYLIST, "offset": -1},
        {"context_uri": PLAYLIST, "offset": True},
        {"context_uri": PLAYLIST, "offset": 1.5},
        {"uris": ["spotify:track:fakesong1"] * (player.MAX_PLAY_URIS + 1)},
        {"uris": []},
        {"uris": ["spotify:local:Artist:Album:Title:180"]},  # local files can't be played
        {"uris": SONGS, "offset": 1},
        {"context_uri": PLAYLIST, "device_id": "../me"},
    ],
)
def test_bad_play_requests_never_leave_the_app(
    fake: FakePlayer, client: SpotifyClient, arguments: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        player.play(client, **arguments)  # type: ignore[arg-type]

    assert fake.calls == []


# Refusals


@pytest.mark.parametrize(
    "command",
    [
        lambda client: player.set_shuffle(client, False),
        lambda client: player.play(client, context_uri=PLAYLIST),
        lambda client: player.pause(client),
        lambda client: player.next_track(client),
        lambda client: player.previous_track(client),
    ],
    ids=["shuffle", "play", "pause", "next", "previous"],
)
def test_a_free_account_is_told_premium_is_needed(
    fake: FakePlayer, client: SpotifyClient, command: object
) -> None:
    fake.premium = False

    with pytest.raises(PremiumRequired, match="Premium"):
        command(client)  # type: ignore[operator]


def test_a_command_with_no_active_device_says_to_open_spotify(
    fake: FakePlayer, client: SpotifyClient
) -> None:
    fake.devices[0].is_active = False

    with pytest.raises(NoActiveDevice):
        player.play(client, context_uri=PLAYLIST)


def test_an_unknown_device_counts_as_no_device(fake: FakePlayer, client: SpotifyClient) -> None:
    with pytest.raises(NoActiveDevice):
        player.pause(client, device_id="fake-device-9")


def test_a_restricted_device_refuses_commands(fake: FakePlayer, client: SpotifyClient) -> None:
    fake.devices[0].is_restricted = True

    with pytest.raises(PlayerRefused, match="refused that playback command"):
        player.next_track(client)


def test_a_reason_code_is_quoted_on_other_refusals(fake: FakePlayer, client: SpotifyClient) -> None:
    player.play(client, context_uri=PLAYLIST)
    player.pause(client)

    with pytest.raises(PlayerRefused, match=r"\(UNKNOWN\)"):
        player.pause(client)  # already paused


def test_rate_limits_still_come_through(
    spotify: responses.RequestsMock, client: SpotifyClient
) -> None:
    spotify.put(
        f"{API_BASE}/me/player/pause",
        status=429,
        headers={"Retry-After": "3600"},
        json={"error": {"status": 429, "message": "slow down"}},
    )

    with pytest.raises(RateLimited):
        player.pause(client)


def test_commands_log_the_route_but_never_the_device(
    fake: FakePlayer, client: SpotifyClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    player.play(client, context_uri=PLAYLIST, device_id="fake-device-1")

    assert "fake-device-1" not in caplog.text
    assert "fakeplaylist1" not in caplog.text
    assert "PUT /me/player/play" in caplog.text


# Images


@pytest.mark.parametrize(
    ("images", "expected"),
    [
        (None, None),
        ([], None),
        (
            [
                {"url": "https://i.scdn.co/image/big", "width": 640},
                {"url": "https://i.scdn.co/image/mid", "width": 300},
                {"url": "https://i.scdn.co/image/small", "width": 64},
            ],
            "https://i.scdn.co/image/mid",
        ),
        ([{"url": "https://i.scdn.co/image/small", "width": 64}], "https://i.scdn.co/image/small"),
        (
            [{"url": "https://mosaic.scdn.co/640/fake", "width": None, "height": None}],
            "https://mosaic.scdn.co/640/fake",
        ),
        (
            [{"url": "https://image-cdn-ak.spotifycdn.com/image/fake", "width": None}],
            "https://image-cdn-ak.spotifycdn.com/image/fake",
        ),
        ([{"url": "http://i.scdn.co/image/plain-http", "width": 640}], None),
        ([{"url": "https://evil.example/i.scdn.co/x", "width": 640}], None),
        ([{"url": "https://scdn.co.evil.example/x", "width": 640}], None),
        ([{"url": "https://i.scdn.co/image/x\x00y", "width": 640}], None),
        ([{"url": "https://i.scdn.co/image\\x", "width": 640}], None),
        ([{"url": "https://i.scdn.co/image/caf\u00e9", "width": 640}], None),
        (["not an object", {"width": 640}], None),
    ],
)
def test_the_best_image_is_a_spotify_https_link(images: object, expected: str | None) -> None:
    assert player.best_image(images) == expected
