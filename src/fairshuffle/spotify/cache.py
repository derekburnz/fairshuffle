"""Remembers each playlist's items for as long as the playlist stays the same.

Spotify gives every version of a playlist a snapshot_id, which changes whenever the playlist
does. GET /me/playlists hands back the current snapshot_id of every playlist, so when it matches
the one the items were read at, the items are still right and reading them again (one call per
50 items) would only spend the app's rate limit. The cache lives in memory only: playlist
contents are the user's own data and never go to disk here.
"""

from __future__ import annotations

import logging
import threading
import weakref
from collections import OrderedDict
from dataclasses import dataclass

from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.models import Playlist, PlaylistItem
from fairshuffle.spotify.playlists import read_playlist_items

MAX_PLAYLISTS = 50  # the least recently used playlist is forgotten past this many
MAX_ITEMS = 50_000  # across all playlists: a few MB, about 50 MB at worst; a bigger one isn't kept

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Entry:
    snapshot_id: str
    items: tuple[PlaylistItem, ...]


class PlaylistItemsCache:
    """Playlist items by playlist ID, each kept with the snapshot_id it was read at.

    The Playlist passed in must come from a fresh GET /me/playlists (or GET /playlists/{id}),
    never from the snapshot_id a caller saw before it read the items: the items call carries no
    snapshot_id, so pairing older items with a newer snapshot_id would hand back a stale list.

    The cache belongs to one sign-in. Asked with a different SpotifyClient than last time, it
    drops everything first, so one account never sees another's items. clear() and forget()
    also stop a read already under way from storing what it got.

    Safe to share between worker threads. Two threads asking for the same playlist at once may
    both read it; the second answer simply replaces the first.
    """

    def __init__(self, max_playlists: int = MAX_PLAYLISTS, max_items: int = MAX_ITEMS) -> None:
        if max_playlists < 1 or max_items < 1:
            raise ValueError("The cache must be able to hold at least one playlist and item.")
        self._max_playlists = max_playlists
        self._max_items = max_items
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._item_count = 0
        self._generation = 0  # moves on at every clear, forget or change of sign-in
        self._client: weakref.ref[SpotifyClient] | None = None  # weak: keeps no tokens alive
        self._lock = threading.Lock()

    def items(self, client: SpotifyClient, playlist: Playlist) -> tuple[PlaylistItem, ...]:
        """The playlist's items: from memory if its snapshot_id is unchanged, else from Spotify."""
        with self._lock:
            if self._client is None or self._client() is not client:
                self._drop_all()
                self._client = weakref.ref(client)
            entry = self._entries.get(playlist.id)
            if entry is not None and entry.snapshot_id == playlist.snapshot_id:
                self._entries.move_to_end(playlist.id)
                log.info("Playlist unchanged since it was last read; no item calls needed")
                return entry.items
            generation = self._generation
        items = tuple(read_playlist_items(client, playlist.id))
        with self._lock:
            if generation == self._generation:  # nothing was cleared or forgotten meanwhile
                self._store(playlist, items)
        return items

    def forget(self, playlist_id: str) -> None:
        """Drop one playlist, for example after FairShuffle itself has reordered it. Reads of other
        playlists under way at the time aren't stored either, which only costs a later read."""
        with self._lock:
            self._generation += 1
            self._pop(playlist_id)

    def clear(self) -> None:
        """Drop everything, for example at sign-out, so another account never sees it."""
        with self._lock:
            self._drop_all()
            self._client = None

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _store(self, playlist: Playlist, items: tuple[PlaylistItem, ...]) -> None:
        self._pop(playlist.id)
        if len(items) > self._max_items:
            return  # too big to keep; the next ask reads it again
        self._entries[playlist.id] = _Entry(playlist.snapshot_id, items)
        self._item_count += len(items)
        while len(self._entries) > self._max_playlists or self._item_count > self._max_items:
            self._pop(next(iter(self._entries)))  # the least recently used

    def _pop(self, playlist_id: str) -> None:
        entry = self._entries.pop(playlist_id, None)
        if entry is not None:
            self._item_count -= len(entry.items)

    def _drop_all(self) -> None:
        self._generation += 1
        self._entries.clear()
        self._item_count = 0
