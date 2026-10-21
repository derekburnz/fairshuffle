"""The Fisher-Yates shuffle (Knuth's Algorithm P), the reason FairShuffle exists.

Walk the list from the last position down to the second. At each position i, pick a position j
from 0 to i inclusive, every one equally likely, and swap the two. Position i is then final: it
holds a fair pick from everything not yet placed. After n - 1 steps every one of the n! orders
has had exactly the same chance, 1 / n!.

Two details make or break that:

- j must range over 0..i, including i itself. Picking from 0..n-1 every time (the common
  mistake) gives n^n equally likely runs, which can't split evenly over n! orders, so some
  orders come up more often than others. tests/unit/test_engine.py shows the chi-square test
  catching exactly that bias.
- The random numbers must come from a source with enough state. Python's default generator
  (Mersenne Twister) has 2^19937 states, but secrets.SystemRandom asks the operating system
  (on Windows, the system's cryptographic generator) for fresh randomness on every call, so no
  order is out of reach however long the playlist is, and nothing about the next shuffle can be
  predicted from the last. Tests pass a seeded random.Random instead, so their results repeat.

Pure function, no I/O: it shuffles whatever it is given, duplicates, local files and episodes
alike, and never changes the list passed in.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from random import Random


def shuffled[T](items: Sequence[T], rng: Random | None = None) -> list[T]:
    """A new list holding items in a uniformly random order. rng defaults to SystemRandom."""
    if rng is None:
        rng = secrets.SystemRandom()
    order = list(items)
    for i in range(len(order) - 1, 0, -1):
        j = rng.randrange(i + 1)  # 0 <= j <= i, each equally likely
        order[i], order[j] = order[j], order[i]
    return order
