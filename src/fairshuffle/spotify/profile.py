"""The signed-in user's profile, for the tray's "Signed in as" line.

GET /me returns display_name, which may be null (Spotify docs, re-checked 2026-10-21). The name
is the user's own personal detail, so it is shown in the menu but never written to the log.
"""

from __future__ import annotations

from fairshuffle.spotify.client import SpotifyClient

MAX_NAME_LENGTH = 64  # a longer name is cut so the menu stays a sensible width


def display_name(client: SpotifyClient) -> str | None:
    """The user's Spotify display name, cleaned up for showing in the menu, or None."""
    name = client.get("/me").get("display_name")
    if not isinstance(name, str):
        return None
    name = "".join(char for char in name if char.isprintable()).strip()
    if len(name) > MAX_NAME_LENGTH:
        name = name[: MAX_NAME_LENGTH - 1].rstrip() + "…"  # an ellipsis character
    return name or None
