"""Plain data the rest of the app gets from Spotify, so no other module reads Spotify's JSON."""

from __future__ import annotations

from dataclasses import dataclass


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
