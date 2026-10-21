"""The display name for the tray's "Signed in as" line."""

from __future__ import annotations

from typing import Any

import pytest

from fairshuffle.spotify.profile import MAX_NAME_LENGTH, display_name, user_id


class FakeClient:
    def __init__(self, me: dict[str, Any]) -> None:
        self.me = me
        self.paths: list[str] = []

    def get(self, path: str) -> dict[str, Any]:
        self.paths.append(path)
        return self.me


@pytest.mark.parametrize(
    ("me", "name"),
    [
        ({"display_name": "Fake User"}, "Fake User"),
        ({"display_name": "  Fake User  "}, "Fake User"),
        ({"display_name": "Fake\nUser‮"}, "FakeUser"),  # line breaks, direction tricks
        ({"display_name": None}, None),
        ({"display_name": ""}, None),
        ({"display_name": "   "}, None),
        ({"display_name": 42}, None),
        ({}, None),
    ],
)
def test_the_name_is_cleaned_up_for_the_menu(me: dict[str, Any], name: str | None) -> None:
    client = FakeClient(me)

    assert display_name(client) == name  # type: ignore[arg-type]
    assert client.paths == ["/me"]


def test_a_long_name_is_cut_with_an_ellipsis() -> None:
    name = display_name(FakeClient({"display_name": "x" * 200}))  # type: ignore[arg-type]

    assert name is not None
    assert len(name) == MAX_NAME_LENGTH
    assert name.endswith("…")


@pytest.mark.parametrize(
    ("me", "expected"),
    [({"id": "fakeuser"}, "fakeuser"), ({"id": ""}, None), ({"id": 7}, None), ({}, None)],
)
def test_the_user_id_comes_from_me(me: dict[str, Any], expected: str | None) -> None:
    client = FakeClient(me)

    assert user_id(client) == expected  # type: ignore[arg-type]
    assert client.paths == ["/me"]
