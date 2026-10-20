"""The one-time codes behind a PKCE sign-in (RFC 7636), as pure functions with no I/O.

PKCE (Proof Key for Code Exchange) is how an app that cannot keep a client secret signs in
safely. Before opening the browser, the app makes a random code_verifier and sends only its
SHA-256 hash, the code_challenge, with the sign-in request. When Spotify later hands back an
authorization code, the app must show the original verifier to swap that code for tokens. A
program that intercepts the code on its way back has no verifier, so the code is useless to it.

state is a second random value that travels out with the request and must come back unchanged
on the callback. A callback with any other state did not come from the sign-in this app started,
so the loopback listener drops it.

Every value comes from the secrets module, Python's cryptographically secure random source.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import string
from dataclasses import dataclass, field

CHALLENGE_METHOD = "S256"  # the only method Spotify accepts, and the one RFC 7636 says to use

# RFC 7636 section 4.1: a verifier is 43 to 128 characters from the unreserved URI characters.
MIN_VERIFIER_LENGTH = 43
MAX_VERIFIER_LENGTH = 128
UNRESERVED_CHARACTERS = frozenset(string.ascii_letters + string.digits + "-._~")

# Section 4.1 recommends 32 random octets, base64url-encoded, which gives a 43-character
# verifier with 256 bits of randomness. state gets the same strength.
RANDOM_OCTETS = 32


def _base64url(data: bytes) -> str:
    """Base64url without the = padding, as RFC 7636 appendix A describes."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def new_code_verifier() -> str:
    """A fresh code_verifier: 43 characters, 256 bits from the secrets module."""
    return _base64url(secrets.token_bytes(RANDOM_OCTETS))


def check_code_verifier(verifier: str) -> None:
    """Raise ValueError if verifier breaks the RFC 7636 rules for length or characters.

    The message never quotes the verifier, so it is safe to log.
    """
    if not MIN_VERIFIER_LENGTH <= len(verifier) <= MAX_VERIFIER_LENGTH:
        raise ValueError(
            f"A code_verifier must be {MIN_VERIFIER_LENGTH} to {MAX_VERIFIER_LENGTH} characters, "
            f"not {len(verifier)}."
        )
    if not UNRESERVED_CHARACTERS.issuperset(verifier):
        raise ValueError("A code_verifier may only use letters, digits and - . _ ~")


def code_challenge(verifier: str) -> str:
    """The S256 code_challenge for verifier: base64url(SHA-256(verifier)), no padding."""
    check_code_verifier(verifier)
    return _base64url(hashlib.sha256(verifier.encode("ascii")).digest())


def new_state() -> str:
    """A fresh state value: 43 URL-safe characters, 256 bits from the secrets module."""
    return _base64url(secrets.token_bytes(RANDOM_OCTETS))


def states_match(expected: str, received: str | None) -> bool:
    """True only if the callback brought back exactly the state this app sent.

    The comparison takes the same time however many characters match, so the listener's reply
    time gives nothing away about the expected value.
    """
    if not received:
        return False
    try:
        received_bytes = received.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate can't be UTF-8, so it can't be our state
        return False
    return secrets.compare_digest(expected.encode("utf-8"), received_bytes)


@dataclass(frozen=True, slots=True)
class PkceRequest:
    """The three values one sign-in attempt needs. Make a new one for every attempt.

    The verifier is left out of repr, so printing or logging the object never shows it.
    """

    verifier: str = field(repr=False)
    challenge: str
    state: str

    @classmethod
    def new(cls) -> PkceRequest:
        verifier = new_code_verifier()
        return cls(verifier=verifier, challenge=code_challenge(verifier), state=new_state())
