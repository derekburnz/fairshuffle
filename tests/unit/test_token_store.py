"""Refresh token storage: save, load and delete under service FairShuffle, never logged."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import KeyringError, PasswordSetError

from fairshuffle.auth.token_store import (
    ACCOUNT,
    MAX_TOKEN_BYTES,
    SERVICE,
    TokenStoreError,
    delete_refresh_token,
    load_refresh_token,
    save_refresh_token,
)
from fairshuffle.storage import logging_setup

FAKE_REFRESH = "fake-refresh-token-for-tests"


def test_nothing_is_stored_at_first() -> None:
    assert load_refresh_token() is None


def test_a_saved_token_loads_back() -> None:
    save_refresh_token(FAKE_REFRESH)

    assert load_refresh_token() == FAKE_REFRESH
    assert keyring.get_password("FairShuffle", "spotify-refresh-token") == FAKE_REFRESH


def test_saving_again_replaces_the_old_token() -> None:
    save_refresh_token("fake-old-refresh")
    save_refresh_token(FAKE_REFRESH)

    assert load_refresh_token() == FAKE_REFRESH


def test_delete_removes_the_entry() -> None:
    save_refresh_token(FAKE_REFRESH)

    delete_refresh_token()

    assert load_refresh_token() is None
    assert keyring.get_password(SERVICE, ACCOUNT) is None


def test_deleting_when_nothing_is_stored_is_fine() -> None:
    delete_refresh_token()

    assert load_refresh_token() is None


def test_an_empty_token_is_refused() -> None:
    with pytest.raises(ValueError, match="no refresh token"):
        save_refresh_token("")


def test_an_empty_stored_value_counts_as_none() -> None:
    keyring.set_password(SERVICE, ACCOUNT, "")

    assert load_refresh_token() is None


def test_saved_and_loaded_tokens_are_masked_in_logs() -> None:
    save_refresh_token(FAKE_REFRESH)
    assert FAKE_REFRESH in logging_setup._masked_values

    logging_setup._masked_values.clear()
    load_refresh_token()

    assert FAKE_REFRESH in logging_setup._masked_values


def test_the_token_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    save_refresh_token(FAKE_REFRESH)
    load_refresh_token()
    delete_refresh_token()

    assert FAKE_REFRESH not in caplog.text
    assert "Saved the Spotify sign-in" in caplog.text
    assert "Removed the Spotify sign-in" in caplog.text


class FakeWin32Error(Exception):  # stands in for win32ctypes' pywintypes.error
    """Credential Manager's own errors are plain Exceptions, not keyring errors."""


@pytest.fixture(params=[KeyringError, PasswordSetError, FakeWin32Error])
def broken_keyring(request: pytest.FixtureRequest) -> None:
    """A store whose every call fails with a message quoting the token.

    It replaces the in-memory store from conftest, which restores its own afterwards.
    """
    error_type: type[Exception] = request.param

    class BrokenKeyring(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def get_password(self, service: str, username: str) -> str | None:
            raise error_type(f"fake failure reading {FAKE_REFRESH}")

        def set_password(self, service: str, username: str, password: str) -> None:
            raise error_type(f"fake failure saving {password}")

        def delete_password(self, service: str, username: str) -> None:
            raise error_type(f"fake failure deleting {FAKE_REFRESH}")

    keyring.set_keyring(BrokenKeyring())


@pytest.mark.usefixtures("broken_keyring")
@pytest.mark.parametrize(
    ("action", "words"),
    [
        (lambda: save_refresh_token(FAKE_REFRESH), "Could not save"),
        (load_refresh_token, "Could not read"),
        (delete_refresh_token, "Could not remove"),
    ],
)
def test_store_failures_give_a_clear_error_without_the_token(
    action: Callable[[], object], words: str
) -> None:
    with pytest.raises(TokenStoreError, match=words) as caught:
        action()

    assert FAKE_REFRESH not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None  # the store's own message, which quotes it, is gone


def test_a_token_too_long_for_credential_manager_is_refused() -> None:
    too_long = "x" * (MAX_TOKEN_BYTES // 2 + 1)

    with pytest.raises(TokenStoreError, match="too long") as caught:
        save_refresh_token(too_long)

    assert too_long not in str(caught.value)
    assert load_refresh_token() is None


def test_the_longest_token_that_fits_is_saved() -> None:
    longest = "x" * (MAX_TOKEN_BYTES // 2)

    save_refresh_token(longest)

    assert load_refresh_token() == longest


def test_outside_the_in_memory_store_every_call_is_refused() -> None:
    """conftest's safety net: child processes and stray calls get keyring's fail backend."""
    assert os.environ["PYTHON_KEYRING_BACKEND"] == "keyring.backends.fail.Keyring"
    with pytest.raises(KeyringError):
        fail.Keyring().get_password(SERVICE, ACCOUNT)
