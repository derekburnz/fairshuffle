"""Stand-ins for the account and the thread pool, shared by the playlist UI tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from fairshuffle.spotify.models import Playlist
from fairshuffle.ui.account import AccountState, AccountStatus


class FakeAccount(QObject):
    """Just the parts of AccountController the playlist UI reads."""

    status_changed = Signal(object)

    def __init__(self, signed_in: bool = True) -> None:
        super().__init__()
        self.client: object | None = None
        self.status = AccountStatus(AccountState.SIGNED_OUT)
        if signed_in:
            self.sign_in()

    def sign_in(self, name: str | None = "Fake User") -> None:
        self.client = object()  # the controller only hands it to the (faked) Spotify calls
        self.status = AccountStatus(AccountState.SIGNED_IN, name=name)
        self.status_changed.emit(self.status)

    def sign_out(self) -> None:
        self.client = None
        self.status = AccountStatus(AccountState.SIGNED_OUT)
        self.status_changed.emit(self.status)


class HeldJobs:
    """A runner that keeps each job until the test releases it, on the test's own thread."""

    def __init__(self) -> None:
        self.jobs: list[tuple[Callable[[], Any], Callable[[Any], None]]] = []

    def __call__(self, job: Callable[[], Any], done: Callable[[Any], None]) -> None:
        self.jobs.append((job, done))

    def release(self, index: int = 0) -> None:
        job, done = self.jobs.pop(index)
        done(job())


def playlist(number: int, name: str | None = None, count: int | None = 10) -> Playlist:
    return Playlist(
        id=f"fakeplaylist{number}",
        name=name if name is not None else f"Fake Playlist {number}",
        owner_id="fakeuser",
        collaborative=False,
        snapshot_id=f"fake-snapshot-{number}",
        item_count=count,
    )
