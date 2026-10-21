"""How long to wait before trying Spotify again.

Spotify counts requests in a rolling 30-second window and doesn't publish the limit. Over it, the
reply is 429, normally with a Retry-After header in seconds; since July 2026 a reply whose JSON
says QUOTA_EXCEEDED means the app's shared quota is used up. When Spotify gives no wait (no
Retry-After, a 5xx or a dropped connection), FairShuffle backs off exponentially with full
jitter: a random wait between 0 and 1, 2, 4... seconds, so retries from several workers don't
all land at the same moment. It is the same idea as BGP's route flap dampening, where a
neighbour that keeps failing gets held off for longer each time.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

import requests

_SECONDS = re.compile(r"\d{1,6}(\.\d{1,3})?")  # Spotify sends whole seconds; allow a fraction


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How hard to try. The defaults give a read about a minute in all before giving up."""

    max_attempts: int = 4  # the first try plus three retries
    base_delay: float = 1.0  # seconds; the backoff ceiling doubles from here
    max_delay: float = 30.0  # the backoff ceiling never goes above this
    max_retry_after: float = 60.0  # a longer Retry-After is handed to the user instead of waited

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10.")
        if min(self.base_delay, self.max_delay, self.max_retry_after) < 0:
            raise ValueError("Delays can't be negative.")


def retry_after_seconds(response: requests.Response) -> float | None:
    """Spotify's Retry-After in seconds, or None if it is missing or unreadable."""
    value = response.headers.get("Retry-After", "").strip()
    return float(value) if _SECONDS.fullmatch(value) else None


def quota_exceeded(response: requests.Response) -> bool:
    """True when a 429's JSON body says {"error": {"reason": "QUOTA_EXCEEDED"}}."""
    try:
        body: Any = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and error.get("reason") == "QUOTA_EXCEEDED"


def backoff_delay(retry: int, policy: RetryPolicy, rng: random.Random) -> float:
    """The wait before retry number `retry` (0 for the first retry), with full jitter."""
    ceiling = min(policy.max_delay, policy.base_delay * 2**retry)
    return rng.uniform(0, ceiling)
