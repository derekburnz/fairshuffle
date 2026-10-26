"""v0.6.0 live check (#117): True Shuffle against the real Spotify app, on "Shuffle Test" only.

Dev only, run by hand on Derek's PC (P6-08). It never writes to a playlist: True Shuffle only
reads "Shuffle Test" and sends player commands to the Spotify app, so Spotify plays sound on
that PC for a minute or two. Steps, each printed with PASS or FAIL:

1. Spotify plays "Shuffle Test" with its own shuffle on, partway into a song (set up by the
   script, as a user would have it).
2. True Shuffle is ticked through the app's own TrueShuffleController: shuffle off, a song list
   playing with no context, the same song on at about the same point.
3. Next, Next, Previous, Pause and Resume in Spotify follow our order.
4. Untick: Spotify's shuffle is back on and "Shuffle Test" plays from the song that was on.
5. Tick again, then play the playlist straight from Spotify: the once-a-minute watch unticks.
6. The reason codes Spotify sends now (undocumented since 2026): a pause while paused and a
   command to a device that doesn't exist.
7. The largest song list one play takes (sets shuffle/session.py MAX_SONGS): lists of the test
   songs repeated, 100 up to 1,000; each must start on its first song and skip to its second.

At the end playback is paused and Spotify's shuffle is put back as it was. Prints counts, timings
and the app's own messages only: no song names, URIs or IDs.

Before running: Spotify open on the PC, signed in to FairShuffle with playback control (tray menu
"Allow playback control..." once, then quit FairShuffle; the script takes the app's lock).

    uv run python scripts/live_true_shuffle_check.py
"""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

from PySide6.QtCore import QDir, QLockFile, QObject, Signal

from fairshuffle.app import create_application, default_instance_key, start_logging
from fairshuffle.auth.oauth import SignInRequired, SpotifyAuth, TokenError
from fairshuffle.auth.token_store import TokenStoreError
from fairshuffle.config import ConfigError, load_settings
from fairshuffle.shuffle import session as true_shuffle
from fairshuffle.shuffle.engine import shuffled
from fairshuffle.shuffle.planner import writable_uris
from fairshuffle.spotify import player
from fairshuffle.spotify.client import SpotifyClient, new_session
from fairshuffle.spotify.errors import SpotifyError
from fairshuffle.spotify.models import Playlist
from fairshuffle.spotify.playlists import list_editable_playlists, read_playlist_items
from fairshuffle.spotify.profile import user_id
from fairshuffle.ui.account import AccountState, AccountStatus
from fairshuffle.ui.true_shuffle import ToggleState, TrueShuffleController

TEST_PLAYLIST = "Shuffle Test"
MAX_TEST_SONGS = 100  # more than this and it probably isn't the test playlist
PROBE_SIZES = (100, 200, 300, 500, 750, 1000)
START_AT_MS = 30_000  # step 1 starts partway into a song, as a listener would be
SETTLE = 2.0  # seconds for Spotify's state to catch up with a command
POLLS = 10  # reads of the player state while waiting for a change
NO_SUCH_DEVICE = "0" * 40


class Stop(Exception):
    """The check can't go on. The message is safe to print."""


@dataclass
class Report:
    emit: Callable[[str], None] = print
    results: list[tuple[str, bool]] = field(default_factory=list)

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.results.append((name, passed))
        self.emit(f"  {'PASS' if passed else 'FAIL'}  {name}{f' ({detail})' if detail else ''}")
        return passed

    def note(self, line: str) -> None:
        self.emit(f"  {line}")

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(passed for _, passed in self.results)


class ScriptAccount(QObject):
    """The parts of AccountController that TrueShuffleController reads, around a ready client."""

    status_changed = Signal(object)

    def __init__(self, client: SpotifyClient) -> None:
        super().__init__()
        self.client: SpotifyClient | None = client
        self.status = AccountStatus(AccountState.SIGNED_IN, playback=True)


def run_now(job: Callable[[], object], done: Callable[[object], None]) -> None:
    """The toggle's runner, on this thread: the script waits for each step anyway."""
    done(job())


def find_test_playlist(playlists: Sequence[Playlist], owner: str) -> Playlist:
    """The one playlist named exactly TEST_PLAYLIST that owner owns. Anything else is refused."""
    matches = [p for p in playlists if p.name == TEST_PLAYLIST and p.owner_id == owner]
    if len(matches) != 1:
        raise Stop(f'Expected one playlist of yours named "{TEST_PLAYLIST}", found {len(matches)}.')
    return matches[0]


