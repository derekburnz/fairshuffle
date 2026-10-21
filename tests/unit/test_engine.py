"""The Fisher-Yates engine gives a permutation, and every order equally often."""

from __future__ import annotations

import itertools
import random
import secrets
from collections import Counter
from collections.abc import Callable, Sequence

import pytest

from fairshuffle.shuffle import engine
from fairshuffle.shuffle.engine import shuffled

# The chi-square critical value for 23 degrees of freedom (24 orders of 4 items, minus one) at a
# 0.1% significance level. A fair shuffle stays below it 999 times in 1,000.
CHI_SQUARE_23_AT_0_1_PERCENT = 49.728
RUNS = 24_000  # 1,000 expected per order


def seeded(seed: int) -> random.Random:
    """A repeatable source, so a test gives the same answer every run."""
    return random.Random(seed)  # noqa: S311  # tests want repeatable, not secret


def chi_square(shuffle: Callable[[Sequence[str], random.Random], list[str]]) -> float:
    """How far the counts of the 24 orders of ABCD land from 1,000 each."""
    rng = seeded(20261021)
    counts = Counter("".join(shuffle("ABCD", rng)) for _ in range(RUNS))
    expected = RUNS / 24
    orders = ("".join(order) for order in itertools.permutations("ABCD"))
    return sum((counts[order] - expected) ** 2 / expected for order in orders)


def naive_shuffle(items: Sequence[str], rng: random.Random) -> list[str]:
    """The common mistake: swap each position with ANY position, not one at or below it."""
    order = list(items)
    for i in range(len(order)):
        j = rng.randrange(len(order))
        order[i], order[j] = order[j], order[i]
    return order


@pytest.mark.parametrize("count", [0, 1, 2, 10_000])
def test_the_result_is_a_permutation(count: int) -> None:
    items = list(range(count))

    result = shuffled(items, seeded(count))

    assert sorted(result) == items


def test_duplicates_local_files_and_episodes_are_all_kept() -> None:
    items = [
        "spotify:track:fake0001",
        "spotify:track:fake0001",  # the same song twice stays twice
        "spotify:episode:fake0002",
        "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215",
        None,  # an item Spotify no longer has
    ]

    result = shuffled(items, seeded(1))

    assert Counter(result) == Counter(items)


def test_the_input_is_not_changed() -> None:
    items = list("ABCDEF")

    shuffled(items, seeded(1))

    assert items == list("ABCDEF")


def test_every_order_of_four_comes_up_equally_often() -> None:
    assert chi_square(shuffled) < CHI_SQUARE_23_AT_0_1_PERCENT


def test_the_chi_square_test_catches_the_naive_shuffle() -> None:
    # Proves the test above has teeth: 4^4 = 256 equally likely runs can't split evenly over
    # 24 orders, and with 24,000 shuffles the bias is far past the critical value.
    assert chi_square(naive_shuffle) > CHI_SQUARE_23_AT_0_1_PERCENT


def test_ten_thousand_items_land_somewhere_new() -> None:
    items = list(range(10_000))

    result = shuffled(items)

    # A fair shuffle leaves about one item in place on average; the chance of 100 or more is
    # far below one in a googol.
    assert sum(a == b for a, b in zip(items, result, strict=True)) < 100


def test_the_default_source_is_the_operating_systems(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[random.Random] = []

    class Recording(secrets.SystemRandom):
        def __init__(self) -> None:
            super().__init__()
            made.append(self)

    monkeypatch.setattr(engine.secrets, "SystemRandom", Recording)

    shuffled(list("ABC"))

    assert len(made) == 1
