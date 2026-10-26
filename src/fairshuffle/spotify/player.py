"""Reads and controls playback in the user's Spotify app over Spotify Connect, for the true
shuffle player (M6).

FairShuffle plays no audio itself. Like a network controller that pushes config to a switch
rather than forwarding packets, it sends commands to the Spotify app the user already has open,
which keeps playing (and keeps following Next and Previous) after FairShuffle is closed.

Endpoints (Spotify docs, re-checked 2026-10-25, see the spotify-api-notes skill, Player
section): GET /me/player and GET /me/player/devices need user-read-playback-state; PUT
/me/player/shuffle, PUT /me/player/play, PUT /me/player/pause, POST /me/player/next and POST
/me/player/previous need user-modify-playback-state and a Premium account. Every command page
says "The order of execution is not guaranteed when you use this API with other Player API
endpoints", so callers read the state back after a sequence of commands (shuffle/session.py).

Spotify's error object documents only QUOTA_EXCEEDED as a reason code now, so the player errors
below are mapped from what the API is known to send, and the live test (#117) checks them:
404 or NO_ACTIVE_DEVICE is NoActiveDevice, 403 PREMIUM_REQUIRED is PremiumRequired and any
other 403 on a command is PlayerRefused. A device with is_restricted takes no commands at all,
which controllable_device() reports as DeviceRestricted before anything is sent.

Device names (often the user's own name, as in "Alex's PC") and what is playing are the user's
own data: shown in the player, never logged or put in a repr.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, TypeGuard

from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.errors import (
    AccessDenied,
    DeviceRestricted,
    NoActiveDevice,
    PlayerRefused,
    PremiumRequired,
    RequestRejected,
    SpotifyError,
)
from fairshuffle.spotify.profile import clean_text

MAX_TEXT_LENGTH = 200  # titles and names from Spotify are cut past this before they are shown
# What FairShuffle asks Spotify to play: tracks and episodes by URI, or a playlist as a context.
_PLAYABLE_URI = re.compile(r"spotify:(track|episode):[0-9A-Za-z]{1,64}")
_CONTEXT_URI = re.compile(r"spotify:playlist:[0-9A-Za-z]{1,64}")
_DEVICE_ID = re.compile(r"[0-9A-Za-z_-]{1,128}")
_REPEAT_STATES = frozenset({"off", "track", "context"})
# A sanity bound on one play request, far above any list a person plays. The real limit is
# undocumented; the live test (#117) finds it, and the session (shuffle/session.py) stays under it.
MAX_PLAY_URIS = 10_000

NO_DEVICE = (
    "Open the Spotify app on this PC (or any device) and play something, so FairShuffle has a "
    "player to control."
)
PREMIUM = "Spotify only lets apps control playback for Premium accounts."
RESTRICTED = "The device Spotify is playing on doesn't accept commands from other apps."

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Device:
    """One Spotify Connect device, such as the Spotify app on this PC.

    id can be None: Spotify says so for some devices, and those can't be picked by ID.
    """

    id: str | None = field(repr=False)
    name: str = field(repr=False)
    type: str
    is_active: bool
    is_restricted: bool


@dataclass(frozen=True)
class NowPlaying:
    """The song or episode playing now, with what Spotify's Developer Policy II.5 asks FairShuffle
    to show alongside playback: the cover art, the title and the artist (or the show)."""

    uri: str | None = field(repr=False)
    title: str = field(repr=False)
    artists: str = field(repr=False)  # "Artist A, Artist B", or the show for an episode
    image_url: str | None = field(repr=False)
    duration_ms: int | None


@dataclass(frozen=True)
class PlaybackState:
    """What GET /me/player says. context_uri is the playlist or album playing, if any."""

    device: Device | None
    is_playing: bool
    shuffle: bool
    repeat: str
    context_uri: str | None = field(repr=False)
    item: NowPlaying | None
    progress_ms: int | None


def playback_state(client: SpotifyClient) -> PlaybackState | None:
    """The user's playback right now, or None when nothing is playing on any device (204)."""
    data = client.get("/me/player", {"additional_types": "track,episode"})
    if not data:
        return None
    device = _device(data.get("device"))
    context = data.get("context")
    context_uri = context.get("uri") if isinstance(context, dict) else None
    repeat = data.get("repeat_state")
    progress = data.get("progress_ms")
    return PlaybackState(
        device=device,
        is_playing=data.get("is_playing") is True,
        shuffle=data.get("shuffle_state") is True,
        repeat=repeat if repeat in _REPEAT_STATES else "off",
        context_uri=context_uri if _is_context_uri(context_uri) else None,
        item=_now_playing(data.get("item")),
        progress_ms=progress if _is_count(progress) else None,
    )


