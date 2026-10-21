"""The check after a shuffle spots lost, doubled and moved songs, and nothing else."""

from __future__ import annotations

import pytest

from fairshuffle.shuffle.verify import Verdict, verify
from fairshuffle.spotify.models import PlaylistItem

LOCAL = "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"


def read_back(uris: list[str | None]) -> list[PlaylistItem]:
    return [
        PlaylistItem(n, uri, "track" if uri else None, is_local=uri == LOCAL)
        for n, uri in enumerate(uris)
    ]


PLAN: list[str | None] = ["spotify:track:a", "spotify:track:b", "spotify:track:a", LOCAL, None]


def test_the_planned_result_passes() -> None:
    verdict = verify(PLAN, read_back(PLAN))

    assert verdict == Verdict(5, 5, missing=0, extra=0, in_order=True)
    assert verdict.ok


def test_an_empty_playlist_that_should_be_empty_passes() -> None:
    assert verify([], []).ok


@pytest.mark.parametrize(
    ("actual", "missing", "extra"),
    [
        (PLAN[:3], 2, 0),  # cut off before the end
        ([*PLAN, "spotify:track:c"], 0, 1),  # someone added a song
        (["spotify:track:a", "spotify:track:b", LOCAL, None], 1, 0),  # one copy of a duplicate gone
        ([*PLAN[:4], "spotify:track:z"], 1, 1),  # a song swapped for another
        ([], 5, 0),
    ],
)
def test_lost_or_extra_songs_fail(actual: list[str | None], missing: int, extra: int) -> None:
    verdict = verify(PLAN, read_back(actual))

    assert (verdict.missing, verdict.extra) == (missing, extra)
    assert not verdict.same_songs
    assert not verdict.ok


def test_the_same_songs_in_another_order_are_reported_apart() -> None:
    verdict = verify(PLAN, read_back(list(reversed(PLAN))))

    assert verdict.same_songs
    assert not verdict.in_order
    assert not verdict.ok


def test_a_verdict_carries_counts_only() -> None:
    assert LOCAL not in repr(verify(PLAN, read_back(PLAN[:2])))
