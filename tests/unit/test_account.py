"""The account controller behind the tray menu, with fake Spotify replies and a fake browser."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

import keyring
import pytest
import requests
import responses
from pytestqt.qtbot import QtBot

from fairshuffle.auth.loopback import CallbackTimeout, ListenerCancelled
from fairshuffle.auth.oauth import SignInRequired, SpotifyAuth, Tokens
from fairshuffle.config import ConfigError, SpotifySettings, load_settings
from fairshuffle.ui import account as account_module
from fairshuffle.ui.account import (
    PLAYBACK_SIGN_IN,
    SIGN_IN_CANCELLED,
    UNEXPECTED,
    AccountController,
    AccountState,
    AccountStatus,
    run_in_thread_pool,
)

TOKEN_URL = "https://accounts.spotify.com/api/token"
ME = "https://api.spotify.com/v1/me"
FAKE_REFRESH = "fake-refresh-token-for-tests"
TOKEN_REPLY = {"access_token": "fake-access-token-1", "token_type": "Bearer", "expires_in": 3600}
OLD_SCOPES = "playlist-read-private playlist-modify-private user-read-private"  # before v0.6.0
NEW_SCOPES = f"{OLD_SCOPES} user-read-playback-state user-modify-playback-state"


class Runner:
    """Runs jobs straight away, or holds them until release() when held is True."""

    def __init__(self, held: bool = False) -> None:
        self.held = held
        self.waiting: list[tuple[Callable[[], Any], Callable[[Any], None]]] = []

    def __call__(self, job: Callable[[], Any], done: Callable[[Any], None]) -> None:
        if self.held:
            self.waiting.append((job, done))
        else:
            done(job())

    def release(self, index: int = 0) -> None:
        job, done = self.waiting.pop(index)
        done(job())


class FakeSignIn:
    """Stands in for BrowserSignIn. Set `result` to an exception or to "ok"."""

    result: object = "ok"
    refresh_token = FAKE_REFRESH
    created: list[FakeSignIn] = []

    def __init__(self, http: requests.Session, settings: SpotifySettings, _browser: object) -> None:
        self.http, self.settings = http, settings
        self.cancelled = False
        FakeSignIn.created.append(self)

    def run(self) -> SpotifyAuth:
        if isinstance(FakeSignIn.result, BaseException):
            raise FakeSignIn.result
        keyring.set_password("FairShuffle", "spotify-refresh-token", FakeSignIn.refresh_token)
        tokens = Tokens("fake-access-token-1", FakeSignIn.refresh_token, 3600, frozenset())
        return SpotifyAuth(self.http, self.settings, tokens)

    def cancel(self) -> None:
        self.cancelled = True


@pytest.fixture(autouse=True)
def fake_sign_in(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    FakeSignIn.result = "ok"
    FakeSignIn.refresh_token = FAKE_REFRESH
    FakeSignIn.created = []
    monkeypatch.setattr(account_module, "BrowserSignIn", FakeSignIn)
    yield


@pytest.fixture
def spotify() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture
def seen() -> list[AccountStatus]:
    return []


def controller(
    seen: list[AccountStatus], runner: Runner | None = None, **options: Any
) -> AccountController:
    account = AccountController(
        open_browser=lambda _url: pytest.fail("the real browser must not open"),
        runner=runner or Runner(),
        **options,
    )
    account.status_changed.connect(seen.append)
    return account


def save_refresh_token() -> None:
    keyring.set_password("FairShuffle", "spotify-refresh-token", FAKE_REFRESH)


def stored() -> str | None:
    return keyring.get_password("FairShuffle", "spotify-refresh-token")


# Starting up


def test_with_nothing_saved_it_starts_signed_out(seen: list[AccountStatus]) -> None:
    account = controller(seen)

    account.start()

    assert [status.state for status in seen] == [AccountState.CHECKING, AccountState.SIGNED_OUT]
    assert account.status.message is None
    assert account.client is None


def test_a_restart_resumes_the_saved_sign_in_without_a_browser(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json=TOKEN_REPLY)
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)

    account.start()

    assert account.status == AccountStatus(AccountState.SIGNED_IN, name="Fake User")
    assert account.client is not None
    assert FakeSignIn.created == []


def test_a_sign_in_saved_before_the_player_asks_once_for_playback_control(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)

    account.start()

    assert account.status.state is AccountState.SIGNED_IN
    assert account.status.playback is False
    assert account.status.message == PLAYBACK_SIGN_IN
    assert account.client is not None  # shuffle and Undo still work
    assert [status.message for status in seen].count(PLAYBACK_SIGN_IN) == 1


def test_a_sign_in_with_the_playback_scopes_resumes_quietly(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": NEW_SCOPES})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)

    account.start()

    assert account.status == AccountStatus(AccountState.SIGNED_IN, name="Fake User")
    assert account.status.playback is True


def test_signing_in_again_for_playback_replaces_the_old_sign_in(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.get(ME, json={"display_name": "Fake User"})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.start()

    account.sign_in()  # FakeSignIn grants a sign-in with no scope list, taken on trust

    assert account.status == AccountStatus(
        AccountState.SIGNED_IN, name="Fake User", message="Signed in as Fake User."
    )
    assert account.status.playback is True


def test_signing_in_again_ends_the_old_sign_in_before_saving_the_new_one(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.get(ME, json={"display_name": "Fake User"})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.start()
    old = account.client
    assert old is not None
    FakeSignIn.refresh_token = "fake-refresh-token-2"

    account.sign_in()

    with pytest.raises(SignInRequired):  # a worker still holding it can't refresh or save
        old.get("/me")
    assert stored() == "fake-refresh-token-2"


def test_a_cancel_that_leaves_no_saved_sign_in_says_so(
    spotify: responses.RequestsMock, seen: list[AccountStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.start()

    def cancelled_during_the_exchange() -> SpotifyAuth:
        keyring.delete_password("FairShuffle", "spotify-refresh-token")
        raise ListenerCancelled("Sign-in was cancelled.")

    monkeypatch.setattr(FakeSignIn, "run", lambda _self: cancelled_during_the_exchange())
    account.sign_in()

    assert account.status == AccountStatus(AccountState.SIGNED_OUT, message=SIGN_IN_CANCELLED)


def test_a_failed_sign_in_for_playback_whose_saved_sign_in_expired_asks_again(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.start()
    FakeSignIn.result = CallbackTimeout("The sign-in timed out.")

    account.sign_in()

    assert account.status.state is AccountState.SIGN_IN_AGAIN
    assert account.status.message == "The sign-in timed out."


def test_a_cancelled_sign_in_for_playback_keeps_the_saved_sign_in(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.get(ME, json={"display_name": "Fake User"})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.start()
    FakeSignIn.result = ListenerCancelled()

    account.sign_in()

    assert account.status.state is AccountState.SIGNED_IN
    assert account.status.playback is False
    assert account.client is not None
    assert stored() == FAKE_REFRESH


def test_a_failed_sign_in_for_playback_keeps_the_saved_sign_in_and_says_why(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.post(TOKEN_URL, json={**TOKEN_REPLY, "scope": OLD_SCOPES})
    spotify.get(ME, json={"display_name": "Fake User"})
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.start()
    FakeSignIn.result = CallbackTimeout("The sign-in timed out.")

    account.sign_in()

    assert account.status.state is AccountState.SIGNED_IN
    assert account.status.message == "The sign-in timed out."
    assert stored() == FAKE_REFRESH


def test_an_expired_saved_sign_in_asks_to_sign_in_again(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    account = controller(seen)

    account.start()

    assert account.status.state is AccountState.SIGN_IN_AGAIN
    assert stored() is None


def test_without_a_client_id_it_says_setup_is_needed(seen: list[AccountStatus]) -> None:
    def no_client_id() -> SpotifySettings:
        raise ConfigError("SPOTIFY_CLIENT_ID is not set.")

    account = controller(seen, settings_loader=no_client_id)

    account.start()
    assert account.status == AccountStatus(AccountState.SETUP_NEEDED)  # quiet at start

    account.sign_in()
    assert account.status.state is AccountState.SETUP_NEEDED
    assert account.status.message == "SPOTIFY_CLIENT_ID is not set."


def test_spotify_being_unreachable_at_start_offers_to_try_again(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, body=requests.ConnectionError("down"))
    account = controller(seen)

    account.start()

    assert account.status.state is AccountState.UNAVAILABLE
    assert "ConnectionError" in (account.status.message or "")
    assert stored() == FAKE_REFRESH  # kept for the next try


def test_an_account_missing_from_user_management_is_explained(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json=TOKEN_REPLY)
    spotify.get(ME, status=403, body=b"")
    account = controller(seen)

    account.start()

    assert account.status.state is AccountState.SIGNED_IN
    assert account.status.name is None
    assert "User Management" in (account.status.message or "")


def test_a_profile_spotify_wont_give_still_counts_as_signed_in(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json=TOKEN_REPLY)
    spotify.get(ME, status=404)
    account = controller(seen)

    account.start()

    assert account.status == AccountStatus(AccountState.SIGNED_IN)


def test_a_profile_call_spotify_still_refuses_means_sign_in_again(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json=TOKEN_REPLY)
    spotify.get(ME, status=401)
    spotify.post(TOKEN_URL, json=TOKEN_REPLY)
    spotify.get(ME, status=401)
    account = controller(seen)

    account.start()

    assert account.status.state is AccountState.SIGN_IN_AGAIN
    assert account.client is None


# Signing in


def test_signing_in_shows_the_name_and_says_so_once(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)

    account.sign_in()

    assert [status.state for status in seen] == [AccountState.SIGNING_IN, AccountState.SIGNED_IN]
    assert account.status == AccountStatus(
        AccountState.SIGNED_IN, name="Fake User", message="Signed in as Fake User."
    )
    assert stored() == FAKE_REFRESH


def test_signing_in_without_a_name_still_says_so(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    spotify.get(ME, json={"display_name": None})
    account = controller(seen)

    account.sign_in()

    assert account.status.message == "Signed in to Spotify."


def test_a_cancelled_sign_in_goes_back_quietly(seen: list[AccountStatus]) -> None:
    FakeSignIn.result = ListenerCancelled("Sign-in was cancelled.")
    account = controller(seen)

    account.sign_in()

    assert account.status == AccountStatus(AccountState.SIGNED_OUT)


def test_a_failed_sign_in_says_why(seen: list[AccountStatus]) -> None:
    FakeSignIn.result = CallbackTimeout("Spotify did not answer in time. Try signing in again.")
    account = controller(seen)

    account.sign_in()

    assert account.status.state is AccountState.SIGNED_OUT
    assert account.status.message == "Spotify did not answer in time. Try signing in again."


def test_a_second_sign_in_while_one_is_open_is_ignored(seen: list[AccountStatus]) -> None:
    account = controller(seen, Runner(held=True))

    account.sign_in()
    account.sign_in()

    assert len(FakeSignIn.created) == 1


def test_cancel_sign_in_reaches_the_attempt(seen: list[AccountStatus]) -> None:
    account = controller(seen, Runner(held=True))
    account.cancel_sign_in()  # nothing to cancel yet: no error

    account.sign_in()
    account.cancel_sign_in()

    assert FakeSignIn.created[0].cancelled


# Signing out


def test_sign_out_removes_the_saved_sign_in(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.sign_in()

    account.sign_out()

    assert stored() is None
    assert account.status == AccountStatus(
        AccountState.SIGNED_OUT, message="Signed out of Spotify."
    )
    assert account.client is None


def test_sign_out_ends_the_old_sign_in_before_deleting_it(
    spotify: responses.RequestsMock, seen: list[AccountStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A playlist load still running on a worker holds the old client. Ending it first means
    # that load can't refresh and save a token after the delete, signing the account back in.
    spotify.get(ME, json={"display_name": "Fake User"})
    account = controller(seen)
    account.sign_in()
    old = account.client
    assert old is not None
    ended_at_delete: list[bool] = []
    real_delete = account_module.delete_refresh_token

    def delete() -> None:
        with pytest.raises(SignInRequired):
            old.get("/me")
        ended_at_delete.append(True)
        real_delete()

    monkeypatch.setattr(account_module, "delete_refresh_token", delete)

    account.sign_out()

    assert ended_at_delete == [True]
    assert stored() is None


def test_a_sign_out_that_cant_reach_credential_manager_says_so(
    seen: list[AccountStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_delete() -> None:
        raise account_module.TokenStoreError("Could not remove the sign-in (FakeError).")

    monkeypatch.setattr(account_module, "delete_refresh_token", broken_delete)
    account = controller(seen)

    account.sign_out()

    assert account.status.state is AccountState.SIGNED_OUT
    assert account.status.message == "Could not remove the sign-in (FakeError)."


# Results that arrive late


def test_a_result_that_arrives_after_the_user_moved_on_is_dropped(
    spotify: responses.RequestsMock, seen: list[AccountStatus]
) -> None:
    save_refresh_token()
    spotify.post(TOKEN_URL, json=TOKEN_REPLY)
    spotify.get(ME, json={"display_name": "Fake User"})
    runner = Runner(held=True)
    account = controller(seen, runner)
    account.start()
    account.sign_out()

    runner.release(0)  # the resume finishes signed in, but the user already picked Sign out
    assert account.status.state is AccountState.CHECKING
    assert account.client is None

    runner.release(0)  # then the sign-out
    assert account.status.state is AccountState.SIGNED_OUT
    assert stored() is None


def test_shutdown_cancels_a_sign_in_and_drops_late_results(seen: list[AccountStatus]) -> None:
    runner = Runner(held=True)
    account = controller(seen, runner)
    account.sign_in()

    account.shutdown()
    FakeSignIn.result = ListenerCancelled("Sign-in was cancelled.")  # what cancel() leads to
    runner.release()

    assert FakeSignIn.created[0].cancelled
    assert account.status.state is AccountState.SIGNING_IN  # nothing changed after shutdown


# The thread pool runner


def test_jobs_run_off_the_main_thread_and_report_back_on_it(qtbot: QtBot) -> None:
    import threading

    main = threading.get_ident()
    results: list[tuple[int, int]] = []

    run_in_thread_pool(
        threading.get_ident, lambda worker: results.append((worker, threading.get_ident()))
    )

    qtbot.waitUntil(lambda: bool(results))
    worker, delivered_on = results[0]
    assert worker != main
    assert delivered_on == main


def test_a_job_that_crashes_reports_a_fixed_message(
    qtbot: QtBot, caplog: pytest.LogCaptureFixture
) -> None:
    results: list[Any] = []

    def crash() -> None:
        raise RuntimeError("fake-access-token-1 in a message")

    run_in_thread_pool(crash, results.append)

    qtbot.waitUntil(lambda: bool(results))
    assert results[0].status == AccountStatus(AccountState.UNAVAILABLE, message=UNEXPECTED)
    assert "fake-access-token-1" not in caplog.text
    assert "RuntimeError" in caplog.text


# Logs


def test_the_display_name_never_reaches_the_log(
    spotify: responses.RequestsMock, seen: list[AccountStatus], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    spotify.get(ME, json={"display_name": "Fake Person Name"})
    account = controller(seen)

    account.sign_in()
    account.sign_out()

    assert "Fake Person Name" not in caplog.text


def test_the_real_settings_loader_is_the_default() -> None:
    assert AccountController()._settings_loader is load_settings


# Quitting and tidying up


class RecordingSession(requests.Session):
    closed_count = 0

    def close(self) -> None:
        RecordingSession.closed_count += 1
        super().close()


def test_shutdown_waits_for_running_jobs_before_the_lock_goes(seen: list[AccountStatus]) -> None:
    waits: list[int] = []
    account = controller(seen, wait_for_jobs=lambda ms: waits.append(ms) or True)

    account.shutdown()

    assert waits == [account_module.SHUTDOWN_WAIT_MS]


def test_a_job_still_running_at_quit_is_logged(
    seen: list[AccountStatus], caplog: pytest.LogCaptureFixture
) -> None:
    account = controller(seen, wait_for_jobs=lambda _ms: False)

    account.shutdown()

    assert "still running at quit" in caplog.text


def test_quitting_cuts_short_a_wait_between_retries(seen: list[AccountStatus]) -> None:
    account = controller(seen, wait_for_jobs=lambda _ms: True)
    account._pause(0)  # before Quit a wait just waits

    account.shutdown()

    with pytest.raises(account_module.SpotifyUnavailable, match="closing"):
        account._pause(60)  # returns at once instead of after a minute


def test_the_session_is_closed_when_a_job_fails_unexpectedly(seen: list[AccountStatus]) -> None:
    RecordingSession.closed_count = 0

    class Broken(Exception):
        pass

    FakeSignIn.result = Broken()
    account = controller(seen, session_factory=RecordingSession)

    with pytest.raises(Broken):  # the synchronous runner lets it through; _Task would catch it
        account.sign_in()

    assert RecordingSession.closed_count == 1


def test_a_failed_refresh_while_reading_the_name_still_signs_in_and_says_why(
    spotify: responses.RequestsMock, seen: list[AccountStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refresh_fails(_client: object) -> str:
        raise account_module.TokenError("Couldn't reach Spotify's sign-in service (Timeout).")

    monkeypatch.setattr(account_module, "display_name", refresh_fails)
    account = controller(seen)

    account.sign_in()

    assert account.status.state is AccountState.SIGNED_IN
    assert account.status.message == "Couldn't reach Spotify's sign-in service (Timeout)."
    assert account.client is not None


def test_the_status_repr_leaves_out_the_name() -> None:
    status = AccountStatus(
        AccountState.SIGNED_IN, name="Fake Person", message="Signed in as Fake Person."
    )

    assert "Fake Person" not in repr(status)


def test_the_real_pool_wait_returns_when_nothing_is_running(qapp: object) -> None:
    assert account_module.wait_for_thread_pool(100)
