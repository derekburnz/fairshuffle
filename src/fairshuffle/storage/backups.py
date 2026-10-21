"""A copy of a playlist's order, saved before every shuffle so it can be undone (D13).

Before the first write to Spotify the shuffle saves every entry's URI, kind and local-file flag
to %APPDATA%\\FairShuffle\\backups, reads the file back and checks it matches. Only then does
it change the playlist. A shuffle cut off halfway, or one the user doesn't like, can then be put
back with Undo.

A backup holds the playlist ID, its snapshot_id when it was read, the time and the entries. No
token, no name and nothing about the account: a playlist ID and its song list are all it needs.
Local file URIs carry artist, album and title, so the files stay on this PC's user profile and
are never logged.

Each playlist keeps its newest KEEP_PER_PLAYLIST backups, so a second shuffle of a playlist
that was cut off halfway doesn't destroy the order from before the first.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fairshuffle.spotify.models import PlaylistItem
from fairshuffle.storage.paths import backup_dir

FORMAT = 1
KEEP_PER_PLAYLIST = 10
MAX_FILE_BYTES = 50_000_000  # far above the largest playlist (10,000 items of 1,000 characters)
MAX_URI_LENGTH = 1_000  # as spotify/playlists.py: local file URIs can be long
_ID = re.compile(r"[0-9A-Za-z]{1,64}")  # a Spotify ID never holds a path separator or a dot
_SNAPSHOT = re.compile(r"[\x21-\x7e]{1,256}")  # as spotify/playlists.py
_STAMP = "%Y%m%dT%H%M%S%fZ"

log = logging.getLogger(__name__)


class BackupError(Exception):
    """A backup couldn't be saved or read. The shuffle must not start without one."""


@dataclass(frozen=True)
class Backup:
    playlist_id: str
    snapshot_id: str
    saved_at: datetime
    items: tuple[PlaylistItem, ...]


def save(playlist_id: str, snapshot_id: str, items: Sequence[PlaylistItem]) -> Backup:
    """Save the order, read it back and check it, then drop the oldest beyond the keep limit.

    Raises BackupError if any step fails; nothing has touched Spotify at that point, so the
    caller stops and says the shuffle couldn't start.
    """
    _check_id(playlist_id)
    # Positions are the order itself: number them from 0 so the file reads back the same.
    numbered = tuple(replace(item, position=n) for n, item in enumerate(items))
    backup = Backup(playlist_id, snapshot_id, datetime.now(UTC), numbered)
    folder = backup_dir()
    path = folder / f"{playlist_id}-{backup.saved_at.strftime(_STAMP)}.json"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _write_atomically(path, json.dumps(_to_json(backup), ensure_ascii=False))
        if load(path) != backup:
            path.unlink(missing_ok=True)  # never leave a wrong copy for Undo to find
            raise BackupError("The backup didn't read back the same.")
    except OSError:
        # The OS message can quote the path, which holds the Windows user name: log the type only.
        log.warning("Saving a backup failed")
        raise BackupError("FairShuffle couldn't save a backup, so nothing was changed.") from None
    _prune(playlist_id)
    log.info("Saved a backup of %d items", len(backup.items))
    return backup


def newest(playlist_id: str) -> Backup | None:
    """The newest backup of this playlist that reads cleanly, or None."""
    _check_id(playlist_id)
    for path in reversed(_files(playlist_id)):
        try:
            return load(path)
        except BackupError:
            continue  # a damaged file: try the one before it
    return None


def load(path: Path) -> Backup:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("too big")
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        return _from_json(data)
    except OSError, ValueError, KeyError, TypeError:
        raise BackupError("A backup file couldn't be read.") from None


def restore_target(backup: Backup, current: Sequence[PlaylistItem]) -> list[int] | None:
    """The current positions in the backup's order, for a keep-order Undo, or None.

    Entries are matched by URI, the first unused one each time, so duplicates come back in their
    old order. Items with no URI match each other, since reorder moves them by position. None
    when the playlist no longer holds exactly the backup's entries (something was added or
    removed since), because a reorder alone can't put that back.
    """
    if len(current) != len(backup.items):
        return None
    free: dict[str | None, list[int]] = {}
    for position, item in enumerate(current):
        free.setdefault(item.uri, []).append(position)
    target: list[int] = []
    for item in backup.items:
        positions = free.get(item.uri)
        if not positions:
            return None
        target.append(positions.pop(0))
    return target


def _files(playlist_id: str) -> list[Path]:
    """This playlist's backups, oldest first (the stamp sorts by time)."""
    folder = backup_dir()
    if not folder.is_dir():
        return []
    pattern = re.compile(re.escape(playlist_id) + r"-\d{8}T\d{12}Z\.json")
    return sorted(path for path in folder.iterdir() if pattern.fullmatch(path.name))


def _prune(playlist_id: str) -> None:
    for path in _files(playlist_id)[:-KEEP_PER_PLAYLIST]:
        try:
            path.unlink()
        except OSError:
            log.warning("Removing an old backup failed")


def _write_atomically(path: Path, text: str) -> None:
    """Write to a temp file in the same folder, then swap it in, so a crash never leaves half a
    backup under the real name."""
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    os.close(handle)  # reopened by name below, so the handle can't leak if opening fails
    try:
        with open(temp_name, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _check_id(playlist_id: str) -> None:
    if not _ID.fullmatch(playlist_id):
        raise ValueError("That isn't a Spotify playlist ID.")


def _to_json(backup: Backup) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "playlist_id": backup.playlist_id,
        "snapshot_id": backup.snapshot_id,
        "saved_at": backup.saved_at.isoformat(),
        "items": [
            {"uri": item.uri, "kind": item.kind, "is_local": item.is_local} for item in backup.items
        ],
    }


def _from_json(data: Any) -> Backup:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("unknown backup format")
    playlist_id, snapshot_id = data["playlist_id"], data["snapshot_id"]
    if not isinstance(playlist_id, str) or not _ID.fullmatch(playlist_id):
        raise ValueError("bad playlist ID")
    if not isinstance(snapshot_id, str) or not _SNAPSHOT.fullmatch(snapshot_id):
        raise ValueError("bad snapshot_id")
    if not isinstance(data["items"], list):
        raise ValueError("bad backup")
    saved_at = datetime.fromisoformat(data["saved_at"])
    items = tuple(_item(position, entry) for position, entry in enumerate(data["items"]))
    return Backup(playlist_id, snapshot_id, saved_at, items)


def _item(position: int, entry: Any) -> PlaylistItem:
    uri, kind, is_local = entry["uri"], entry["kind"], entry["is_local"]
    if not (uri is None or _is_spotify_uri(uri)):
        raise ValueError("bad uri")
    if kind not in ("track", "episode", None) or not isinstance(is_local, bool):
        raise ValueError("bad item")
    return PlaylistItem(position=position, uri=uri, kind=kind, is_local=is_local)


def _is_spotify_uri(uri: Any) -> bool:
    return (
        isinstance(uri, str)
        and uri.startswith("spotify:")
        and len(uri) <= MAX_URI_LENGTH
        and uri.isprintable()
    )
