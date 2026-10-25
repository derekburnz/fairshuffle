"""Runs a shuffle (or an Undo) against Spotify, step by step, on a worker thread.

A shuffle goes:

1. Read the playlist's snapshot_id, then its items (from the cache when unchanged), then the
   snapshot_id again. The items call carries no snapshot_id, so if the two differ the playlist
   changed while it was being read, and the run stops before writing anything.
2. Shuffle with Fisher-Yates and build the plan for the chosen mode (D12). In fast mode, if the
   plan would remove local files or items Spotify sends no URI for, stop and let the app ask the
   user first (P4-2), unless they already said "shuffle fast anyway".
3. Save the backup and check it reads back (D13). No backup, no shuffle.
4. Send the writes, pacing them and reporting progress. Retry-After waits happen inside
   SpotifyClient. In keep-order mode each move carries the latest snapshot_id, cancel is honoured
   between moves (every song is still there, just partly shuffled), and every CHECK_EVERY moves
   the playlist is read and compared with the order our moves should have made, to catch
   another editor (P4-6). The snapshot_id isn't used for that: on the real API the one GET
   /playlists/{id} returns never matched the one the last reorder returned (live test, #31).
   An edit made after the last check is caught by the read-back in step 5. Fast mode is a
   handful of calls and can't
   stop halfway without leaving the playlist short, so cancel only works before its first write.
5. Read the playlist back and verify it holds the same songs in the planned order.

Any failure once a write may have reached Spotify (including SpotifyUnavailable with
may_have_applied) ends the run with changed=True, so the app offers Undo from the backup rather
than guessing what landed. The cache forgets the playlist after any write.

Undo puts the newest backup back the same way, in the mode the user has chosen, without saving
a new backup: if Undo itself is cut off, the backup it was restoring is still the newest one.
A fast Undo replaces the whole playlist, so it asks first (NEEDS_CONFIRM) when that would remove
anything there now: songs added since the shuffle, local files or items with no URI.

Everything before the first write only reads, so a failure there reports changed=False. Plans
are built before the first write too, so a bug in one can't be mistaken for a partial write.

Nothing here touches Qt, so it is tested with plain threads and the fake Spotify. The engine is
always called without a random source here, so it uses secrets.SystemRandom.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto

from fairshuffle.auth.oauth import SignInRequired, TokenError
from fairshuffle.auth.token_store import TokenStoreError
from fairshuffle.shuffle.engine import shuffled
from fairshuffle.shuffle.planner import (
    Append,
    Move,
    Replace,
    fast_mode_losses,
    fast_plan,
    reorder_plan,
    writable_uris,
)
from fairshuffle.shuffle.verify import Verdict, verify
from fairshuffle.spotify.cache import PlaylistItemsCache
from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.errors import SpotifyError, SpotifyUnavailable
from fairshuffle.spotify.models import Playlist, PlaylistItem
from fairshuffle.spotify.playlists import read_playlist_items
from fairshuffle.storage import backups
from fairshuffle.storage.backups import BackupError

CHECK_EVERY = 50  # keep-order mode reads the playlist back after this many moves
PACE_SECONDS = 0.05  # at most 20 writes a second; Spotify publishes no limit, so stay gentle
_SNAPSHOT = re.compile(r"[\x21-\x7e]{1,256}")  # as spotify/playlists.py

UNEXPECTED = "Something went wrong during the shuffle. Check the log if it repeats."
CHANGED_WHILE_READING = (
    "The playlist changed while FairShuffle was reading it, so nothing was changed. Try again."
)
CHANGED_ELSEWHERE = (
    "The playlist was changed somewhere else during the shuffle, so FairShuffle stopped. "
    "Undo puts back the order from before."
)
PARTLY_DONE = "The playlist may be partly shuffled. Undo puts back the order from before."
_SPOTIFY_ERRORS = (SignInRequired, SpotifyError, TokenError, TokenStoreError)

log = logging.getLogger(__name__)

Progress = Callable[[int, int], None]


class Mode(Enum):
    FAST = auto()  # replace, then add: seconds; resets "date added", drops local files (D12)
    KEEP_ORDER = auto()  # reorder one entry at a time: slower; keeps everything


class Result(Enum):
    DONE = auto()
    NOTHING_TO_DO = auto()  # fewer than two entries
    NEEDS_CONFIRM = auto()  # fast mode would remove `losses` entries; ask first (P4-2)
    CANCELLED = auto()
    CHANGED_ELSEWHERE = auto()  # another editor changed the playlist
    NOT_VERIFIED = auto()  # all writes went through but the read-back doesn't match
    FAILED = auto()


@dataclass(frozen=True)
class Outcome:
    """How a run ended. changed is True when the playlist may differ from before, so the app
    should offer Undo. message is FairShuffle's own text, safe to show and log."""

    result: Result
    changed: bool = False
    message: str = ""
    losses: int = 0
    verdict: Verdict | None = None


