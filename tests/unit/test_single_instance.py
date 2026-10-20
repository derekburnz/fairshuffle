"""The single-instance guard: one copy per Windows user, later launches hand over and exit."""

from __future__ import annotations

import getpass
import hashlib
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from fairshuffle.app import SingleInstance, default_instance_key

MakeInstance = Callable[[], SingleInstance]


@pytest.fixture
def make_instance(qapp: QApplication, instance_key: str) -> Iterator[MakeInstance]:
    """Build guards that share the test's key, and release them all afterwards."""
    made: list[SingleInstance] = []

    def make() -> SingleInstance:
        guard = SingleInstance(key=instance_key)
        made.append(guard)
        return guard

    yield make
    for guard in made:
        guard.release()


def test_default_key_is_per_user_and_hides_the_user_name() -> None:
    user_hash = hashlib.sha256(getpass.getuser().encode()).hexdigest()[:16]

    assert default_instance_key() == f"FairShuffle-{user_hash}"


def test_default_key_still_works_without_a_user_name(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_user() -> str:
        raise OSError("no user name available")

    monkeypatch.setattr(getpass, "getuser", no_user)

    assert default_instance_key().startswith("FairShuffle-")


def test_first_copy_wins_and_a_later_copy_does_not(make_instance: MakeInstance) -> None:
    first = make_instance()
    second = make_instance()

    assert first.acquire() is True
    assert second.acquire() is False


def test_a_later_launch_tells_the_first_copy(make_instance: MakeInstance, qtbot: QtBot) -> None:
    first = make_instance()
    assert first.acquire()

    with qtbot.waitSignal(first.activation_requested, timeout=5000):
        assert make_instance().acquire() is False


def test_after_release_a_new_copy_can_start(make_instance: MakeInstance) -> None:
    first = make_instance()
    assert first.acquire()

    first.release()

    assert make_instance().acquire() is True


def test_a_later_launch_gives_up_quickly_if_the_first_copy_is_not_listening_yet(
    make_instance: MakeInstance, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first copy has taken the lock but has not opened its socket yet (it is starting up).
    monkeypatch.setattr(SingleInstance, "_listen", lambda _self: None)
    assert make_instance().acquire()

    assert make_instance().acquire() is False


def test_a_lock_file_left_unreadable_by_a_crash_is_cleared(
    make_instance: MakeInstance,
) -> None:
    guard = make_instance()
    guard.lock_path.write_bytes(b"\x00not a lock file")

    assert guard.acquire() is True
    assert guard.listening


def test_fairshuffle_still_starts_if_the_lock_folder_is_unusable(
    qapp: QApplication, instance_key: str, tmp_path: Path
) -> None:
    not_a_folder = tmp_path / "file.txt"
    not_a_folder.write_text("x")
    guard = SingleInstance(key=instance_key, lock_dir=not_a_folder)

    assert guard.acquire() is True
    assert not guard.listening
    guard.release()


def test_fairshuffle_still_starts_if_the_lock_breaks_after_clearing_a_stale_one(
    make_instance: MakeInstance, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A lock file was cleared, then the folder became unusable before the lock could be retaken.
    guard = make_instance()
    errors = iter([QLockFile.LockError.LockFailedError, QLockFile.LockError.UnknownError])
    monkeypatch.setattr(guard, "_take_lock", lambda: False)
    monkeypatch.setattr(guard, "_notify_first_copy", lambda: False)
    monkeypatch.setattr(guard._lock, "removeStaleLockFile", lambda: True)
    monkeypatch.setattr(guard._lock, "error", lambda: next(errors))

    assert guard.acquire() is True


def test_the_first_copy_still_runs_if_it_cannot_listen(
    make_instance: MakeInstance, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QLocalServer, "listen", lambda _self, _name: False)
    guard = make_instance()

    assert guard.acquire() is True
    assert not guard.listening


def test_launches_close_together_raise_one_notice(
    make_instance: MakeInstance, qtbot: QtBot
) -> None:
    first = make_instance()
    assert first.acquire()
    notices: list[None] = []
    first.activation_requested.connect(lambda: notices.append(None))

    make_instance().acquire()
    make_instance().acquire()
    qtbot.waitUntil(lambda: len(notices) >= 1)
    qtbot.wait(200)

    assert len(notices) == 1


def test_a_launch_after_the_quiet_period_raises_another_notice(
    make_instance: MakeInstance, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SingleInstance, "QUIET_PERIOD", 0.0)
    first = make_instance()
    assert first.acquire()

    for _ in range(2):
        with qtbot.waitSignal(first.activation_requested, timeout=5000):
            make_instance().acquire()
