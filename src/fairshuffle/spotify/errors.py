"""What can go wrong when FairShuffle calls Spotify, as errors the app can show to the user.

Messages quote only the HTTP status and Spotify's short reason code, never a response body, a
token or a query string. SignInRequired comes from the sign-in code and is listed here so callers
can import every Spotify error from one place.
"""

from __future__ import annotations

from fairshuffle.auth.oauth import SignInRequired

__all__ = [
    "AccessDenied",
    "DeviceRestricted",
    "NoActiveDevice",
    "NotOwner",
    "PlayerError",
    "PlayerRefused",
    "PremiumRequired",
    "RateLimited",
    "RequestRejected",
    "SignInRequired",
    "SpotifyError",
    "SpotifyUnavailable",
]


class SpotifyError(Exception):
    """Any Spotify Web API failure other than an ended sign-in.

    reason is Spotify's short reason code from the error object (such as QUOTA_EXCEEDED or
    PREMIUM_REQUIRED) when the reply had a well-formed one, else None.
    """

    reason: str | None = None


class AccessDenied(SpotifyError):
    """Spotify answered 403. In development mode that often means the account isn't on the app's
    User Management list."""


class NotOwner(AccessDenied):
    """Spotify answered 403 for a playlist: it is neither owned by nor shared for editing with the
    signed-in user, so FairShuffle can't read or reorder its items."""


class RateLimited(SpotifyError):
    """Spotify answered 429 and FairShuffle has stopped waiting for now.

    retry_after is Spotify's suggested wait in seconds, if it sent one. quota_exceeded is True
    when the reply said QUOTA_EXCEEDED: the app's shared quota is used up, not just this burst.
    """

    def __init__(self, message: str, retry_after: float | None, quota_exceeded: bool) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.quota_exceeded = quota_exceeded


class SpotifyUnavailable(SpotifyError):
    """Spotify couldn't be reached, or kept answering with a server error.

    may_have_applied is True for a change (a reorder, say) whose fate is unknown: the request may
    have reached Spotify before the failure, so the caller must re-read the playlist before
    trying again rather than send the same change twice.
    """

    def __init__(self, message: str, may_have_applied: bool = False) -> None:
        super().__init__(message)
        self.may_have_applied = may_have_applied


class RequestRejected(SpotifyError):
    """Spotify refused the request itself (400, 404 and similar). Retrying won't help."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class PlayerError(SpotifyError):
    """A playback command (spotify/player.py) that Spotify's app didn't carry out."""


class NoActiveDevice(PlayerError):
    """No Spotify app is open and active for this account, so there is nothing to control."""


class PremiumRequired(PlayerError):
    """Spotify only takes playback commands from Premium accounts."""


class DeviceRestricted(PlayerError):
    """The active device says it accepts no Web API commands (device.is_restricted)."""


class PlayerRefused(PlayerError):
    """Spotify answered a playback command with 403 for another reason, or none."""
