"""Reads the signed-in user's playlists from the Spotify Web API.

GET /me/playlists returns the playlists the user owns and the ones they follow, 50 at most per
page, with a "next" link to the following page (Spotify docs, re-checked 2026-10-21). FairShuffle
can only reorder playlists the user owns or collaborates on, so only those are kept.

Playlist names are the user's own content: they are shown in the app but never logged.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.models import Playlist
from fairshuffle.spotify.profile import clean_text

PAGE_SIZE = 50  # the most Spotify allows per page
MAX_PAGES = 2_000  # Spotify's largest offset (100,000) in pages of 50: a loop guard, never reached

_ID = re.compile(r"[0-9A-Za-z]{1,64}")  # Spotify IDs are base62; anything else never reaches a path

log = logging.getLogger(__name__)


def list_editable_playlists(client: SpotifyClient, user_id: str) -> list[Playlist]:
    """Every playlist user_id owns or collaborates on, in the order Spotify lists them."""
    playlists: list[Playlist] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    next_url: str | None = None
    for _ in range(MAX_PAGES):
        if next_url is None:
            page = client.get("/me/playlists", params={"limit": PAGE_SIZE})
        else:
            page = client.get_url(next_url)
        for entry in _items(page):
            playlist = _playlist(entry)
            if playlist is None or playlist.id in seen_ids:
                continue
            if playlist.owner_id == user_id or playlist.collaborative:
                seen_ids.add(playlist.id)
                playlists.append(playlist)
        link = page.get("next")
        if not isinstance(link, str) or link in seen_pages:
            break
        seen_pages.add(link)
        next_url = link
    log.info("Found %d playlists FairShuffle can reorder", len(playlists))
    return playlists


def _items(page: dict[str, Any]) -> list[Any]:
    items = page.get("items")
    return items if isinstance(items, list) else []


def _playlist(entry: Any) -> Playlist | None:
    """A Playlist from one entry of the list, or None when the entry is missing or malformed."""
    if not isinstance(entry, dict):
        return None
    playlist_id = entry.get("id")
    owner = entry.get("owner")
    owner_id = owner.get("id") if isinstance(owner, dict) else None
    snapshot_id = entry.get("snapshot_id")
    if not (isinstance(playlist_id, str) and _ID.fullmatch(playlist_id)):
        return None
    if not isinstance(owner_id, str) or not isinstance(snapshot_id, str) or not snapshot_id:
        return None
    name = entry.get("name")
    return Playlist(
        id=playlist_id,
        name=(clean_text(name) if isinstance(name, str) else None) or "",
        owner_id=owner_id,
        collaborative=entry.get("collaborative") is True,
        snapshot_id=snapshot_id,
        item_count=_item_count(entry.get("items")),
    )


def _item_count(items: Any) -> int | None:
    """items.total, or None. The deprecated tracks.total is never read."""
    total = items.get("total") if isinstance(items, dict) else None
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        return None
    return total
