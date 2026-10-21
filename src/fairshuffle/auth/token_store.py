"""Keeps the Spotify refresh token in Windows Credential Manager (D10).

The refresh token is the one long-lived secret FairShuffle holds: for up to six months it lets
the app get new access tokens without a browser. So it lives where Windows keeps saved network
and Git passwords, in Credential Manager, locked to the user's Windows account, under the
service name FairShuffle. It never goes in a file. The access token, which lasts about an hour,
stays in memory and is not stored here.

keyring is the standard Python library for the operating system's password store; on Windows it
talks to Credential Manager. Tests swap in an in-memory store (tests/conftest.py), so they never
read or write the real one.

Every token this module sees is registered with mask_secret() first, so it can't reach a log.
Errors never quote a token and never carry the store's own exception along with them, because
that exception's message could.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import keyring
from keyring.errors import PasswordDeleteError

from fairshuffle.storage.logging_setup import mask_secret

SERVICE = "FairShuffle"
ACCOUNT = "spotify-refresh-token"
# Credential Manager holds at most 2560 bytes per entry, and keyring writes UTF-16 (2 bytes per
# character), so 1280 characters. Spotify refresh tokens are far shorter.
MAX_TOKEN_BYTES = 2560

log = logging.getLogger(__name__)


class TokenStoreError(Exception):
    """Credential Manager could not be used. The message says what failed, never the token."""


def _call[T](action: str, call: Callable[[], T]) -> T:
    """Run one call to the password store, turning any failure into a TokenStoreError.

    Windows errors from the store are not all keyring errors, so every Exception is caught. Only
    the error's class name is kept, and the TokenStoreError is raised outside the except block,
    so it holds no reference to the original exception.
    """
    try:
        return call()
    except Exception as error:  # any store failure gets the same clear message
        failure = type(error).__name__
    raise TokenStoreError(f"Could not {action} Windows Credential Manager ({failure}).")


def save_refresh_token(token: str) -> None:
    """Store the refresh token, replacing any earlier one."""
    if not token:
        raise ValueError("There is no refresh token to save.")
    mask_secret(token)
    if len(token.encode("utf-16-le")) > MAX_TOKEN_BYTES:
        raise TokenStoreError("The sign-in is too long for Windows Credential Manager.")
    _call("save the sign-in to", lambda: keyring.set_password(SERVICE, ACCOUNT, token))
    log.info("Saved the Spotify sign-in to Credential Manager")


def load_refresh_token() -> str | None:
    """The stored refresh token, or None if there is none."""
    token = _call("read the sign-in from", lambda: keyring.get_password(SERVICE, ACCOUNT))
    if not token:
        return None
    mask_secret(token)
    return token


def delete_refresh_token() -> None:
    """Remove the stored refresh token. Doing nothing when there is none is not an error."""

    def delete() -> bool:
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
        except PasswordDeleteError:
            return False  # nothing was stored
        return True

    if _call("remove the sign-in from", delete):
        log.info("Removed the Spotify sign-in from Credential Manager")
