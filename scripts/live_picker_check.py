"""v0.5.0 check: the real picker window, driven from code, on the "Shuffle Test" playlist only.

Builds the same parts FairShuffle.exe builds (account, playlists, shuffles, tray, picker), resumes
the saved sign-in and presses the picker's own buttons: Shuffle (fast), Undo, then Shuffle with
"Keep date added" ticked. Each run must finish DONE and verified; the script then reads the
playlist back itself. Dialogs are answered from code and printed; notifications are recorded and
printed instead of shown. Prints counts and the app's own texts only: no URIs or IDs.

FairShuffle must not be running (same saved sign-in); the script takes the app's lock to make sure.

    uv run python scripts/live_picker_check.py
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QDir, QEventLoop, QLockFile
from PySide6.QtWidgets import QApplication, QWidget

import fairshuffle.ui.picker as picker_module
from fairshuffle import __version__
from fairshuffle.app import create_application, default_instance_key, start_logging
from fairshuffle.spotify.playlists import read_playlist_items
from fairshuffle.spotify.profile import user_id
from fairshuffle.storage import settings
from fairshuffle.ui.account import AccountController, AccountState
from fairshuffle.ui.playlists import PlaylistController, PlaylistsState
from fairshuffle.ui.shuffle import Finished, ShuffleController
from fairshuffle.ui.tray import TrayIcon

TEST_PLAYLIST = "Shuffle Test"
MAX_SONGS = 100
FAST_SECONDS = 120
KEEP_ORDER_SECONDS = 900


class Stop(Exception):
    """The check can't go on. The message is safe to print."""


