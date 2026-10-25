"""An in-memory Spotify Connect player that answers FairShuffle's /me/player calls the way the
Web API reference describes them (re-checked 2026-10-25, see the spotify-api-notes skill).

Like FakeSpotify it sits behind `responses`, so the real SpotifyClient and spotify/player.py run
unchanged. The two can share one RequestsMock: pass resolve=fake_spotify_lookup so playing a
playlist context reads the fake playlist's songs. It serves:

- GET /me/player: 204 when no device is active, else the state with the device, shuffle_state,
  repeat_state, context, item and progress_ms;
- GET /me/player/devices: every device;
- PUT /me/player/shuffle?state=true|false, PUT /me/player/play (context_uri with
  offset.position, or uris, or no body to resume), PUT /me/player/pause, POST /me/player/next
  and POST /me/player/previous: 204.

Where the docs are silent, the fake copies what the API is known to send and says so: a command
with no active device answers 404 NO_ACTIVE_DEVICE, a free account 403 PREMIUM_REQUIRED, a
restricted device 403 with no reason, and an unknown device_id 404. With shuffle on, the fake
plays a context back to front, so a test sees at once when our order was not the one played.
deferred_shuffle=True copies "The order of execution is not guaranteed": a shuffle command only
takes effect after the next command, so code must read the state back rather than trust order.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests
import responses

from fairshuffle.spotify.client import API_BASE

_PLAYER = re.compile(re.escape(API_BASE) + r"/me/player(?P<rest>/[a-z]+)?")

Reply = tuple[int, dict[str, str], str]


@dataclass
class FakeDevice:
    id: str
    name: str = "Fake PC"
    type: str = "Computer"
    is_active: bool = True
    is_restricted: bool = False


@dataclass
class PlayerCall:
    method: str
    path: str
    query: dict[str, list[str]]
    body: dict[str, Any] | None


@dataclass
class FakePlayer:
    """The fake player. Create it with a responses.RequestsMock, then add devices."""

    mock: responses.RequestsMock
    # Turns a playlist context URI into its track URIs in playlist order (None: unknown, 404).
    resolve: Callable[[str], list[str] | None] = lambda _uri: None
    premium: bool = True
    deferred_shuffle: bool = False
    devices: list[FakeDevice] = field(default_factory=list)
    shuffle: bool = False
    repeat: str = "off"
    is_playing: bool = False
    context_uri: str | None = None
    order: list[str] = field(default_factory=list)  # what plays, in the order it plays
    position: int = 0
    calls: list[PlayerCall] = field(default_factory=list)
    _pending_shuffle: bool | None = None

    def __post_init__(self) -> None:
        for method in ("GET", "PUT", "POST"):
            self.mock.add_callback(method, _PLAYER, callback=self._answer)

    def add_device(self, device_id: str = "fake-device-1", **options: Any) -> FakeDevice:
        device = FakeDevice(device_id, **options)
        self.devices.append(device)
        return device

    @property
    def active(self) -> FakeDevice | None:
        return next((device for device in self.devices if device.is_active), None)

    @property
    def current(self) -> str | None:
        return self.order[self.position] if 0 <= self.position < len(self.order) else None

    def commands(self) -> list[PlayerCall]:
        return [call for call in self.calls if call.method != "GET"]

    # The user pressing buttons in the Spotify app itself ------------------------------------

    def press_next(self) -> None:
        self._skip(1)

    def press_previous(self) -> None:
        self._skip(-1)

    # Answering ------------------------------------------------------------------------------

    def _answer(self, request: requests.PreparedRequest) -> Reply:
        url = urlsplit(request.url or "")
        method = (request.method or "GET").upper()
        call = PlayerCall(method, url.path, parse_qs(url.query), _body(request))
        self.calls.append(call)
        if not str(request.headers.get("Authorization", "")).startswith("Bearer "):
            return _error(401, "No token provided")
        match = _PLAYER.fullmatch(f"{url.scheme}://{url.netloc}{url.path}")
        rest = (match["rest"] if match else None) or ""
        if method == "GET" and rest == "":
            return self._state()
        if method == "GET" and rest == "/devices":
            return _ok(200, {"devices": [_device_json(device) for device in self.devices]})
        if method == "GET":
            return _error(404, "Not found")
        refusal = self._refusal(call)
        if refusal is not None:
            return refusal
        reply = self._command(method, rest, call)
        if reply[0] < 300 and rest != "/shuffle" and self._pending_shuffle is not None:
            self.shuffle, self._pending_shuffle = self._pending_shuffle, None
        return reply

    def _refusal(self, call: PlayerCall) -> Reply | None:
        if not self.premium:
            return _error(403, "Player command failed: Premium required", "PREMIUM_REQUIRED")
        wanted = call.query.get("device_id", [None])[0]
        if wanted is not None:
            device = next((device for device in self.devices if device.id == wanted), None)
            if device is None:
                return _error(404, "Device not found")
            for other in self.devices:  # a command to a device makes it the active one
                other.is_active = other is device
        device = self.active
        if device is None:
            return _error(404, "Player command failed: No active device found", "NO_ACTIVE_DEVICE")
        if device.is_restricted:
            return _error(403, "Player command failed: Restriction violated")
        return None

    def _command(self, method: str, rest: str, call: PlayerCall) -> Reply:
        if method == "PUT" and rest == "/shuffle":
            state = call.query.get("state", [""])[0]
            if state not in ("true", "false"):
                return _error(400, "Invalid state")
            if self.deferred_shuffle:
                self._pending_shuffle = state == "true"
            else:
                self.shuffle = state == "true"
            return _done()
        if method == "PUT" and rest == "/play":
            return self._play(call.body)
        if method == "PUT" and rest == "/pause":
            if not self.is_playing:
                return _error(403, "Player command failed: Restriction violated", "UNKNOWN")
            self.is_playing = False
            return _done()
        if method == "POST" and rest in ("/next", "/previous"):
            self._skip(1 if rest == "/next" else -1)
            return _done()
        return _error(405, "Method not allowed")

    def _play(self, body: dict[str, Any] | None) -> Reply:
        if not body:  # resume
            if self.current is None:
                return _error(404, "Nothing to resume")
            self.is_playing = True
            return _done()
        context_uri, uris, offset = body.get("context_uri"), body.get("uris"), body.get("offset")
        if (context_uri is None) == (uris is None):
            return _error(400, "Give context_uri or uris")
        if uris is not None:
            if offset is not None:
                return _error(400, "offset needs a context")
            self.context_uri, tracks = None, list(uris)
        else:
            tracks = self.resolve(str(context_uri))
            if tracks is None:
                return _error(404, "Context not found")
            self.context_uri = context_uri
        start = offset.get("position", 0) if isinstance(offset, dict) else 0
        if self.shuffle:  # Spotify's own shuffle: anything but the order asked for
            tracks = list(reversed(tracks))
        self.order, self.position = tracks, start
        self.is_playing = self.current is not None
        return _done()

    def _skip(self, step: int) -> None:
        self.position = max(0, self.position + step)
        if self.current is None:  # past the end with repeat off: playback stops
            self.is_playing = False
            self.position = len(self.order)

    def _state(self) -> Reply:
        device = self.active
        if device is None:
            return 204, {}, ""
        current = self.current
        item = None
        if current is not None:
            item = {
                "type": "track",
                "uri": current,
                "name": f"Song {current.rsplit(':', 1)[-1]}",
                "duration_ms": 180_000,
                "artists": [{"name": "Fake Artist"}],
                "album": {"images": [{"url": "https://i.scdn.co/image/fake-cover", "width": 640}]},
            }
        context = {"uri": self.context_uri, "type": "playlist"} if self.context_uri else None
        return _ok(
            200,
            {
                "device": _device_json(device),
                "shuffle_state": self.shuffle,
                "repeat_state": self.repeat,
                "context": context,
                "item": item,
                "is_playing": self.is_playing,
                "progress_ms": 0 if item else None,
                "currently_playing_type": "track" if item else "unknown",
            },
        )


def _device_json(device: FakeDevice) -> dict[str, Any]:
    return {
        "id": device.id,
        "name": device.name,
        "type": device.type,
        "is_active": device.is_active,
        "is_restricted": device.is_restricted,
        "is_private_session": False,
        "volume_percent": 50,
        "supports_volume": True,
    }


def _body(request: requests.PreparedRequest) -> dict[str, Any] | None:
    if not request.body:
        return None
    raw = request.body
    if not isinstance(raw, (str, bytes)):
        raise TypeError("FairShuffle sends JSON bodies")
    data = json.loads(raw)
    return data if isinstance(data, dict) else None


def _ok(status: int, data: dict[str, Any]) -> Reply:
    return status, {"Content-Type": "application/json"}, json.dumps(data)


def _done() -> Reply:
    return 204, {}, ""


def _error(status: int, message: str, reason: str | None = None) -> Reply:
    error: dict[str, Any] = {"status": status, "message": message}
    if reason is not None:
        error["reason"] = reason
    return _ok(status, {"error": error})
