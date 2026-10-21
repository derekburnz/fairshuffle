"""Reading Spotify's slow-down signals and working out how long to wait."""

from __future__ import annotations

import random

import pytest
import requests

from fairshuffle.spotify.ratelimit import (
    RetryPolicy,
    backoff_delay,
    quota_exceeded,
    retry_after_seconds,
)


def reply(headers: dict[str, str] | None = None, body: bytes = b"") -> requests.Response:
    response = requests.Response()
    response.status_code = 429
    response.headers.update(headers or {})
    response._content = body
    return response


@pytest.mark.parametrize(
    ("header", "seconds"),
    [("5", 5.0), (" 12 ", 12.0), ("0", 0.0), ("2.5", 2.5)],
)
def test_retry_after_is_read_in_seconds(header: str, seconds: float) -> None:
    assert retry_after_seconds(reply({"Retry-After": header})) == seconds


@pytest.mark.parametrize(
    "header", ["", "-1", "soon", "Wed, 21 Oct 2026 07:28:00 GMT", "1e9", "9999999"]
)
def test_an_unreadable_retry_after_counts_as_none(header: str) -> None:
    assert retry_after_seconds(reply({"Retry-After": header})) is None


def test_a_missing_retry_after_counts_as_none() -> None:
    assert retry_after_seconds(reply()) is None


def test_the_quota_exceeded_body_is_recognised() -> None:
    body = b'{"error":{"status":429,"message":"Too many requests","reason":"QUOTA_EXCEEDED"}}'

    assert quota_exceeded(reply(body=body))


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'{"error": "QUOTA_EXCEEDED"}',
        b'{"error": {"status": 429, "message": "Too many requests"}}',
        b'{"error": {"reason": "SOMETHING_ELSE"}}',
    ],
)
def test_other_429_bodies_are_not_quota_exceeded(body: bytes) -> None:
    assert not quota_exceeded(reply(body=body))


def test_the_backoff_ceiling_doubles_and_stops_at_the_maximum() -> None:
    class Top(random.Random):
        def uniform(self, a: float, b: float) -> float:
            return b

    policy = RetryPolicy(base_delay=1.0, max_delay=10.0)

    assert [backoff_delay(retry, policy, Top()) for retry in range(6)] == [1, 2, 4, 8, 10, 10]


def test_the_backoff_is_jittered_between_zero_and_the_ceiling() -> None:
    rng = random.Random(1234)  # noqa: S311  # jitter test, not security
    waits = [backoff_delay(3, RetryPolicy(), rng) for _ in range(200)]

    assert all(0 <= wait <= 8 for wait in waits)
    assert len(set(waits)) > 100  # spread out, not one fixed value
