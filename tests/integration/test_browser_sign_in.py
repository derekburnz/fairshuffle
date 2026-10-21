"""A whole browser sign-in over 127.0.0.1, with a fake browser and a fake token endpoint.

The fake browser plays the part of Spotify's sign-in page: it reads the state and Redirect URI
from the authorize URL and calls the listener back, as the real page does after the user agrees.
It uses http.client, which responses doesn't intercept, so it really reaches the listener.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from http.client import HTTPConnection
from urllib.parse import SplitResult, parse_qs, urlencode, urlsplit

import keyring
import pytest
import requests
import responses

from fairshuffle.auth import loopback
from fairshuffle.auth.loopback import ListenerCancelled, RedirectTarget, SignInDenied
from fairshuffle.auth.pkce import code_challenge
from fairshuffle.auth.sign_in import BrowserNotOpened, BrowserSignIn
from fairshuffle.config import SpotifySettings

TOKEN_URL = "https://accounts.spotify.com/api/token"
FAKE_CODE = "fake-auth-code-for-tests"
TOKEN_REPLY = {
    "access_token": "fake-access-token-1",
    "refresh_token": "fake-refresh-token-for-tests",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "playlist-read-private",
}


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loopback, "POLL_SECONDS", 0.02)


@pytest.fixture
def settings() -> SpotifySettings:
    with socket.socket() as probe:  # ask the OS for a free port, then let it go for the listener
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    uri = f"http://127.0.0.1:{port}/callback"
    return SpotifySettings("fake-client-id-for-tests", uri, RedirectTarget.parse(uri))


@pytest.fixture
def spotify() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def http() -> Iterator[requests.Session]:
    with requests.Session() as session:
        yield session


class FakeBrowser:
    """Opens the authorize URL by calling the Redirect URI back on a thread, like Spotify would."""

    def __init__(self, **answer: str) -> None:
        self.answer = answer  # extra or replacement query values for the callback
        self.urls: list[str] = []
        self.threads: list[threading.Thread] = []

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        target = urlsplit(query["redirect_uri"])
        callback = {"code": FAKE_CODE, "state": query["state"], **self.answer}
        thread = threading.Thread(target=self._call_back, args=(target, callback))
        thread.start()
        self.threads.append(thread)
        return True

    def query(self) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(urlsplit(self.urls[0]).query).items()}

    @staticmethod
    def _call_back(target: SplitResult, callback: dict[str, str]) -> None:
        connection = HTTPConnection("127.0.0.1", target.port, timeout=5)
        try:
            connection.request("GET", f"{target.path}?{urlencode(callback)}")
            connection.getresponse().read()
        finally:
            connection.close()

    def join(self) -> None:
        for thread in self.threads:
            thread.join(5)


def test_a_whole_sign_in_saves_the_refresh_token(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    spotify.post(TOKEN_URL, json=TOKEN_REPLY)
    browser = FakeBrowser()

    auth = BrowserSignIn(http, settings, browser, timeout=5).run()
    browser.join()

    assert auth.access_token() == "fake-access-token-1"
    assert (
        keyring.get_password("FairShuffle", "spotify-refresh-token") == TOKEN_REPLY["refresh_token"]
    )
    form = {k: v[0] for k, v in parse_qs(str(spotify.calls[0].request.body)).items()}
    assert form["code"] == FAKE_CODE
    assert code_challenge(form["code_verifier"]) == browser.query()["code_challenge"]
    assert browser.query()["redirect_uri"] == settings.redirect_uri


def test_a_declined_sign_in_raises_and_exchanges_nothing(
    spotify: responses.RequestsMock, http: requests.Session, settings: SpotifySettings
) -> None:
    browser = FakeBrowser(error="access_denied", code="")

    with pytest.raises(SignInDenied):
        BrowserSignIn(http, settings, browser, timeout=5).run()
    browser.join()

    assert len(spotify.calls) == 0


def test_a_browser_that_wont_open_is_reported_and_the_port_freed(
    http: requests.Session, settings: SpotifySettings
) -> None:
    with pytest.raises(BrowserNotOpened):
        BrowserSignIn(http, settings, lambda _url: False, timeout=5).run()

    with socket.create_server(("127.0.0.1", settings.redirect.port)):
        pass  # binding works again, so the listener let go of the port


def test_cancel_before_run_never_opens_the_browser(
    http: requests.Session, settings: SpotifySettings
) -> None:
    opened: list[str] = []
    attempt = BrowserSignIn(http, settings, lambda url: opened.append(url) or True, timeout=5)
    attempt.cancel()

    with pytest.raises(ListenerCancelled):
        attempt.run()

    assert opened == []


def test_cancel_while_waiting_stops_the_sign_in(
    http: requests.Session, settings: SpotifySettings
) -> None:
    attempt: BrowserSignIn

    def browser_that_never_answers(_url: str) -> bool:
        threading.Timer(0.1, attempt.cancel).start()  # the user picks Cancel sign-in
        return True

    attempt = BrowserSignIn(http, settings, browser_that_never_answers, timeout=5)

    with pytest.raises(ListenerCancelled):
        attempt.run()
