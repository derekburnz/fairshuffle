"""The True Shuffle toggle (ui/true_shuffle.py) and its tick box in the tray menu."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fakes.ui_fakes import FakeAccount, HeldJobs
from PySide6.QtWidgets import QApplication

from fairshuffle.shuffle import session as true_shuffle
from fairshuffle.spotify.errors import NoActiveDevice, SpotifyError
from fairshuffle.ui import true_shuffle as toggle_module
from fairshuffle.ui.account import UNEXPECTED, AccountState, AccountStatus
from fairshuffle.ui.tray import TRUE_SHUFFLE, TrayIcon
from fairshuffle.ui.true_shuffle import (
    NEEDS_PLAYBACK_SIGN_IN,
    NOT_SIGNED_IN,
    ToggleState,
    ToggleStatus,
    TrueShuffleController,
)


def session(**changes: Any) -> true_shuffle.Session:
    values: dict[str, Any] = {
        "source_id": "fakeplaylist1",
        "order": ("spotify:track:fakesong1", "spotify:track:fakesong2"),
        "original": ("spotify:track:fakesong2", "spotify:track:fakesong1"),
        "skipped": 0,
        "left_for_later": 0,
        "shuffle_was_on": True,
        "device_id": "fake-device-1",
        "confirmed": True,
    }
    values.update(changes)
    return true_shuffle.Session(**values)


class FakeSessions:
    """Stands in for shuffle/session.py: records calls, returns or raises what the test sets."""

    def __init__(self) -> None:
        self.started = 0
        self.stopped: list[true_shuffle.Session] = []
        self.start_result: object = session()
        self.stop_result: object = True
        self.still_ours: object = True

    def start(self, _client: object) -> true_shuffle.Session:
        self.started += 1
        if isinstance(self.start_result, BaseException):
            raise self.start_result
        return self.start_result  # type: ignore[return-value]

    def stop(self, _client: object, ended: true_shuffle.Session) -> bool:
        self.stopped.append(ended)
        if isinstance(self.stop_result, BaseException):
            raise self.stop_result
        return bool(self.stop_result)


@pytest.fixture
def sessions(monkeypatch: pytest.MonkeyPatch) -> FakeSessions:
    fake = FakeSessions()
    monkeypatch.setattr(true_shuffle, "start", fake.start)
    monkeypatch.setattr(true_shuffle, "stop", fake.stop)
    monkeypatch.setattr(toggle_module, "_still_ours", lambda _client, _session: fake.still_ours)
    return fake


@pytest.fixture
def account(qapp: QApplication) -> FakeAccount:
    return FakeAccount()


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def seen() -> list[ToggleStatus]:
    return []


@pytest.fixture
def toggle(
    account: FakeAccount, jobs: HeldJobs, seen: list[ToggleStatus], sessions: FakeSessions
) -> TrueShuffleController:
    controller = TrueShuffleController(account, runner=jobs)  # type: ignore[arg-type]
    controller.status_changed.connect(seen.append)
    return controller


def states(seen: list[ToggleStatus]) -> list[ToggleState]:
    return [status.state for status in seen]


def test_ticking_it_starts_a_true_shuffle(
    toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus], sessions: FakeSessions
) -> None:
    toggle.toggle(True)
    assert toggle.status.state is ToggleState.STARTING

    jobs.release()

    assert states(seen) == [ToggleState.STARTING, ToggleState.ON]
    assert seen[-1].message is not None and "2 songs in a fair random order" in seen[-1].message
    assert sessions.started == 1
    assert toggle.watch_timer.isActive()


def test_unticking_it_goes_back_to_normal(
    toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus], sessions: FakeSessions
) -> None:
    toggle.toggle(True)
    jobs.release()

    toggle.toggle(False)
    jobs.release()

    assert states(seen)[-2:] == [ToggleState.STOPPING, ToggleState.OFF]
    assert sessions.stopped == [sessions.start_result]
    assert not toggle.watch_timer.isActive()


def test_a_start_spotify_refuses_says_why_and_stays_off(
    toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus], sessions: FakeSessions
) -> None:
    sessions.start_result = NoActiveDevice("Open the Spotify app first.")

    toggle.toggle(True)
    jobs.release()

    assert seen[-1] == ToggleStatus(ToggleState.OFF, "Open the Spotify app first.", warning=True)
    assert not toggle.watch_timer.isActive()


def test_a_bug_of_ours_shows_a_fixed_message(
    toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus], sessions: FakeSessions
) -> None:
    sessions.start_result = KeyError("fakesong1")

    toggle.toggle(True)
    jobs.release()

    assert seen[-1] == ToggleStatus(ToggleState.OFF, UNEXPECTED, warning=True)


def test_a_failed_stop_says_why(
    toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus], sessions: FakeSessions
) -> None:
    toggle.toggle(True)
    jobs.release()
    sessions.stop_result = SpotifyError("Couldn't reach Spotify.")

    toggle.toggle(False)
    jobs.release()

    assert seen[-1] == ToggleStatus(ToggleState.OFF, "Couldn't reach Spotify.", warning=True)


def test_signed_out_it_asks_to_sign_in(
    account: FakeAccount, toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus]
) -> None:
    account.sign_out()

    toggle.toggle(True)

    assert seen == [ToggleStatus(ToggleState.OFF, NOT_SIGNED_IN, warning=True)]
    assert jobs.jobs == []


def test_an_old_sign_in_is_pointed_at_allow_playback_control(
    account: FakeAccount, toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus]
) -> None:
    account.status = AccountStatus(AccountState.SIGNED_IN, playback=False)

    toggle.toggle(True)

    assert seen == [ToggleStatus(ToggleState.OFF, NEEDS_PLAYBACK_SIGN_IN, warning=True)]
    assert jobs.jobs == []


def test_clicks_while_it_is_changing_are_ignored(
    toggle: TrueShuffleController, jobs: HeldJobs
) -> None:
    toggle.toggle(True)
    toggle.toggle(False)
    toggle.toggle(True)

    assert len(jobs.jobs) == 1


def test_it_unticks_itself_when_spotify_moves_on(
    toggle: TrueShuffleController, jobs: HeldJobs, seen: list[ToggleStatus], sessions: FakeSessions
) -> None:
    toggle.toggle(True)
    jobs.release()
    sessions.still_ours = False

    toggle.watch_timer.timeout.emit()
    jobs.release()

    assert seen[-1] == ToggleStatus(ToggleState.OFF)
    assert sessions.stopped == []  # nothing is sent to Spotify; the user moved on themselves


@pytest.mark.parametrize("answer", [True, None], ids=["still-ours", "couldnt-ask"])
def test_it_stays_on_while_ours_or_when_spotify_cant_be_asked(
    toggle: TrueShuffleController, jobs: HeldJobs, sessions: FakeSessions, answer: object
) -> None:
    toggle.toggle(True)
    jobs.release()
    sessions.still_ours = answer

    toggle.watch_timer.timeout.emit()
    jobs.release()

    assert toggle.status.state is ToggleState.ON


def test_signing_out_turns_it_off_and_drops_a_late_result(
    account: FakeAccount,
    toggle: TrueShuffleController,
    jobs: HeldJobs,
    seen: list[ToggleStatus],
) -> None:
    toggle.toggle(True)

    account.sign_out()
    jobs.release()

    assert states(seen) == [ToggleState.STARTING, ToggleState.OFF]
    assert not toggle.watch_timer.isActive()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"order": ("spotify:track:fakesong1",)}, "1 song in"),
        ({"left_for_later": 700}, "The other 700 wait for next time"),
        ({"skipped": 1}, "1 local or unavailable song was left out"),
        ({"skipped": 3}, "3 local or unavailable songs were left out"),
        ({"confirmed": False}, "Spotify hasn't confirmed it yet"),
    ],
)
def test_the_on_message_says_what_happened(changes: dict[str, Any], expected: str) -> None:
    assert expected in toggle_module._started_text(session(**changes))


# The tick box in the tray menu


@pytest.fixture
def tray(account: FakeAccount, toggle: TrueShuffleController) -> Iterator[TrayIcon]:
    icon = TrayIcon(quit_app=lambda: None, account=account, true_shuffle=toggle)  # type: ignore[arg-type]
    yield icon
    icon.hide()


def test_the_tick_box_shows_only_while_signed_in(account: FakeAccount, tray: TrayIcon) -> None:
    tray.show_account_status(account.status)
    assert tray.true_shuffle_action.isVisible()
    assert tray.true_shuffle_action.isCheckable()

    account.sign_out()
    tray.show_account_status(account.status)
    assert not tray.true_shuffle_action.isVisible()


def test_the_tick_box_follows_the_toggle(
    tray: TrayIcon, toggle: TrueShuffleController, jobs: HeldJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(tray, "showMessage", lambda title, *_: shown.append(title))

    tray.true_shuffle_action.trigger()  # ticks it
    assert tray.true_shuffle_action.isChecked()
    assert not tray.true_shuffle_action.isEnabled()
    assert tray.true_shuffle_action.text() == "True Shuffle (starting…)"

    jobs.release()
    assert tray.true_shuffle_action.isChecked()
    assert tray.true_shuffle_action.isEnabled()
    assert tray.true_shuffle_action.text() == TRUE_SHUFFLE
    assert shown == ["True Shuffle is on"]

    tray.true_shuffle_action.trigger()  # unticks it
    jobs.release()
    assert not tray.true_shuffle_action.isChecked()


def test_a_refused_start_unticks_the_box_and_warns(
    tray: TrayIcon,
    jobs: HeldJobs,
    sessions: FakeSessions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(tray, "showMessage", lambda _title, text, *_: shown.append(text))
    sessions.start_result = NoActiveDevice("Open the Spotify app first.")

    tray.true_shuffle_action.trigger()
    jobs.release()

    assert not tray.true_shuffle_action.isChecked()
    assert shown == ["Open the Spotify app first."]
