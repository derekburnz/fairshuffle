"""Turns a shuffled order into the Spotify writes that produce it, before any call is made.

There are two ways to write a new order (D12):

- Fast (the default): replace the playlist with the first 100 URIs, then add the rest 100 at a
  time. About 5 calls for 500 songs. Every entry is written fresh, so "date added" and "added
  by" reset, and anything without a URI Spotify accepts is lost: local files (the Web API can't
  add them) and items Spotify no longer has (it sends no URI). The app asks first (P4-2).
- Keep order (a setting): move one entry at a time with reorder calls, which keeps every entry
  as it is. For each position from the top, the entry that belongs there is moved up from
  wherever it sits now. At most n - 1 moves, and none for an entry already in place.

Both plans are plain data and pure functions, so the tests replay them on a simulated playlist
and check the result is exactly the target before anything touches Spotify.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fairshuffle.spotify.models import PlaylistItem

MAX_URIS_PER_WRITE = 100  # replace and add both take at most 100 URIs per request


@dataclass(frozen=True)
class Replace:
    """PUT /playlists/{id}/items with uris: the playlist becomes exactly these, in order."""

    uris: tuple[str, ...]


@dataclass(frozen=True)
class Append:
    """POST /playlists/{id}/items with uris: these go on the end, in order."""

    uris: tuple[str, ...]


@dataclass(frozen=True)
class Move:
    """PUT /playlists/{id}/items with range_start and insert_before (range_length 1): the entry at
    range_start moves to just before the entry now at insert_before."""

    range_start: int
    insert_before: int


def fast_mode_losses(items: Sequence[PlaylistItem]) -> int:
    """How many entries a fast shuffle would remove: local files and items with no URI."""
    return sum(1 for item in items if not _writable(item))


def fast_plan(target: Sequence[PlaylistItem]) -> list[Replace | Append]:
    """Replace with the first 100 of target, then add the rest 100 at a time.

    Entries the API can't write (fast_mode_losses) are left out, so the caller must have asked
    the user first. An order with nothing writable in it would empty the playlist, so that is
    refused: such a playlist can only be shuffled in keep-order mode.
    """
    uris = [item.uri for item in target if _writable(item) and item.uri is not None]
    if not uris:
        raise ValueError("Nothing in this order can be written in fast mode.")
    chunks = [
        tuple(uris[start : start + MAX_URIS_PER_WRITE])
        for start in range(0, len(uris), MAX_URIS_PER_WRITE)
    ]
    return [Replace(chunks[0]), *(Append(chunk) for chunk in chunks[1:])]


def reorder_plan(target: Sequence[int]) -> list[Move]:
    """The moves that turn a playlist in its current order into target.

    target lists the current positions in their new order: target[0] is the position of the
    entry that should end up first. Positions, not URIs, name the entries, because the same song
    can be in a playlist twice and local or missing items may share or lack a URI.
    """
    if sorted(target) != list(range(len(target))):
        raise ValueError("target must hold each current position exactly once.")
    current = list(range(len(target)))  # current[k] is the entry now at position k
    moves: list[Move] = []
    for i, wanted in enumerate(target):
        at = current.index(wanted, i)  # everything above i is already in its final place
        if at == i:
            continue
        moves.append(Move(range_start=at, insert_before=i))
        current.insert(i, current.pop(at))
    return moves


def _writable(item: PlaylistItem) -> bool:
    return item.uri is not None and not item.is_local
