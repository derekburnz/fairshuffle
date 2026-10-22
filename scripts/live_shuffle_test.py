"""Live test of the shuffle against the real Spotify, on the "Shuffle Test" playlist only (#31).

Dev only, run by hand on Derek's PC (P4-5). It writes to Spotify, so it only ever touches one
playlist: the single playlist named exactly "Shuffle Test" that the signed-in user owns. The name
is fixed here on purpose; there is no option to point it anywhere else.

Without --run it only finds the playlist and says how many songs it holds. Nothing is written.
With --run it does 5 fast shuffles, then 5 keep-order shuffles, then one Undo. Each step reads
the playlist back and checks it holds the same songs as at the start, in a new order. Keep-order
runs read the playlist back every 10 moves, so the check that spots another editor runs
against the real API too (P4-6; the first live run showed snapshot_ids can't be used for it).

If a run fails after it may have changed the playlist, the script puts the order from before
that run back at once (keep-order Undo, or fast Undo if songs went missing) and says whether that
verified. The order from before the whole test is in the oldest of the 10 backups kept, so a
second --run pushes it out; fine for a playlist made for testing.

"Exactly" means after the clean-up every playlist name gets on the way in (spotify/playlists.py
strips spaces and invisible characters), so " Shuffle Test " counts too. Only playlists you own
are looked at, and two matches are refused.

It prints counts and results only: no song names, URIs or IDs. FairShuffle must not be running:
both would use the same saved sign-in, and a refresh by one can sign the other out. The script
takes the app's single-instance lock for the whole test, so it refuses to start while the tray
app runs and the tray app can't start meanwhile.

    uv run python scripts/live_shuffle_test.py          # dry run: finds the playlist
    uv run python scripts/live_shuffle_test.py --run    # 10 shuffles and an Undo
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile

from fairshuffle.app import default_instance_key
from fairshuffle.auth.oauth import SignInRequired, SpotifyAuth, TokenError
from fairshuffle.auth.token_store import TokenStoreError
from fairshuffle.config import ConfigError, load_settings
from fairshuffle.shuffle.planner import fast_mode_losses
from fairshuffle.shuffle.runner import (
    Mode,
    Options,
    Outcome,
    Result,
    shuffle_playlist,
    undo_last_shuffle,
)
from fairshuffle.spotify.cache import PlaylistItemsCache
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.errors import SpotifyError
from fairshuffle.spotify.models import Playlist
from fairshuffle.spotify.playlists import list_editable_playlists, read_playlist_items
from fairshuffle.spotify.profile import user_id
from fairshuffle.storage import backups
from fairshuffle.storage.logging_setup import setup_logging

TEST_PLAYLIST = "Shuffle Test"
MAX_SONGS = 100  # one fast write is all or nothing up to 100 songs, so a run can't leave it short
FAST_RUNS = 5
KEEP_ORDER_RUNS = 5
CHECK_EVERY = 10  # small, so even a 30-song keep-order run checks the songs twice

Out = Callable[[str], None]


class SetupError(Exception):
    """The test can't start. The message is safe to print."""


def find_test_playlist(playlists: Sequence[Playlist], owner: str) -> Playlist:
    """The one playlist named exactly TEST_PLAYLIST that owner owns. Anything else is refused."""
    matches = [p for p in playlists if p.name == TEST_PLAYLIST and p.owner_id == owner]
    if not matches:
        raise SetupError(f'No playlist of yours is named exactly "{TEST_PLAYLIST}".')
    if len(matches) > 1:
        raise SetupError(
            f'{len(matches)} of your playlists are named "{TEST_PLAYLIST}". Rename all but one.'
        )
    return matches[0]


def hold_app_lock(lock_dir: Path | None = None) -> QLockFile:
    """Take FairShuffle's own single-instance lock, or refuse: the tray app must not be running.

    Taken directly rather than through SingleInstance, which would ping the running copy.
    """
    folder = lock_dir or Path(QDir.tempPath())
    lock = QLockFile(str(folder / f"{default_instance_key()}.lock"))
    lock.setStaleLockTime(0)  # as the app: only a lock whose process is gone counts as abandoned
    if lock.tryLock(0):
        return lock
    if lock.error() == QLockFile.LockError.LockFailedError:
        raise SetupError("FairShuffle is running. Quit it from the tray first.")
    raise SetupError("Can't check whether FairShuffle is running, so not starting.")