def hold_app_lock() -> QLockFile:
    lock = QLockFile(str(Path(QDir.tempPath()) / f"{default_instance_key()}.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(0):
        return lock
    if lock.error() == QLockFile.LockError.LockFailedError:
        raise Stop("FairShuffle is running. Quit it from the tray first.")
    raise Stop("Can't check whether FairShuffle is running, so not starting.")


def wait_until(app: QApplication, done: Callable[[], bool], seconds: float, what: str) -> float:
    began = time.monotonic()
    while not done():
        if time.monotonic() - began > seconds:
            raise Stop(f"Timed out after {seconds:.0f} s waiting for {what}.")
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.02)
    return time.monotonic() - began


def main() -> int:
    try:
        lock = hold_app_lock()
    except Stop as error:
        print(f"Stopped: {error}")
        return 2
    try:
        return check()
    except Exception as error:  # noqa: BLE001  # the class only: a traceback shows home paths
        print(f"Stopped: unexpected {type(error).__name__}.")
        return 2
    finally:
        lock.unlock()


def check() -> int:
    """Everything after the lock: build the app's parts, run the steps, print the results."""
    start_logging()
    app = create_application()
    dialogs: list[str] = []
    toasts: list[str] = []
    finished: list[Finished] = []
    progress_seen: list[str] = []
    results: list[tuple[str, bool]] = []

    def answer(
        _parent: QWidget, title: str, text: str, buttons: Sequence[str], default: int
    ) -> int:
        # The local-files question: keep-order is the app's own default and loses nothing.
        pick = 0 if buttons and buttons[0].startswith("Use &keep-order") else len(buttons) - 1
        dialogs.append(f"{title} | {text} | answered {buttons[pick].replace('&', '')!r}")
        return pick

    picker_module.choose = answer  # type: ignore[assignment]

    account = AccountController()
    shuffles = ShuffleController(account)
    playlists = PlaylistController(account)
    tray = TrayIcon(quit_app=app.quit, account=account, playlists=playlists, shuffles=shuffles)
    tray.showMessage = lambda title, text, *_: toasts.append(f"{title} | {text}")  # type: ignore[method-assign]
    shuffles.finished.connect(finished.append)
    keep_before = shuffles.keep_date_added  # put back at the end, whatever happens
    try:
        print(f"FairShuffle {__version__}: resuming the saved sign-in")
        account.start()
        wait_until(app, lambda: account.status.state is not AccountState.CHECKING, 60, "sign-in")
        if account.status.state is not AccountState.SIGNED_IN or account.client is None:
            raise Stop(f"Not signed in (state {account.status.state.name}).")
        client = account.client

        tray.show_picker()
        picker = tray.picker
        if picker is None:
            raise Stop("The picker didn't open.")
        wait_until(app, lambda: playlists.status.state is PlaylistsState.READY, 60, "playlists")
        print(f"Picker: {picker.account_label.text()!r}, status {picker.status_label.text()!r}")

        owner = user_id(client)
        matches = [
            p for p in playlists.status.playlists if p.name == TEST_PLAYLIST and p.owner_id == owner
        ]
        if len(matches) != 1:
            raise Stop(
                f'Expected one playlist named "{TEST_PLAYLIST}" you own, found {len(matches)}.'
            )
        target = matches[0]
        picker.search.setText(TEST_PLAYLIST)
        app.processEvents()
        picker.list.setCurrentIndex(picker.filtered.index(0, 0))
        app.processEvents()
        selected = picker.selected_playlist()
        if selected is None or selected.id != target.id:
            raise Stop("Couldn't select the test playlist in the picker.")
        start = [item.uri for item in read_playlist_items(client, target.id)]
        if len(start) > MAX_SONGS:
            raise Stop(f"More than {MAX_SONGS} songs: is this really the test playlist?")
        songs = Counter(start)
        print(
            f'Selected "{TEST_PLAYLIST}": {len(start)} items. Undo enabled: '
            f"{picker.undo_button.isEnabled()}"
        )

        shuffles.running_changed.connect(
            lambda p: p is not None and progress_seen.append(picker.status_label.text())
        )

        def run(label: str, button: str, seconds: float) -> list[str | None]:
            before_runs = len(finished)
            progress_seen.clear()
            chosen = picker.selected_playlist()
            if chosen is None or chosen.id != target.id:
                raise Stop("The picker's selection is no longer the test playlist.")
            getattr(picker, button).click()
            took = wait_until(
                app,
                # A NEEDS_CONFIRM answered with keep-order starts its rerun inside the same
                # signal, so "running is None" only holds once every run has ended.
                lambda: len(finished) > before_runs and shuffles.running is None,
                seconds,
                label,
            )
            last = finished[-1]
            time.sleep(2)  # Spotify's reads can lag a write by a moment (P4-6)
            after = [item.uri for item in read_playlist_items(client, target.id)]
            outcome = last.outcome
            print(
                f"\n{label}: {outcome.result.name}, changed={outcome.changed}, "
                f"mode={last.mode.name}, verdict={outcome.verdict}, {took:.1f} s"
            )
            if progress_seen:
                print(f"  first progress line: {progress_seen[0]!r}")
                print(f"  last progress line:  {progress_seen[-1]!r}")
            print(f"  cancel shown while running: {bool(progress_seen)}")
            print(f"  status line after: {picker.status_label.text()!r}")
            print(f"  notification: {toasts[-1] if toasts else 'none'}")
            print(f"  read back: {len(after)} items, same songs: {Counter(after) == songs}")
            return after

        # 1. Fast shuffle
        picker.keep_date_added.setChecked(False)
        app.processEvents()
        before = [item.uri for item in read_playlist_items(client, target.id)]
        after = run("1. Shuffle (fast)", "shuffle_button", FAST_SECONDS)
        ok = (
            finished[-1].outcome.result.name == "DONE"
            and Counter(after) == songs
            and after != before
        )
        results.append(("Fast shuffle", ok))
        print(f"  new order: {after != before}  ->  {'PASS' if ok else 'FAIL'}")
        shuffled = after

        # 2. Undo
        print(f"\nUndo enabled before pressing: {picker.undo_button.isEnabled()}")
        after = run("2. Undo", "undo_button", KEEP_ORDER_SECONDS)
        if finished[-1].outcome.result.name == "NEEDS_CONFIRM":
            # The Undo dialog has no keep-order choice, so do what a user would: tick the box
            # and press Undo again.
            print("  Undo asked first; ticking Keep date added and pressing Undo again")
            picker.keep_date_added.setChecked(True)
            app.processEvents()
            after = run("2b. Undo (keep date added)", "undo_button", KEEP_ORDER_SECONDS)
            picker.keep_date_added.setChecked(False)
            app.processEvents()
        ok = finished[-1].outcome.result.name == "DONE" and after == before
        results.append(("Undo", ok))
        print(
            f"  back to the order before step 1: {after == before} (differs from shuffled: "
            f"{after != shuffled})  ->  {'PASS' if ok else 'FAIL'}"
        )

        # 3. Keep date added
        picker.keep_date_added.setChecked(True)
        app.processEvents()
        saved = settings.load().keep_date_added
        print(f"\nKeep date added ticked; saved to settings.json: {saved}")
        before = after
        after = run("3. Shuffle (keep date added)", "shuffle_button", KEEP_ORDER_SECONDS)
        last = finished[-1]
        ok = (
            last.outcome.result.name == "DONE"
            and last.mode.name == "KEEP_ORDER"
            and Counter(after) == songs
            and after != before
            and saved
        )
        results.append(("Keep-date-added shuffle", ok))
        print(f"  new order: {after != before}  ->  {'PASS' if ok else 'FAIL'}")

        # 4. The setting reads back as a new start would see it.
        reread = ShuffleController(account).keep_date_added
        results.append(("Setting saved", reread))
        print(
            f"\n4. A new start sees keep date added = {reread}  ->  {'PASS' if reread else 'FAIL'}"
        )

        print(f"\nDialogs shown: {len(dialogs)}")
        for line in dialogs:
            print(f"  {line}")
        print("\nSummary:")
        for name, passed in results:
            print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        return 0 if all(passed for _, passed in results) else 1
    except Stop as error:
        print(f"Stopped: {error}")
        return 2
    except Exception as error:  # noqa: BLE001  # report the class only, as the app does
        print(f"Stopped: unexpected {type(error).__name__}.")
        return 2
    finally:
        shuffles.shutdown()
        shuffles.set_keep_date_added(keep_before)
        print(f"Keep date added put back to {keep_before}.")
        account.shutdown()
        tray.hide()


if __name__ == "__main__":
    sys.exit(main())