@dataclass
class Options:
    """What the caller can tune. Tests shrink the pace and the check interval."""

    # The user chose "shuffle fast anyway" after being told this many would go. A rerun that
    # would now remove more (someone added songs in between) asks again.
    allowed_losses: int = 0
    cancel: threading.Event | None = None
    progress: Progress | None = None
    check_every: int = CHECK_EVERY
    pace: float = PACE_SECONDS
    sleep: Callable[[float], None] = time.sleep


class _Stop(Exception):
    """Ends a run early with an Outcome."""

    def __init__(self, outcome: Outcome) -> None:
        super().__init__(outcome.result.name)
        self.outcome = outcome


def shuffle_playlist(
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    playlist_id: str,
    mode: Mode,
    options: Options | None = None,
) -> Outcome:
    """Shuffle one playlist. Runs on a worker thread; never raises."""
    options = options or Options()
    return _guarded(lambda: _shuffle(client, cache, playlist_id, mode, options), cache, playlist_id)


def undo_last_shuffle(
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    playlist_id: str,
    mode: Mode,
    options: Options | None = None,
) -> Outcome:
    """Put the newest backup of this playlist back. Runs on a worker thread; never raises."""
    options = options or Options()
    return _guarded(lambda: _undo(client, cache, playlist_id, mode, options), cache, playlist_id)


def _shuffle(
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    playlist_id: str,
    mode: Mode,
    options: Options,
) -> Outcome:
    snapshot, items = _read_steady(client, cache, playlist_id)
    if len(items) < 2:
        return Outcome(Result.NOTHING_TO_DO, message="There is nothing to shuffle yet.")
    order = shuffled(range(len(items)))  # no random source passed: secrets.SystemRandom
    target = [items[k] for k in order]
    _check_losses(items, mode, options)
    _cancelled_before_writing(options)
    try:
        backups.save(playlist_id, snapshot, items)
    except BackupError as error:
        return Outcome(Result.FAILED, message=str(error))
    return _write(client, cache, playlist_id, mode, snapshot, items, target, order, options)


def _undo(
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    playlist_id: str,
    mode: Mode,
    options: Options,
) -> Outcome:
    backup = backups.newest(playlist_id)
    if backup is None:
        return Outcome(Result.FAILED, message="There is no backup of this playlist to put back.")
    snapshot, current = _read_steady(client, cache, playlist_id)
    target = list(backup.items)
    order: list[int] = []
    if mode is Mode.KEEP_ORDER:
        restored = backups.restore_target(backup, current)
        if restored is None:
            return Outcome(
                Result.FAILED,
                message="Songs were added or removed since the shuffle, so keep-order mode "
                "can't put the old order back. Fast mode can, but it removes any song added "
                "since.",
            )
        order = restored
    else:
        _check_undo_losses(current, target, options)
    _cancelled_before_writing(options)
    outcome = _write(client, cache, playlist_id, mode, snapshot, current, target, order, options)
    left_out = fast_mode_losses(target) if mode is Mode.FAST else 0
    if outcome.result is Result.DONE and left_out:
        note = f"{left_out} local files or songs Spotify no longer has couldn't be put back."
        return replace(outcome, message=f"{outcome.message} {note}".strip())
    return outcome


