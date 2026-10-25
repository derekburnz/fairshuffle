"""An in-memory Spotify that answers FairShuffle's playlist calls the way the Web API reference
describes them (re-checked 2026-10-21, see the spotify-api-notes skill).

It sits behind `responses`, so the real SpotifyClient, its retries and the item reader all run
unchanged; only the far end of the wire is fake. It serves:

- GET /playlists/{id}: the playlist's snapshot_id and items.total;
- GET /playlists/{id}/items: pages of at most 50, with a next link while more follow;
- PUT /playlists/{id}/items: reorder (range_start, insert_before, range_length, snapshot_id) or
  replace (uris, at most 100), never both in one request; 200 with the new snapshot_id;
- POST /playlists/{id}/items: add up to 100 uris at an optional position; 201 with snapshot_id;
- POST /me/playlists: a new empty playlist owned by the user (name required); 201 with its id.

Every change gives the playlist a new snapshot_id. Reorder keeps each entry's added_at; replace
and add stamp a new one, which is how tests tell the two strategies apart. Local files can be
moved but never written by replace or add (Spotify's Playlists page), so those are refused.

Tests can queue faults with fail_next (a 429 with Retry-After, a 5xx, or a dropped connection,
before or after the change is applied), run code before a request with before_request (another
editor changing the playlist mid-shuffle), and read back every call from calls.

Where the docs are silent, the fake says what it does. A reorder with a stale snapshot_id is
applied, because nothing documents a refusal, so shuffle code must check for other editors
itself rather than count on Spotify; reject_stale_snapshot=True makes it refuse instead (400),
so tests can cover both. replies_name_versions_apart=True copies what the real API did in the
live test (#31): a write's reply carries a snapshot_id GET /playlists/{id} never returns.
uris on the query string is refused (the app sends them in the body), and an empty uris list
clears the playlist. Every call must carry a Bearer token, or it gets 401; the
fake doesn't serve the token endpoint, so a test of the refresh-on-401 path needs its own mock.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests
import responses

from fairshuffle.spotify.client import API_BASE

PAGE_SIZE = 50  # GET /playlists/{id}/items gives at most 50 per page
MAX_URIS = 100  # replace and add take at most 100 URIs per request

_PLAYLIST = re.compile(re.escape(API_BASE) + r"/playlists/(?P<id>[^/?]+)(?P<items>/items)?")
_CREATE = re.compile(re.escape(API_BASE) + r"/me/playlists")
_REORDER_FIELDS = ("range_start", "insert_before", "range_length")

Reply = tuple[int, dict[str, str], str]


@dataclass
class Entry:
    """One playlist entry. uri None is an item Spotify no longer has (it sends "item": null)."""

    uri: str | None
    added_at: str
    is_local: bool = False

    @property
    def kind(self) -> str | None:
        if self.uri is None:
            return None
        return "episode" if self.uri.startswith("spotify:episode:") else "track"


@dataclass
class FakePlaylist:
    id: str
    entries: list[Entry]
    editable: bool = True  # False: owned by someone else, so every call answers 403
    version: int = 1
    stale_reads: int = 0  # GET /playlists/{id} reads still to answer with the old snapshot_id
    public: object = True  # as POST /me/playlists set it

    @property
    def snapshot_id(self) -> str:
        return f"fake-snapshot-{self.id}-{self.version}"

    @property
    def uris(self) -> list[str | None]:
        return [entry.uri for entry in self.entries]


@dataclass
class Fault:
    """A reply to send in place of the real one. applied=True makes the change first, as when a
    connection drops after Spotify has already done the work."""

    status: int | None  # None drops the connection
    retry_after: str | None = None
    applied: bool = False
    method: str | None = None  # only fail this method, such as "PUT"; None fails any


@dataclass
class Call:
    method: str
    path: str
    query: dict[str, list[str]]
    body: dict[str, Any] | None


@dataclass
class FakeSpotify:
    """The fake Web API. Create it with a responses.RequestsMock, then add playlists."""

    mock: responses.RequestsMock
    playlists: dict[str, FakePlaylist] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    faults: list[Fault] = field(default_factory=list)
    before_request: Callable[[Call], None] | None = None
    reject_stale_snapshot: bool = False
    # As the real API did in the live test (#31): a write's reply names the new version with a
    # snapshot_id that GET /playlists/{id} never returns. Both still change with every edit.
    replies_name_versions_apart: bool = False
    # As the second live run suggested: right after a change, this many GET /playlists/{id}
    # reads still answer with the version before it, as a lagging read replica would.
    lagging_snapshot_reads: int = 0
    _clock: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    created: list[FakePlaylist] = field(default_factory=list)  # made through POST /me/playlists

    def __post_init__(self) -> None:
        for method in ("GET", "PUT", "POST"):
            self.mock.add_callback(method, _PLAYLIST, callback=self._answer)
        self.mock.add_callback("POST", _CREATE, callback=self._create)

    # Setting up -----------------------------------------------------------------------------

    def add_playlist(
        self,
        playlist_id: str,
        uris: list[str | None],
        *,
        local: frozenset[int] = frozenset(),
        editable: bool = True,
    ) -> FakePlaylist:
        """A playlist holding uris in order. Positions in local become local files."""
        entries = [
            Entry(uri, self._stamp(), is_local=position in local)
            for position, uri in enumerate(uris)
        ]
        playlist = FakePlaylist(playlist_id, entries, editable)
        self.playlists[playlist_id] = playlist
        return playlist

    def fail_next(
        self,
        status: int | None,
        *,
        retry_after: str | None = None,
        applied: bool = False,
        method: str | None = None,
    ) -> None:
        """Answer the next matching request with status (None drops the connection)."""
        self.faults.append(Fault(status, retry_after, applied, method))

    def edit(self, playlist_id: str, uris: list[str | None]) -> None:
        """Another editor (or the Spotify app) changes the playlist: new order, new snapshot."""
        playlist = self.playlists[playlist_id]
        playlist.entries = [Entry(uri, self._stamp()) for uri in uris]
        playlist.version += 1
        playlist.stale_reads = self.lagging_snapshot_reads

    def writes(self) -> list[Call]:
        return [call for call in self.calls if call.method != "GET"]

    # Answering ------------------------------------------------------------------------------

    def _answer(self, request: requests.PreparedRequest) -> Reply:
        url = urlsplit(request.url or "")
        method = (request.method or "GET").upper()
        call = Call(method, url.path, parse_qs(url.query), _body(request))
        self.calls.append(call)
        if not str(request.headers.get("Authorization", "")).startswith("Bearer "):
            return _error(401, "No token provided")
        if self.before_request is not None:
            self.before_request(call)
        match = _PLAYLIST.fullmatch(f"{url.scheme}://{url.netloc}{url.path}")
        if match is None:
            return _error(404, "Not found")
        playlist = self.playlists.get(match["id"])
        if playlist is None:
            return _error(404, "Not found")
        fault = self._take_fault(method)
        if fault is not None and not fault.applied:
            return _fault_reply(fault)
        if not playlist.editable:
            return _error(403, "Forbidden")
        reply = self._route(method, bool(match["items"]), playlist, call)
        if fault is not None and reply[0] < 300:  # applied first, then the reply is lost
            return _fault_reply(fault)
        if fault is not None:  # nothing was applied, so the fault waits for the next request
            self.faults.insert(0, fault)
        return reply

    def _create(self, request: requests.PreparedRequest) -> Reply:
        url = urlsplit(request.url or "")
        body = _body(request)
        self.calls.append(Call("POST", url.path, parse_qs(url.query), body))
        if not str(request.headers.get("Authorization", "")).startswith("Bearer "):
            return _error(401, "No token provided")
        if not body or not isinstance(body.get("name"), str):
            return _error(400, "name is required")
        playlist = self.add_playlist(f"fakecreated{len(self.created) + 1}", [])
        playlist.public = body.get("public", True)
        self.created.append(playlist)
        return _ok(201, {"id": playlist.id, "uri": f"spotify:playlist:{playlist.id}"})

    def _take_fault(self, method: str) -> Fault | None:
        for index, fault in enumerate(self.faults):
            if fault.method in (None, method):
                return self.faults.pop(index)
        return None

    def _route(self, method: str, items: bool, playlist: FakePlaylist, call: Call) -> Reply:
        if method == "GET" and not items:
            return _ok(200, self._playlist_object(playlist))
        if method == "GET":
            return self._page(playlist, call)
        if method == "PUT" and items:
            return self._put(playlist, call)
        if method == "POST" and items:
            return self._add(playlist, call)
        return _error(405, "Method not allowed")

    def _playlist_object(self, playlist: FakePlaylist) -> dict[str, Any]:
        snapshot = playlist.snapshot_id
        if playlist.stale_reads > 0:
            playlist.stale_reads -= 1
            snapshot = f"fake-snapshot-{playlist.id}-{playlist.version - 1}"
        return {
            "id": playlist.id,
            "snapshot_id": snapshot,
            "items": {"total": len(playlist.entries)},
        }

    def _page(self, playlist: FakePlaylist, call: Call) -> Reply:
        try:
            limit = int(call.query.get("limit", ["20"])[0])
            offset = int(call.query.get("offset", ["0"])[0])
        except ValueError:
            return _error(400, "Invalid limit or offset")
        if not 1 <= limit <= PAGE_SIZE or offset < 0:
            return _error(400, "Invalid limit or offset")
        chunk = playlist.entries[offset : offset + limit]
        more = offset + limit < len(playlist.entries)
        next_url = (
            f"{API_BASE}/playlists/{playlist.id}/items?offset={offset + limit}&limit={limit}"
            if more
            else None
        )
        return _ok(
            200,
            {
                "items": [_item_json(entry) for entry in chunk],
                "next": next_url,
                "total": len(playlist.entries),
                "limit": limit,
                "offset": offset,
            },
        )

    def _put(self, playlist: FakePlaylist, call: Call) -> Reply:
        body = call.body or {}
        if "uris" in call.query:
            return _error(400, "FairShuffle sends uris in the body")
        reorder = any(name in body for name in _REORDER_FIELDS)
        if "uris" in body and reorder:
            return _error(400, "Replace and reorder can't be combined")
        if "uris" in body:
            return self._replace(playlist, body["uris"])
        if reorder:
            return self._reorder(playlist, body)
        return _error(400, "Nothing to do")

    def _replace(self, playlist: FakePlaylist, uris: Any) -> Reply:
        problem = _check_uris(uris)
        if problem:
            return _error(400, problem)
        playlist.entries = [Entry(uri, self._stamp()) for uri in uris]
        return self._changed(playlist, 200)

    def _add(self, playlist: FakePlaylist, call: Call) -> Reply:
        body = call.body or {}
        if "uris" in call.query:
            return _error(400, "FairShuffle sends uris in the body")
        uris = body.get("uris")
        problem = _check_uris(uris)
        if problem or not uris:
            return _error(400, problem or "No uris")
        position = body.get("position", len(playlist.entries))
        if not _is_int(position) or not 0 <= position <= len(playlist.entries):
            return _error(400, "Invalid position")
        playlist.entries[position:position] = [Entry(uri, self._stamp()) for uri in uris]
        return self._changed(playlist, 201)

    def _reorder(self, playlist: FakePlaylist, body: dict[str, Any]) -> Reply:
        size = len(playlist.entries)
        start, before, length = (
            body.get("range_start"),
            body.get("insert_before"),
            body.get("range_length", 1),
        )
        if not (_is_int(start) and _is_int(before) and _is_int(length)):
            return _error(400, "range_start, insert_before and range_length must be integers")
        assert isinstance(start, int) and isinstance(before, int) and isinstance(length, int)
        if not (0 <= start < size and 0 <= before <= size and 1 <= length <= size - start):
            return _error(400, "Range out of bounds")
        named = {playlist.snapshot_id, self._reply_snapshot(playlist)}
        if self.reject_stale_snapshot and body.get("snapshot_id") not in named:
            return _error(400, "Stale snapshot_id")
        playlist.entries = reordered(playlist.entries, start, before, length)
        return self._changed(playlist, 200)

    def _changed(self, playlist: FakePlaylist, status: int) -> Reply:
        playlist.version += 1
        playlist.stale_reads = self.lagging_snapshot_reads
        return _ok(status, {"snapshot_id": self._reply_snapshot(playlist)})

    def _reply_snapshot(self, playlist: FakePlaylist) -> str:
        if self.replies_name_versions_apart:
            return f"fake-reply-snapshot-{playlist.id}-{playlist.version}"
        return playlist.snapshot_id

    def _stamp(self) -> str:
        """A distinct added_at for each write, so tests can see which entries were rewritten."""
        return f"2026-01-01T00:00:00.{next(self._clock):06d}Z"


def reordered[T](items: list[T], start: int, before: int, length: int) -> list[T]:
    """Spotify's reorder: move items[start:start + length] to just before the item that was at
    position before. A move into its own range (start <= before <= start + length) changes
    nothing."""
    block = items[start : start + length]
    rest = items[:start] + items[start + length :]
    at = before if before <= start else before - length
    if start <= before <= start + length:
        return list(items)
    return rest[:at] + block + rest[at:]


def _item_json(entry: Entry) -> dict[str, Any]:
    item = None
    if entry.uri is not None:
        item = {"type": entry.kind, "uri": entry.uri, "is_local": entry.is_local}
    return {"added_at": entry.added_at, "is_local": entry.is_local, "item": item}


def _check_uris(uris: Any) -> str | None:
    if not isinstance(uris, list) or not all(isinstance(uri, str) for uri in uris):
        return "uris must be a list of strings"
    if len(uris) > MAX_URIS:
        return "Too many uris"
    if any(uri.startswith("spotify:local:") for uri in uris):
        return "Local files can't be added"
    if not all(uri.startswith(("spotify:track:", "spotify:episode:")) for uri in uris):
        return "Invalid uri"
    return None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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


def _error(status: int, message: str) -> Reply:
    return _ok(status, {"error": {"status": status, "message": message}})


def _fault_reply(fault: Fault) -> Reply:
    if fault.status is None:
        raise requests.ConnectionError("fake dropped connection")
    headers = {"Content-Type": "application/json"}
    if fault.retry_after is not None:
        headers["Retry-After"] = fault.retry_after
    body = {"error": {"status": fault.status, "message": "fake fault"}}
    return fault.status, headers, json.dumps(body)
