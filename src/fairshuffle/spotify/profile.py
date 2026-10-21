"""The signed-in user's profile: their Spotify user ID and the tray's "Signed in as" line.

GET /me returns id and display_name, which may be null (Spotify docs, re-checked 2026-10-21). The
name is the user's own personal detail, so it is shown in the menu but never written to the log.
"""

from __future__ import annotations

from fairshuffle.spotify.client import SpotifyClient

MAX_NAME_LENGTH = 64  # a longer name is cut so the menu stays a sensible width


def display_name(client: SpotifyClient) -> str | None:
    """The user's Spotify display name, cleaned up for showing in the menu, or None."""
    name = client.get("/me").get("display_name")
    if not isinstance(name, str):
        return None
    return clean_text(name, MAX_NAME_LENGTH)


def user_id(client: SpotifyClient) -> str | None:
    """The signed-in user's Spotify user ID, which playlists name as their owner, or None."""
    value = client.get("/me").get("id")
    return value if isinstance(value, str) and value else None


def clean_text(text: str, max_length: int | None = None) -> str | None:
    """Text from Spotify made safe to show: no line breaks, control or direction characters,
    trimmed, cut with an ellipsis past max_length. None when nothing is left."""
    text = "".join(char for char in text if char.isprintable()).strip()
    if max_length is not None and len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"  # an ellipsis character
    return text or None