def live_check(
    client: SpotifyClient,
    playlist_id: str,
    emit: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    probe_sizes: Sequence[int] = PROBE_SIZES,
) -> Report:
    """Steps 1 to 7 on the playlist with playlist_id. Restores Spotify's shuffle at the end."""
    report = Report(emit)
    songs = writable_uris(read_playlist_items(client, playlist_id))
    if len(songs) < 3:
        raise Stop(f'"{TEST_PLAYLIST}" needs at least 3 songs Spotify can play.')
    if len(songs) > MAX_TEST_SONGS:
        raise Stop(f"More than {MAX_TEST_SONGS} songs: is this really the test one?")
    device = player.controllable_device(client)
    before = player.playback_state(client)
    shuffle_before = before.shuffle if before is not None else False
    context = f"spotify:playlist:{playlist_id}"
    account = ScriptAccount(client)
    toggle = TrueShuffleController(account, runner=run_now)  # type: ignore[arg-type]
    messages: list[str] = []
    toggle.status_changed.connect(lambda status: status.message and messages.append(status.message))

    def state_when(ready: Callable[[player.PlaybackState], bool]) -> player.PlaybackState | None:
        state = None
        for _ in range(POLLS):
            state = player.playback_state(client)
            if state is not None and ready(state):
                return state
            sleep(SETTLE / 4)
        return state

    def song(state: player.PlaybackState | None) -> str | None:
        return state.item.uri if state is not None and state.item is not None else None

    try:
        emit(f'1. Spotify plays "{TEST_PLAYLIST}" ({len(songs)} songs) with its own shuffle on')
        player.set_shuffle(client, True, device.id)
        player.play(
            client, context_uri=context, offset=2, position_ms=START_AT_MS, device_id=device.id
        )
        state = state_when(lambda s: s.context_uri == context and s.item is not None)
        if state is None or state.context_uri != context or not state.shuffle:
            report.check("Spotify is playing the test playlist, shuffle on", False)
            raise Stop("Spotify didn't start the test playlist; is the Spotify app open?")
        report.check("Spotify is playing the test playlist, shuffle on", True)
        on_before, at_before = song(state), state.progress_ms or 0

        emit("2. Tick True Shuffle")
        began = time.monotonic()
        toggle.toggle(True)
        ticked = toggle.status.state is ToggleState.ON
        report.check(
            "True Shuffle turns on", ticked, f"{time.monotonic() - began:.1f} s; {messages[-1]!r}"
        )
        session = toggle.session
        if not ticked or session is None:
            raise Stop("True Shuffle didn't start, so the rest can't run.")
        state = player.playback_state(client)
        report.check("Spotify's shuffle is off", state is not None and not state.shuffle)
        report.check(
            "A song list plays (no playlist context)",
            state is not None and state.context_uri is None,
        )
        report.check("The song that was on carries on", song(state) == on_before)
        progress = state.progress_ms if state is not None else None
        report.check(
            "At about the same point in it",
            progress is not None and at_before - 1_000 <= progress <= at_before + 20_000,
            f"{at_before / 1000:.0f} s before, {(progress or 0) / 1000:.0f} s after",
        )
        report.check("Spotify confirmed it before the toggle said on", session.confirmed)

        emit("3. Next, Next, Previous, Pause and Resume follow our order")
        for expected in (1, 2):
            player.next_track(client, device.id)
            state = state_when(lambda s, n=expected: song(s) == session.order[n])
            report.check(
                f"Next plays song {expected + 1} of our order",
                song(state) == session.order[expected],
            )
        player.previous_track(client, device.id)
        state = state_when(lambda s: song(s) == session.order[1])
        report.check("Previous plays song 2 again", song(state) == session.order[1])
        player.pause(client, device.id)
        sleep(SETTLE)
        player.resume(client, device.id)
        state = state_when(lambda s: s.is_playing)
        report.check(
            "Pause and Resume keep our order",
            state is not None and state.is_playing and true_shuffle.is_ours(state, session),
        )
        on_at_untick = song(state)

        emit("4. Untick True Shuffle")
        toggle.toggle(False)
        state = state_when(lambda s: s.context_uri == context)
        report.check("True Shuffle turns off", toggle.status.state is ToggleState.OFF)
        back = state is not None and state.context_uri == context
        report.check("The test playlist plays again", back)
        report.check("Spotify's shuffle is back on, as it was", state is not None and state.shuffle)
        report.check("From the song that was on", song(state) == on_at_untick)

        if not back:
            raise Stop("Spotify isn't playing the test playlist any more, so the rest can't run.")

        emit("5. Tick again, then pick the playlist in Spotify: the toggle clears itself")
        toggle.toggle(True)
        player.play(client, context_uri=context, offset=0, device_id=device.id)
        sleep(SETTLE)
        toggle.watch_timer.timeout.emit()  # the once-a-minute look, now rather than in a minute
        report.check("The watch unticks True Shuffle", toggle.status.state is ToggleState.OFF)

        emit("6. What Spotify sends back now (reason codes are undocumented)")
        player.pause(client, device.id)
        sleep(SETTLE)
        report.note(f"Pause while paused: {_outcome(lambda: player.pause(client, device.id))}")
        report.note(
            "A command to a device that doesn't exist: "
            f"{_outcome(lambda: player.pause(client, NO_SUCH_DEVICE))}"
        )

        emit("7. The largest song list one play takes")
        largest = 0
        rng = Random()  # noqa: S311  # a test order, not a secret
        for size in probe_sizes:
            order = shuffled(songs, rng)
            uris = [order[index % len(order)] for index in range(size)]
            began = time.monotonic()
            try:
                player.set_shuffle(client, False, device.id)
                player.play(client, uris=uris, device_id=device.id)
            except SpotifyError as error:
                report.note(f"{size} songs: refused ({_described(error)})")
                break
            state = state_when(lambda s, first=uris[0]: song(s) == first and s.is_playing)
            started = song(state) == uris[0] and state is not None and state.is_playing
            took = time.monotonic() - began
            player.next_track(client, device.id)
            state = state_when(lambda s, second=uris[1]: song(s) == second)
            skipped = song(state) == uris[1] and state is not None and state.context_uri is None
            report.note(
                f"{size} songs: starts on the first {started}, skips to the second {skipped}, "
                f"{took:.1f} s to start"
            )
            if not (started and skipped):
                break
            largest = size
        report.check(
            "A song list of at least MAX_SONGS works",
            largest >= true_shuffle.MAX_SONGS,
            f"largest that worked {largest}, MAX_SONGS {true_shuffle.MAX_SONGS}",
        )
    finally:
        toggle.watch_timer.stop()
        for put_back in (
            lambda: player.pause(client, device.id),
            lambda: player.set_shuffle(client, shuffle_before, device.id),
        ):
            with contextlib.suppress(SpotifyError):  # already paused, or Spotify went away
                put_back()
        emit(f"Playback paused; Spotify's shuffle put back to {'on' if shuffle_before else 'off'}.")
    return report


