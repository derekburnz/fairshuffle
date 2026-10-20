"""PKCE helpers: the RFC 7636 test vector, verifier rules and state checks."""

from __future__ import annotations

import dataclasses
import string

import pytest

from fairshuffle.auth import pkce
from fairshuffle.auth.pkce import (
    MAX_VERIFIER_LENGTH,
    MIN_VERIFIER_LENGTH,
    PkceRequest,
    check_code_verifier,
    code_challenge,
    new_code_verifier,
    new_state,
    states_match,
)

# RFC 7636 appendix B: these 32 octets give this verifier, whose S256 challenge is below.
RFC_OCTETS = bytes(
    [116, 24, 223, 180, 151, 153, 224, 37, 79, 250, 96, 125, 216, 173, 187, 186,
     22, 212, 37, 77, 105, 214, 191, 240, 91, 88, 5, 88, 83, 132, 141, 121]
)  # fmt: skip
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

URL_SAFE = set(string.ascii_letters + string.digits + "-_")


def test_rfc_7636_appendix_b_challenge() -> None:
    assert code_challenge(RFC_VERIFIER) == RFC_CHALLENGE


def test_rfc_7636_appendix_b_verifier_from_its_octets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pkce.secrets, "token_bytes", lambda n: RFC_OCTETS[:n])

    assert new_code_verifier() == RFC_VERIFIER


def test_verifier_draws_32_octets_from_the_secrets_module(monkeypatch: pytest.MonkeyPatch) -> None:
    asked_for: list[int] = []

    def fake_token_bytes(n: int) -> bytes:
        asked_for.append(n)
        return bytes(n)

    monkeypatch.setattr(pkce.secrets, "token_bytes", fake_token_bytes)

    new_code_verifier()

    assert asked_for == [32]


def test_state_draws_32_octets_from_the_secrets_module(monkeypatch: pytest.MonkeyPatch) -> None:
    asked_for: list[int] = []

    def fake_token_bytes(n: int) -> bytes:
        asked_for.append(n)
        return bytes(n)

    monkeypatch.setattr(pkce.secrets, "token_bytes", fake_token_bytes)

    new_state()

    assert asked_for == [32]


def test_new_verifier_follows_the_rfc_rules() -> None:
    verifier = new_code_verifier()

    assert MIN_VERIFIER_LENGTH <= len(verifier) <= MAX_VERIFIER_LENGTH
    assert set(verifier) <= URL_SAFE
    check_code_verifier(verifier)


def test_every_verifier_is_new() -> None:
    assert len({new_code_verifier() for _ in range(100)}) == 100


@pytest.mark.parametrize("length", [MIN_VERIFIER_LENGTH, MAX_VERIFIER_LENGTH])
def test_verifier_length_limits_are_allowed(length: int) -> None:
    check_code_verifier("a" * length)


@pytest.mark.parametrize("length", [0, MIN_VERIFIER_LENGTH - 1, MAX_VERIFIER_LENGTH + 1])
def test_verifier_outside_the_length_limits_is_refused(length: int) -> None:
    with pytest.raises(ValueError, match="43 to 128 characters"):
        check_code_verifier("a" * length)


def test_every_unreserved_character_is_allowed() -> None:
    check_code_verifier(string.ascii_letters + string.digits + "-._~")


@pytest.mark.parametrize("bad", ["+", "/", "=", " ", "%", "é"])
def test_verifier_with_a_reserved_character_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="only use letters"):
        check_code_verifier("a" * 50 + bad)


def test_error_message_never_quotes_the_verifier() -> None:
    verifier = "fake-verifier+" * 4

    with pytest.raises(ValueError) as caught:
        code_challenge(verifier)

    assert verifier not in str(caught.value)


def test_challenge_has_no_padding() -> None:
    challenge = code_challenge(new_code_verifier())

    assert len(challenge) == 43  # 32-byte SHA-256 digest in base64url
    assert set(challenge) <= URL_SAFE


def test_state_is_url_safe_and_new_every_time() -> None:
    states = {new_state() for _ in range(100)}

    assert len(states) == 100
    for state in states:
        assert len(state) == 43
        assert set(state) <= URL_SAFE


def test_same_state_matches() -> None:
    state = new_state()

    assert states_match(state, state)


@pytest.mark.parametrize("received", [None, "", "wrong-state", "été", "\udcff"])
def test_other_state_does_not_match(received: str | None) -> None:
    assert not states_match(new_state(), received)


def test_state_with_one_character_changed_does_not_match() -> None:
    state = new_state()
    changed = state[:-1] + ("A" if state[-1] != "A" else "B")

    assert not states_match(state, changed)


def test_request_holds_a_matching_challenge() -> None:
    request = PkceRequest.new()

    assert request.challenge == code_challenge(request.verifier)
    check_code_verifier(request.verifier)


def test_every_request_is_new() -> None:
    first, second = PkceRequest.new(), PkceRequest.new()

    assert first.verifier != second.verifier
    assert first.state != second.state


def test_request_repr_hides_the_verifier() -> None:
    request = PkceRequest.new()

    assert request.verifier not in repr(request)
    assert request.state in repr(request)


def test_request_cannot_be_changed() -> None:
    request = PkceRequest.new()

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.state = "other"  # type: ignore[misc]
