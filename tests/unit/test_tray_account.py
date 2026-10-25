"""The account lines in the tray menu: what they say in each state and what they do."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from fairshuffle.ui.account import AccountController, AccountState, AccountStatus
from fairshuffle.ui.tray import TOOLTIP, TrayIcon


class HeldRunner:
    """Never runs a job, so the controller stays in whatever state the test sets."""

    def __call__(self, job: Callable[[], Any], done: Callable[[Any], None]) -> None:
        pass


@pytest.fixture
def account(qapp: QApplication) -> AccountController:
    return AccountController(runner=HeldRunner(), open_browser=lambda _url: False)


@pytest.fixture
def tray(account: AccountController) -> Iterator[TrayIcon]:
    icon = TrayIcon(quit_app=lambda: None, account=account)
    yield icon
    icon.hide()


@pytest.fixture
def messages(tray: TrayIcon, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(tray, "showMessage", lambda _title, text, *_: shown.append(text))
    return shown


def labels(tray: TrayIcon) -> list[str]:
    return [action.text() for action in tray.menu.actions() if action.isVisible()]


def test_the_account_lines_come_first_in_the_menu(tray: TrayIcon) -> None:
    assert labels(tray) == [
        "Checking your Spotify sign-in…",
        "",  # separator
        "&About FairShuffle",
        "",
        "&Quit",
    ]
    assert not tray.status_action.isEnabled()


@pytest.mark.parametrize(
    ("status", "line", "action"),
    [
        (
            AccountStatus(AccountState.SIGNED_OUT),
            "Not signed in to Spotify",
            "&Sign in to Spotify…",
        ),
        (
            AccountStatus(AccountState.SIGNING_IN),
            "Waiting for you to sign in in your browser…",
            "&Cancel sign-in",
        ),
        (
            AccountStatus(AccountState.SIGNED_IN, name="Fake User"),
            "Signed in as Fake User",
            "Sign &out",
        ),
        (AccountStatus(AccountState.SIGNED_IN), "Signed in to Spotify", "Sign &out"),
        (
            AccountStatus(AccountState.SIGN_IN_AGAIN),
            "Your Spotify sign-in has expired",
            "&Sign in again…",
        ),
        (
            AccountStatus(AccountState.SETUP_NEEDED),
            "Spotify app not set up yet (see docs/spotify-setup.md)",
            "&Sign in to Spotify…",
        ),
        (
            AccountStatus(AccountState.UNAVAILABLE),
            "Couldn't check your Spotify sign-in",
            "&Try again",
        ),
    ],
)
def test_each_state_has_its_own_lines(
    tray: TrayIcon, status: AccountStatus, line: str, action: str
) -> None:
    tray.show_account_status(status)

    assert labels(tray)[:2] == [line, action]
    assert tray.toolTip() == f"{TOOLTIP}\n{line}"


def test_an_ampersand_in_a_name_is_shown_not_read_as_a_shortcut(tray: TrayIcon) -> None:
    tray.show_account_status(AccountStatus(AccountState.SIGNED_IN, name="Tom & Jerry"))

    assert tray.status_action.text() == "Signed in as Tom && Jerry"


def test_a_message_is_shown_once_as_a_notification(tray: TrayIcon, messages: list[str]) -> None:
    tray.show_account_status(AccountStatus(AccountState.SIGNED_OUT))
    tray.show_account_status(
        AccountStatus(AccountState.SIGNED_OUT, message="Signed out of Spotify.")
    )

    assert messages == ["Signed out of Spotify."]


def test_the_menu_follows_the_controller(account: AccountController, tray: TrayIcon) -> None:
    account.status_changed.emit(AccountStatus(AccountState.SIGNED_IN, name="Fake User"))

    assert tray.status_action.text() == "Signed in as Fake User"


@pytest.mark.parametrize(
    ("state", "method"),
    [
        (AccountState.SIGNED_OUT, "sign_in"),
        (AccountState.SIGN_IN_AGAIN, "sign_in"),
        (AccountState.SETUP_NEEDED, "sign_in"),
        (AccountState.SIGNING_IN, "cancel_sign_in"),
        (AccountState.SIGNED_IN, "sign_out"),
        (AccountState.UNAVAILABLE, "start"),
    ],
)
def test_the_account_action_does_what_it_says(
    account: AccountController,
    tray: TrayIcon,
    monkeypatch: pytest.MonkeyPatch,
    state: AccountState,
    method: str,
) -> None:
    calls: list[str] = []
    for name in ("sign_in", "cancel_sign_in", "sign_out", "start"):
        monkeypatch.setattr(account, name, lambda name=name: calls.append(name))
    account._status = AccountStatus(state)  # as if the controller had got there itself

    tray.account_action.trigger()

    assert calls == [method]


def test_a_sign_in_without_playback_control_offers_to_allow_it(
    account: AccountController, tray: TrayIcon, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(account, "sign_in", lambda: calls.append("sign_in"))
    tray.show_account_status(AccountStatus(AccountState.SIGNED_IN, playback=False))

    assert labels(tray)[:3] == [
        "Signed in to Spotify",
        "Sign &out",
        "Allow &playback control…",
    ]
    tray.playback_action.trigger()
    assert calls == ["sign_in"]

    tray.show_account_status(AccountStatus(AccountState.SIGNED_IN))
    assert not tray.playback_action.isVisible()


def test_without_an_account_the_menu_is_as_before(qapp: QApplication) -> None:
    icon = TrayIcon(quit_app=lambda: None)

    assert [action.text() for action in icon.menu.actions()] == ["&About FairShuffle", "", "&Quit"]
