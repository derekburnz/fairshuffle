"""Checks the playlist after a shuffle: nothing lost, nothing doubled, and in the planned order.

After the last write the playlist is read again and compared with what the plan meant to leave
behind. A shuffle may only change the order, so the songs themselves (as a multiset: a song
listed twice counts twice) must match exactly, and so must the count. If they don't, something
went wrong (a write cut off halfway, another editor changing the playlist) and the app offers to
put the backup back.

The order is checked too, but reported apart: songs all there in another order means something
else moved them, not that anything was lost.

Pure function, no I/O: the caller does the reading.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from fairshuffle.spotify.models import PlaylistItem


@dataclass(frozen=True)
class Verdict:
    """What the re-read playlist looks like next to the plan.

    missing and extra count entries, a song listed twice counting twice. Counts only: the URIs
    themselves are the user's data and a local file's URI holds its artist and title, so a
    Verdict never carries them into a message or a log line.
    """

    expected_count: int
    actual_count: int
    missing: int
    extra: int
    in_order: bool

    @property
    def same_songs(self) -> bool:
        return self.missing == 0 and self.extra == 0 and self.expected_count == self.actual_count

    @property
    def ok(self) -> bool:
        return self.same_songs and self.in_order


def verify(expected: Sequence[str | None], actual: Sequence[PlaylistItem]) -> Verdict:
    """Compare the URIs the plan meant to leave, in order, with the playlist as read back now.

    None stands for an entry Spotify sends no URI for; such entries count like any other. They
    all look alike, so one swapped for another can't be told apart: Spotify gives nothing more
    to compare.
    """
    found = [item.uri for item in actual]
    wanted, have = Counter(expected), Counter(found)
    return Verdict(
        expected_count=len(expected),
        actual_count=len(found),
        missing=sum((wanted - have).values()),
        extra=sum((have - wanted).values()),
        in_order=list(expected) == found,
    )