def live_test(
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    playlist_id: str,
    out: Out = print,
    pace: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Run the shuffles and the Undo, stopping at the first one that doesn't check out."""
    start = [item.uri for item in read_playlist_items(client, playlist_id)]
    songs = Counter(start)
    plan = [Mode.FAST] * FAST_RUNS + [Mode.KEEP_ORDER] * KEEP_ORDER_RUNS
    for number, mode in enumerate(plan, start=1):
        before = [item.uri for item in read_playlist_items(client, playlist_id)]
        writes = [0]
        began = clock()
        outcome = shuffle_playlist(
            client, cache, playlist_id, mode, _options(writes, pace, check_every=CHECK_EVERY)
        )
        seconds = clock() - began
        after = [item.uri for item in read_playlist_items(client, playlist_id)]
        problem = _shuffle_problem(outcome, songs, before, after)
        label = f"Run {number:2d} {_name(mode)}"
        if problem:
            out(f"{label}: FAILED ({problem}) {outcome.message}".rstrip())
            if outcome.changed:  # the runner saved this run's backup before writing
                _put_back(client, cache, playlist_id, before, out, pace)
            return False
        out(f"{label}: verified, {len(after)} songs, {writes[0]} writes, {seconds:.1f} s")

    expected = _newest_backup(playlist_id)
    writes = [0]
    began = clock()
    outcome = undo_last_shuffle(client, cache, playlist_id, Mode.KEEP_ORDER, _options(writes, pace))
    seconds = clock() - began
    after = [item.uri for item in read_playlist_items(client, playlist_id)]
    if outcome.result is not Result.DONE or after != expected:
        out(f"Undo: FAILED ({outcome.result.name}) {outcome.message}".rstrip())
        return False
    out(
        f"Undo: verified, back to the order before run {len(plan)}, {writes[0]} writes, "
        f"{seconds:.1f} s"
    )
    out(f"All {len(plan)} shuffles and the Undo verified.")
    return True


def _put_back(
    client: SpotifyClient,
    cache: PlaylistItemsCache,
    playlist_id: str,
    before: list[str | None],
    out: Out,
    pace: float | None,
) -> None:
    """Undo the failed run: keep-order first (keeps everything), fast if songs went missing."""
    if _newest_backup(playlist_id) != before:
        out("Not putting it back: the newest backup isn't the order from before this run.")
        return
    for mode in (Mode.KEEP_ORDER, Mode.FAST):
        outcome = undo_last_shuffle(client, cache, playlist_id, mode, _options([0], pace))
        if outcome.result is Result.DONE:
            break
    after = [item.uri for item in read_playlist_items(client, playlist_id)]
    if after == before:
        out("Put the order from before that run back, and checked it.")
    else:
        out(f"Couldn't put the order back ({outcome.result.name}). The backup is still saved.")


def _options(writes: list[int], pace: float | None, check_every: int | None = None) -> Options:
    def count(done: int, _total: int) -> None:
        writes[0] = done

    options = Options(progress=count)
    if pace is not None:
        options.pace = pace
    if check_every is not None:
        options.check_every = check_every
    return options


def _shuffle_problem(
    outcome: Outcome, songs: Counter[str | None], before: list[str | None], after: list[str | None]
) -> str:
    """Why this run doesn't count as verified, or "" if it does."""
    if outcome.result is not Result.DONE:
        return outcome.result.name
    if outcome.verdict is None or not outcome.verdict.ok:
        return "the runner's read-back didn't match"
    if Counter(after) != songs:
        return "the songs differ from the start of the test"
    if after == before:
        return "the order didn't change"
    return ""


def _newest_backup(playlist_id: str) -> list[str | None]:
    backup = backups.newest(playlist_id)
    if backup is None:
        raise SetupError("No backup was saved, so Undo can't be checked.")
    return [item.uri for item in backup.items]


def _name(mode: Mode) -> str:
    return "fast      " if mode is Mode.FAST else "keep-order"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--run", action="store_true", help="shuffle it (writes to Spotify)")
    args = parser.parse_args(argv)
    try:
        lock = hold_app_lock()
    except SetupError as error:
        print(f"Stopped: {error}")
        return 2
    setup_logging()  # after the lock: the tray app shares this log file, with the same redaction
    try:
        settings = load_settings()
        with new_session() as http:
            auth = SpotifyAuth.from_store(http, settings)
            if auth is None:
                raise SetupError("Not signed in. Sign in from the FairShuffle tray, then quit it.")
            client = SpotifyClient(auth)
            owner = user_id(client)
            if owner is None:
                raise SetupError("Spotify didn't say who is signed in.")
            playlist = find_test_playlist(list_editable_playlists(client, owner), owner)
            items = read_playlist_items(client, playlist.id)
            print(
                f'Found "{TEST_PLAYLIST}": {len(items)} songs, '
                f"{fast_mode_losses(items)} local files or unavailable songs."
            )
            if len(items) > MAX_SONGS:
                raise SetupError(f"More than {MAX_SONGS} songs: is this really the test one?")
            if not args.run:
                print("Dry run: nothing was written. Add --run to shuffle it.")
                return 0
            return 0 if live_test(client, PlaylistItemsCache(), playlist.id) else 1
    except (
        ConfigError,
        SetupError,
        SignInRequired,
        SpotifyError,
        TokenError,
        TokenStoreError,
    ) as e:
        print(f"Stopped: {e}")
        return 2
    except Exception as e:  # a bug of ours: only the class name, as the runner does
        print(f"Stopped: unexpected {type(e).__name__}.")
        return 2
    finally:
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