def _write(
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    playlist_id: str,
    mode: Mode,
    snapshot: str,
    items: Sequence[PlaylistItem],
    target: Sequence[PlaylistItem],
    order: Sequence[int],
    options: Options,
) -> Outcome:
    """Send the plan, then verify. order is used in keep-order mode, target in fast mode."""
    path = f"/playlists/{playlist_id}/items"
    # Both plans are built before anything is sent, so a bug in one changes nothing.
    plan: Sequence[Replace | Append | Move]
    if mode is Mode.FAST:
        plan = fast_plan(target)
        expected = [uri for write in plan if not isinstance(write, Move) for uri in write.uris]
    else:
        plan = reorder_plan(order)
        expected = [items[k].uri for k in order]
    now = [item.uri for item in items]  # keep-order: the order our moves have made so far
    landed = 0  # writes Spotify confirmed
    try:
        for write in plan:
            if isinstance(write, Move):
                snapshot = _move(client, playlist_id, path, write, snapshot, now, landed, options)
                # reorder_plan only moves entries up (insert_before < range_start), so this
                # pop-then-insert is exactly what Spotify does with the move.
                now.insert(write.insert_before, now.pop(write.range_start))
            else:
                _paced(options)
                if isinstance(write, Replace):
                    client.put(path, {"uris": list(write.uris)})
                else:
                    client.post(path, {"uris": list(write.uris)})
            landed += 1
            _report(options, landed, len(plan))
    except SpotifyUnavailable as error:
        return _after_failure(cache, playlist_id, landed > 0 or error.may_have_applied, error)
    except _SPOTIFY_ERRORS as error:
        return _after_failure(cache, playlist_id, landed > 0, error)
    except _Stop:
        cache.forget(playlist_id)
        raise
    except Exception as error:  # a bug of ours mid-write: a write may have gone out
        return _unexpected(cache, playlist_id, error, changed=True)
    cache.forget(playlist_id)
    if not landed:
        return Outcome(Result.DONE, message="The playlist was already in that order.")
    try:
        verdict = verify(expected, read_playlist_items(client, playlist_id))
    except _SPOTIFY_ERRORS as error:  # the writes landed, only the check failed
        return _after_failure(cache, playlist_id, True, error)
    except Exception as error:
        return _unexpected(cache, playlist_id, error, changed=True)
    if not verdict.ok:
        log.warning(
            "Read-back after the shuffle didn't match: %d missing, %d extra, in order %s",
            verdict.missing,
            verdict.extra,
            verdict.in_order,
        )
        return Outcome(
            Result.NOT_VERIFIED,
            changed=True,
            message="The playlist doesn't look as planned. Undo puts back the order from before.",
            verdict=verdict,
        )
    log.info("Shuffle done and verified (%d writes)", landed)
    return Outcome(Result.DONE, changed=True, verdict=verdict)


def _move(
    client: SpotifyClient,
    playlist_id: str,
    path: str,
    move: Move,
    snapshot: str,
    now: Sequence[str | None],
    landed: int,
    options: Options,
) -> str:
    """Send one reorder and return the new snapshot_id. now is the order before this move."""
    if options.cancel is not None and options.cancel.is_set():
        raise _Stop(Outcome(Result.CANCELLED, changed=landed > 0, message=_cancelled(landed)))
    if landed and landed % options.check_every == 0:
        _paced(options)  # the check's reads count against the rate limit too
        found = [item.uri for item in read_playlist_items(client, playlist_id)]
        if found != list(now):
            raise _Stop(Outcome(Result.CHANGED_ELSEWHERE, changed=True, message=CHANGED_ELSEWHERE))
    _paced(options)
    reply = client.put(
        path,
        {
            "range_start": move.range_start,
            "insert_before": move.insert_before,
            "range_length": 1,
            "snapshot_id": snapshot,
        },
    )
    new_snapshot = reply.get("snapshot_id")
    if not isinstance(new_snapshot, str) or not _SNAPSHOT.fullmatch(new_snapshot):
        raise SpotifyUnavailable("Spotify sent a reply FairShuffle doesn't understand.", True)
    return new_snapshot


def _read_steady(
    client: SpotifyClient, cache: PlaylistItemsCache, playlist_id: str
) -> tuple[str, tuple[PlaylistItem, ...]]:
    """The playlist's snapshot_id and items, checked unchanged across the read."""
    before = _snapshot(client, playlist_id)
    playlist = Playlist(
        id=playlist_id,
        name="",
        owner_id="",
        collaborative=False,
        snapshot_id=before,
        item_count=None,
    )
    items = cache.items(client, playlist)
    if _snapshot(client, playlist_id) != before:
        cache.forget(playlist_id)
        raise _Stop(Outcome(Result.CHANGED_ELSEWHERE, message=CHANGED_WHILE_READING))
    return before, items