def _outcome(command: Callable[[], None]) -> str:
    try:
        command()
    except SpotifyError as error:
        return _described(error)
    return "accepted"


def _described(error: SpotifyError) -> str:
    return f"{type(error).__name__}, reason {error.reason or 'none'}: {error}"


def hold_app_lock() -> QLockFile:
    lock = QLockFile(str(Path(QDir.tempPath()) / f"{default_instance_key()}.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(0):
        return lock
    if lock.error() == QLockFile.LockError.LockFailedError:
        raise Stop("FairShuffle is running. Quit it from the tray first.")
    raise Stop("Can't check whether FairShuffle is running, so not starting.")


def main() -> int:
    try:
        lock = hold_app_lock()
    except Stop as error:
        print(f"Stopped: {error}")
        return 2
    app = None
    try:
        start_logging()  # after the lock: the tray app shares this log file, same redaction
        app = create_application()  # the toggle's watch timer is a Qt timer
        with new_session() as http:
            auth = SpotifyAuth.from_store(http, load_settings())
            if auth is None:
                raise Stop("Not signed in. Sign in from the FairShuffle tray, then quit it.")
            if not auth.can_control_playback:
                raise Stop(
                    'Pick "Allow playback control..." in the FairShuffle tray menu once, then '
                    "quit FairShuffle and run this again."
                )
            client = SpotifyClient(auth)
            owner = user_id(client)
            if owner is None:
                raise Stop("Spotify didn't say who is signed in.")
            playlist = find_test_playlist(list_editable_playlists(client, owner), owner)
            if playlist.item_count is not None and playlist.item_count > MAX_TEST_SONGS:
                raise Stop(f"More than {MAX_TEST_SONGS} songs: is this really the test one?")
            report = live_check(client, playlist.id)
        print("\nSummary:")
        for name, passed in report.results:
            print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        return 0 if report.passed else 1
    except (ConfigError, Stop, SignInRequired, SpotifyError, TokenError, TokenStoreError) as error:
        print(f"Stopped: {error}")
        return 2
    except KeyboardInterrupt:
        print("Stopped: interrupted.")
        return 2
    except Exception as error:  # noqa: BLE001  # a bug of ours: the class only, as the app does
        print(f"Stopped: unexpected {type(error).__name__}.")
        return 2
    finally:
        if app is not None:
            app.quit()
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
