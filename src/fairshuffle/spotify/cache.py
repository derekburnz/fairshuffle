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
from collections import OrderedDict
from dataclasses import dataclass

from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.models import Playlist, PlaylistItem
from fairshuffle.spotify.playlists import read_playlist_items

MAX_PLAYLISTS = 50  # the least recently used playlist is forgotten past this many

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Entry:
    snapshot_id: str
    items: tuple[PlaylistItem, ...]


class PlaylistItemsCache:
    """Playlist items by playlist ID, each kept with the snapshot_id it was read at.

    Safe to share between worker threads. Two threads asking for the same playlist at once may
    both read it; the second answer simply replaces the first.
    """

    def __init__(self, max_playlists: int = MAX_PLAYLISTS) -> None:
        self._max = max_playlists
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def items(self, client: SpotifyClient, playlist: Playlist) -> tuple[PlaylistItem, ...]:
        """The playlist's items: from memory if its snapshot_id is unchanged, else from Spotify."""
        with self._lock:
            entry = self._entries.get(playlist.id)
            if entry is not None and entry.snapshot_id == playlist.snapshot_id:
                self._entries.move_to_end(playlist.id)
                log.info("Playlist unchanged since it was last read; no item calls needed")
                return entry.items
        items = tuple(read_playlist_items(client, playlist.id))
        with self._lock:
            self._entries[playlist.id] = _Entry(playlist.snapshot_id, items)
            self._entries.move_to_end(playlist.id)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        return items

    def forget(self, playlist_id: str) -> None:
        """Drop one playlist, for example after FairShuffle itself has reordered it."""
        with self._lock:
            self._entries.pop(playlist_id, None)

    def clear(self) -> None:
        """Drop everything, for example at sign-out, so another account never sees it."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