def _snapshot(client: SpotifyClient, playlist_id: str) -> str:
    # No fields filter: the docs' fields examples still use the old names (Rule 4), and
    # snapshot_id is a top-level field of the full reply anyway.
    reply = client.get(f"/playlists/{playlist_id}")
    snapshot = reply.get("snapshot_id")
    if not isinstance(snapshot, str) or not _SNAPSHOT.fullmatch(snapshot):
        raise SpotifyUnavailable("Spotify sent a reply FairShuffle doesn't understand.")
    return snapshot


def _check_losses(items: Sequence[PlaylistItem], mode: Mode, options: Options) -> None:
    if mode is not Mode.FAST:
        return
    losses = fast_mode_losses(items)
    if losses == len(items):
        raise _Stop(
            Outcome(
                Result.FAILED,
                message="Fast mode can't write any of these songs back. Use keep-order mode.",
            )
        )
    if losses > options.allowed_losses:
        raise _Stop(
            Outcome(
                Result.NEEDS_CONFIRM,
                message=f"Fast mode would remove {losses} local files or songs Spotify no longer "
                "has. Keep-order mode keeps them.",
                losses=losses,
            )
        )


def _check_undo_losses(
    current: Sequence[PlaylistItem], backup: Sequence[PlaylistItem], options: Options
) -> None:
    """A fast Undo makes the playlist exactly the backup's writable songs. Count what is there
    now that won't be afterwards: songs added since the shuffle, and local files or items with
    no URI (a backup's own such entries can't be written back either)."""
    restorable = Counter(writable_uris(backup))
    if not restorable:
        raise _Stop(
            Outcome(
                Result.FAILED,
                message="Fast mode can't write any of the backed-up songs back. "
                "Use keep-order mode.",
            )
        )
    kept = sum((Counter(writable_uris(current)) & restorable).values())
    losses = len(current) - kept
    if losses > options.allowed_losses:
        raise _Stop(
            Outcome(
                Result.NEEDS_CONFIRM,
                message=f"Undo in fast mode would remove {losses} songs that are in the playlist "
                "now: songs added since the shuffle, local files or songs Spotify no longer has.",
                losses=losses,
            )
        )


def _cancelled_before_writing(options: Options) -> None:
    if options.cancel is not None and options.cancel.is_set():
        raise _Stop(Outcome(Result.CANCELLED, message="Cancelled. Nothing was changed."))


def _cancelled(landed: int) -> str:
    if not landed:
        return "Cancelled. Nothing was changed."
    return "Cancelled. Every song is still there, partly shuffled. Undo puts back the order."


def _paced(options: Options) -> None:
    if options.pace > 0:
        options.sleep(options.pace)


def _report(options: Options, done: int, total: int) -> None:
    if options.progress is not None:
        options.progress(done, total)


def _after_failure(
    cache: PlaylistItemsCache, playlist_id: str, changed: bool, error: Exception
) -> Outcome:
    cache.forget(playlist_id)
    message = str(error)
    if changed:
        message = f"{message} {PARTLY_DONE}"
    return Outcome(Result.FAILED, changed=changed, message=message)


def _unexpected(
    cache: PlaylistItemsCache, playlist_id: str, error: Exception, changed: bool
) -> Outcome:
    """A bug of ours: a fixed sentence for the user, only the class name in the log."""
    log.error("Shuffle failed (%s)", type(error).__name__)
    cache.forget(playlist_id)
    message = f"{UNEXPECTED} {PARTLY_DONE}" if changed else UNEXPECTED
    return Outcome(Result.FAILED, changed=changed, message=message)


def _guarded(run: Callable[[], Outcome], cache: PlaylistItemsCache, playlist_id: str) -> Outcome:
    """Turn every way a run can end into an Outcome, so the worker thread never raises.

    _write handles every failure from its first write on, so anything that reaches here
    happened while only reading: nothing changed.
    """
    try:
        return run()
    except _Stop as stop:
        return stop.outcome
    except _SPOTIFY_ERRORS as error:
        return Outcome(Result.FAILED, message=str(error))
    except Exception as error:
        return _unexpected(cache, playlist_id, error, changed=False)
