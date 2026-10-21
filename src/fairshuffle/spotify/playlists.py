"""Reads the signed-in user's playlists and their items from the Spotify Web API.

GET /me/playlists returns the playlists the user owns and the ones they follow, 50 at most per
page, with a "next" link while more pages follow (Spotify docs, re-checked 2026-10-21).
FairShuffle can only reorder playlists the user owns or collaborates on, so only those are kept.

GET /playlists/{id}/items returns a playlist's songs and episodes the same way, 50 per page, and
only for playlists the user owns or collaborates on (403 otherwise, raised as NotOwner).

Playlist names and items are the user's own content: they are shown in the app but never logged.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any

from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.errors import SpotifyUnavailable
from fairshuffle.spotify.models import Playlist, PlaylistItem
from fairshuffle.spotify.profile import clean_text

PAGE_SIZE = 50  # the most Spotify allows per page
MAX_PAGES = 2_000  # Spotify's largest offset (100,000) in pages of 50: a loop guard, never reached
MAX_NAME_LENGTH = 500  # Spotify caps names far below this; a longer one is cut, not kept whole
MAX_URI_LENGTH = 1_000  # local file URIs carry artist, album and title, so they can be long

_ID = re.compile(r"[0-9A-Za-z]{1,64}")  # Spotify IDs are base62; anything else never reaches a path
_SNAPSHOT = re.compile(r"[\x21-\x7e]{1,256}")  # printable ASCII, no spaces or line breaks

log = logging.getLogger(__name__)


def list_editable_playlists(client: SpotifyClient, user_id: str) -> list[Playlist]:
    """Every playlist user_id owns or collaborates on, in the order Spotify lists them."""
    playlists: list[Playlist] = []
    seen_ids: set[str] = set()
    for entry in _entries(client, "/me/playlists"):
        playlist = _playlist(entry)
        if playlist is None or playlist.id in seen_ids:
            continue
        if playlist.owner_id == user_id or playlist.collaborative:
            seen_ids.add(playlist.id)
            playlists.append(playlist)
    log.info("Found %d playlists FairShuffle can reorder", len(playlists))
    return playlists


def read_playlist_items(client: SpotifyClient, playlist_id: str) -> list[PlaylistItem]:
    """Every item of a playlist the user owns or collaborates on, in playlist order.

    Positions count every entry, unavailable ones included, because Spotify's reorder call moves
    items by position: an item FairShuffle can't read still takes up its place.

    The items call carries no snapshot_id, so if the playlist changes between pages the positions
    can drift. The shuffle (M4) must compare the playlist's snapshot_id from GET /playlists/{id}
    before and after reading (P4-06). The docs don't say Spotify refuses a reorder sent with a
    stale snapshot_id, so M4 must not rely on that without checking (Rule 4).
    """
    if not _ID.fullmatch(playlist_id):
        raise ValueError("That isn't a Spotify playlist ID.")
    params = {"additional_types": "track,episode"}
    entries = _entries(client, f"/playlists/{playlist_id}/items", params)
    items = [_playlist_item(position, entry) for position, entry in enumerate(entries)]
    log.info("Read %d playlist items", len(items))
    return items


def _entries(
    client: SpotifyClient, path: str, params: dict[str, Any] | None = None
) -> Iterator[Any]:
    """Each entry of a paged list at path, asking for one page of 50 after another.

    Spotify's "next" link says only whether another page exists; it is never followed. FairShuffle
    asks for the same path with the next offset itself, so a reply can't choose what is fetched
    next or what the log shows. A page without an items list, one that isn't full but claims a
    next page, one that holds more than asked for, or more pages than MAX_PAGES, is refused:
    handing back part of a list could lose songs in a shuffle, and later pages would land at the
    wrong positions.
    """
    for page_number in range(MAX_PAGES):
        query = {**(params or {}), "limit": PAGE_SIZE, "offset": page_number * PAGE_SIZE}
        page = client.get(path, params=query)
        items = page.get("items")
        if not isinstance(items, list):
            raise _not_understood()
        has_next = isinstance(page.get("next"), str) and bool(page["next"])
        if len(items) > PAGE_SIZE or (has_next and len(items) < PAGE_SIZE):
            raise _not_understood()
        yield from items
        if not has_next:
            return
    raise _not_understood()  # still more pages after MAX_PAGES: never hand back part of a list


def _not_understood() -> SpotifyUnavailable:
    return SpotifyUnavailable("Spotify sent a reply FairShuffle doesn't understand.")


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
    if not isinstance(owner_id, str) or not isinstance(snapshot_id, str):
        return None
    if not _SNAPSHOT.fullmatch(snapshot_id):
        return None
    name = entry.get("name")
    return Playlist(
        id=playlist_id,
        name=(clean_text(name, MAX_NAME_LENGTH) if isinstance(name, str) else None) or "",
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


def _playlist_item(position: int, entry: Any) -> PlaylistItem:
    """A PlaylistItem from one entry of the items list. A missing or malformed entry, or one whose
    item Spotify left out, becomes an unavailable item (uri None) so later positions stay right."""
    if not isinstance(entry, dict):
        return PlaylistItem(position=position, uri=None, kind=None, is_local=False)
    item = entry.get("item")  # "track" is the deprecated name for the same object
    kind = item.get("type") if isinstance(item, dict) else None
    uri = item.get("uri") if isinstance(item, dict) else None
    return PlaylistItem(
        position=position,
        uri=uri if _is_spotify_uri(uri) else None,
        kind=kind if kind in ("track", "episode") else None,
        is_local=entry.get("is_local") is True,
    )


def _is_spotify_uri(uri: Any) -> bool:
    return (
        isinstance(uri, str)
        and uri.startswith("spotify:")
        and len(uri) <= MAX_URI_LENGTH
        and uri.isprintable()
    )