def devices(client: SpotifyClient) -> list[Device]:
    """The user's Spotify Connect devices that Spotify can see right now."""
    entries = client.get("/me/player/devices").get("devices")
    if not isinstance(entries, list):
        return []
    return [device for entry in entries if (device := _device(entry)) is not None]


def controllable_device(client: SpotifyClient) -> Device:
    """The active device, checked first so a command isn't sent to nothing.

    NoActiveDevice when no Spotify app is active, DeviceRestricted when the active one refuses
    Web API commands.
    """
    active = next((device for device in devices(client) if device.is_active), None)
    if active is None:
        raise NoActiveDevice(NO_DEVICE)
    if active.is_restricted:
        raise DeviceRestricted(RESTRICTED)
    return active


def set_shuffle(client: SpotifyClient, on: bool, device_id: str | None = None) -> None:
    """Turn Spotify's own shuffle on or off."""
    params = {"state": "true" if on else "false", **_device_param(device_id)}
    _command(client, "PUT", "/me/player/shuffle", params=params)


def play(
    client: SpotifyClient,
    *,
    context_uri: str | None = None,
    offset: int | None = None,
    uris: list[str] | None = None,
    position_ms: int | None = None,
    device_id: str | None = None,
) -> None:
    """Start playing a playlist (from offset, 0-based) or a list of track and episode URIs,
    position_ms into the first song.

    Exactly one of context_uri and uris. Local files can't be played through the Web API, so
    their spotify:local: URIs are refused here rather than sent.
    """
    if (context_uri is None) == (uris is None):
        raise ValueError("Play either a playlist or a list of URIs.")
    body: dict[str, Any]
    if context_uri is not None:
        if not _CONTEXT_URI.fullmatch(context_uri):
            raise ValueError("That isn't a Spotify playlist URI.")
        body = {"context_uri": context_uri}
        if offset is not None:
            if not _is_count(offset):
                raise ValueError("The offset is a whole number counting from 0.")
            body["offset"] = {"position": offset}
    else:
        if offset is not None:  # Spotify takes an offset only with a playlist or album
            raise ValueError("An offset needs a playlist.")
        if not uris or len(uris) > MAX_PLAY_URIS:
            raise ValueError(f"Play needs 1 to {MAX_PLAY_URIS} URIs.")
        if not all(isinstance(uri, str) and _PLAYABLE_URI.fullmatch(uri) for uri in uris):
            raise ValueError("Play takes only track and episode URIs.")
        body = {"uris": list(uris)}
    if position_ms is not None:
        if not _is_count(position_ms):
            raise ValueError("position_ms is a whole number of milliseconds from 0.")
        body["position_ms"] = position_ms
    _command(client, "PUT", "/me/player/play", params=_device_param(device_id), body=body)


def resume(client: SpotifyClient, device_id: str | None = None) -> None:
    """Carry on playing what is paused (PUT /me/player/play with no body)."""
    _command(client, "PUT", "/me/player/play", params=_device_param(device_id))


def pause(client: SpotifyClient, device_id: str | None = None) -> None:
    _command(client, "PUT", "/me/player/pause", params=_device_param(device_id))


def next_track(client: SpotifyClient, device_id: str | None = None) -> None:
    _command(client, "POST", "/me/player/next", params=_device_param(device_id))


def previous_track(client: SpotifyClient, device_id: str | None = None) -> None:
    _command(client, "POST", "/me/player/previous", params=_device_param(device_id))


