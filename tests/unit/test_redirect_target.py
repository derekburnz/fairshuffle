"""Reading the Redirect URI: only http://127.0.0.1 with a port is accepted."""

from __future__ import annotations

import pytest

from fairshuffle.auth.loopback import InvalidRedirectUri, RedirectTarget


def test_the_standard_redirect_uri_is_read() -> None:
    target = RedirectTarget.parse("http://127.0.0.1:8888/callback")

    assert target == RedirectTarget(port=8888, path="/callback")


def test_a_missing_path_means_the_root() -> None:
    assert RedirectTarget.parse("http://127.0.0.1:8888").path == "/"


@pytest.mark.parametrize(
    ("uri", "reason"),
    [
        ("http://localhost:8888/callback", "localhost"),
        ("http://LOCALHOST:8888/callback", "localhost"),
        ("http://0.0.0.0:8888/callback", "127.0.0.1"),
        ("http://[::1]:8888/callback", "127.0.0.1"),
        ("http://127.1:8888/callback", "127.0.0.1"),
        ("http://example.com:8888/callback", "127.0.0.1"),
        ("https://127.0.0.1:8888/callback", "http://"),
        ("127.0.0.1:8888/callback", "http://"),
        ("", "http://"),
        ("http://127.0.0.1/callback", "port"),
        ("http://127.0.0.1:0/callback", "port"),
        ("http://127.0.0.1:99999/callback", "port"),
        ("http://127.0.0.1:port/callback", "port"),
        ("http://user:pass@127.0.0.1:8888/callback", "user name"),
        ("http://user@127.0.0.1:8888/callback", "user name"),
        ("http://127.0.0.1:8888/callback?next=x", "query"),
        ("http://127.0.0.1:8888/callback#top", "fragment"),
    ],
)
def test_unsafe_or_unusable_redirect_uris_are_refused(uri: str, reason: str) -> None:
    with pytest.raises(InvalidRedirectUri, match=reason):
        RedirectTarget.parse(uri)


def test_invalid_redirect_uri_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        RedirectTarget.parse("http://localhost:8888/callback")
