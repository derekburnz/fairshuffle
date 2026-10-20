"""Launching FairShuffle a second time, as a real second process, while a first copy runs."""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from fairshuffle.app import SingleInstance

# What a second launch does up to the point where it decides whether to start: exit code 0 means
# it found the first copy and stepped aside, 1 means it would have started a second icon.
SECOND_LAUNCH = """
import sys
from PySide6.QtCore import QCoreApplication
from fairshuffle.app import SingleInstance

app = QCoreApplication([])
sys.exit(1 if SingleInstance(key=sys.argv[1]).acquire() else 0)
"""


def test_second_process_exits_and_the_first_copy_hears_about_it(
    qapp: QApplication, qtbot: QtBot, instance_key: str
) -> None:
    first = SingleInstance(key=instance_key)
    assert first.acquire()
    second: subprocess.Popen[bytes] | None = None
    try:
        with qtbot.waitSignal(first.activation_requested, timeout=10_000):
            # S603: the command is this test's own Python running a fixed script; no shell.
            second = subprocess.Popen([sys.executable, "-c", SECOND_LAUNCH, instance_key])  # noqa: S603

        assert second.wait(timeout=10) == 0
    finally:
        if second is not None and second.poll() is None:
            second.kill()  # never leave a stray Python process behind if the test fails
            second.wait()
        first.release()