def _command(
    client: SpotifyClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> None:
    """Send one playback command and turn Spotify's refusals into player errors."""
    try:
        client.request(method, path, params=params or None, body=body)
    except AccessDenied as error:
        if error.reason == "PREMIUM_REQUIRED":
            raise _keeping_reason(PremiumRequired(PREMIUM), error) from None
        refused = PlayerRefused(
            "Spotify refused that playback command"
            + (f" ({error.reason})" if error.reason else "")
            + "."
        )
        raise _keeping_reason(refused, error) from None
    except RequestRejected as error:
        if error.status == 404 or error.reason == "NO_ACTIVE_DEVICE":
            raise _keeping_reason(NoActiveDevice(NO_DEVICE), error) from None
        raise
    log.info("Sent %s %s", method, path)


def _keeping_reason[E: SpotifyError](mapped: E, original: SpotifyError) -> E:
    """The player error with Spotify's reason code still on it, for the log and the live test."""
    mapped.reason = original.reason
    return mapped


def _device_param(device_id: str | None) -> dict[str, str]:
    if device_id is None:
        return {}
    if not _DEVICE_ID.fullmatch(device_id):
        raise ValueError("That isn't a Spotify device ID.")
    return {"device_id": device_id}


def _device(entry: Any) -> Device | None:
    if not isinstance(entry, dict):
        return None
    device_id = entry.get("id")
    return Device(
        id=device_id if isinstance(device_id, str) and _DEVICE_ID.fullmatch(device_id) else None,
        name=_text(entry.get("name")) or "Unnamed device",
        type=_text(entry.get("type")) or "Unknown",
        is_active=entry.get("is_active") is True,
        is_restricted=entry.get("is_restricted") is True,
    )


def _now_playing(item: Any) -> NowPlaying | None:
    """A track or an episode. An ad or an unknown item (null) is None."""
    if not isinstance(item, dict):
        return None
    uri = item.get("uri")
    duration = item.get("duration_ms")
    if item.get("type") == "episode":
        show = item.get("show")
        artists = _text(show.get("name")) if isinstance(show, dict) else None
        images = item.get("images")
    else:
        names = [
            name
            for artist in item.get("artists") or []
            if isinstance(artist, dict) and (name := _text(artist.get("name")))
        ]
        artists = ", ".join(names) or None
        album = item.get("album")
        images = album.get("images") if isinstance(album, dict) else None
    return NowPlaying(
        uri=uri if isinstance(uri, str) and _PLAYABLE_URI.fullmatch(uri) else None,
        title=_text(item.get("name")) or "Unknown title",
        artists=artists or "Unknown artist",
        image_url=best_image(images),
        duration_ms=duration if _is_count(duration) else None,
    )


def best_image(images: Any, size: int = 300) -> str | None:
    """The https URL of the smallest image at least size pixels wide, else the largest one.

    Spotify lists images widest first and can leave width and height out (null), as it does for
    a playlist cover the user uploaded. Only https links on Spotify's image hosts are kept, so a
    reply can't point the app at another server.
    """
    if not isinstance(images, list):
        return None
    usable: list[tuple[int, str]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        url = image.get("url")
        width = image.get("width")
        if isinstance(url, str) and _is_image_url(url):
            usable.append((width if _is_count(width) else 0, url))
    if not usable:
        return None
    big_enough = [entry for entry in usable if entry[0] >= size]
    if big_enough:
        return min(big_enough)[1]
    return max(usable)[1]


# The path is printable ASCII with no backslash, since the UI hands the link to Qt to fetch.
_IMAGE_HOST = re.compile(r"https://([a-z0-9-]+\.)*(scdn\.co|spotifycdn\.com)/[!-\[\]-~]*")


def _is_image_url(url: str) -> bool:
    return len(url) <= 2_000 and _IMAGE_HOST.fullmatch(url) is not None


def _is_context_uri(value: Any) -> TypeGuard[str]:
    """Any playlist, album or artist URI: playing one of those is how a context shows up."""
    return isinstance(value, str) and _ANY_CONTEXT_URI.fullmatch(value) is not None


_ANY_CONTEXT_URI = re.compile(r"spotify:(playlist|album|artist|show|collection):[0-9A-Za-z:]{1,80}")


def _text(value: Any) -> str | None:
    return clean_text(value, MAX_TEXT_LENGTH) if isinstance(value, str) else None


def _is_count(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
