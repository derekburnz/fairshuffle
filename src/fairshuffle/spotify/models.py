"""Plain data the rest of the app gets from Spotify, so no other module reads Spotify's JSON."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Playlist:
    """One playlist FairShuffle may reorder: owned by the signed-in user or collaborative.

    item_count comes from items.total (tracks.total is deprecated). It is None when Spotify leaves
    it out, which the February 2026 changes allow for playlists the user doesn't own.
    snapshot_id names this exact version of the playlist; it changes whenever the playlist does.
    """

    id: str
    name: str
    owner_id: str
    collaborative: bool
    snapshot_id: str
    item_count: int | None


@dataclass(frozen=True)
class PlaylistItem:
    """One entry of a playlist, at its 0-based position.

    uri is None when Spotify sent no usable item: a song or episode that is no longer available.
    kind is "track" or "episode", or None when unknown. Local files (is_local True) have a
    spotify:local: URI; the Web API can reorder them but never add them back, so a shuffle must
    only ever move items, never rewrite the list.
    """

    position: int
    # A local file's URI holds its artist, album and title, so the URI stays out of repr.
    uri: str | None = field(repr=False)
    kind: str | None
    is_local: bool
