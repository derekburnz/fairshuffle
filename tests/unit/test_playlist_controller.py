"""Loading the playlists behind the picker: off the main thread, dropped when stale."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from ui_fakes import FakeAccount, HeldJobs, playlist

from fairshuffle.spotify.errors import RateLimited, SignInRequired, SpotifyUnavailable
from fairshuffle.spotify.models import Playlist
from fairshuffle.ui.account import UNEXPECTED
from fairshuffle.ui.playlists import (
    NO_USER_ID,
    PlaylistController,
    PlaylistsState,
    PlaylistsStatus,
)


class FakeSpotify:
    """Stands in for profile.user_id and playlists.list_editable_playlists."""

    def __init__(self) -> None:
        self.user: str | None = "fakeuser"
        self.playlists = [playlist(1), playlist(2)]
        self.error: Exception | None = None
        self.user_calls = 0
        self.owners: list[str] = []

    def user_id(self, _client: object) -> str | None:
        self.user_calls += 1
        return self.user

    def list_editable_playlists(self, _client: object, owner_id: str) -> list[Playlist]:
        self.owners.append(owner_id)
        if self.error is not None:
            raise self.error
        return self.playlists


@pytest.fixture
def spotify(monkeypatch: pytest.MonkeyPatch) -> FakeSpotify:
    fake = FakeSpotify()
    monkeypatch.setattr("fairshuffle.ui.playlists.user_id", fake.user_id)
    monkeypatch.setattr(
        "fairshuffle.ui.playlists.list_editable_playlists", fake.list_editable_playlists
    )
    return fake


@pytest.fixture
def jobs() -> HeldJobs:
    return HeldJobs()


@pytest.fixture
def account(qapp: QApplication) -> FakeAccount:
    return FakeAccount()


@pytest.fixture
def seen() -> list[PlaylistsStatus]:
    return []


@pytest.fixture
def controller(
    account: FakeAccount, jobs: HeldJobs, seen: list[PlaylistsStatus]
) -> PlaylistController:
    playlists = PlaylistController(account, runner=jobs)  # type: ignore[arg-type]
    playlists.status_changed.connect(seen.append)
    return playlists


def states(seen: list[PlaylistsStatus]) -> list[PlaylistsState]:
    return [status.state for status in seen]


def test_it_starts_with_nothing_loaded(controller: PlaylistController) -> None:
    assert controller.status == PlaylistsStatus(PlaylistsState.IDLE)


def test_refresh_loads_the_list_on_a_worker(
    controller: PlaylistController, jobs: HeldJobs, spotify: FakeSpotify, seen: list[Any]
) -> None:
    controller.refresh()

    assert states(seen) == [PlaylistsState.LOADING]
    assert spotify.owners == []  # nothing ran on this thread yet
    jobs.release()
    assert controller.status == PlaylistsStatus(PlaylistsState.READY, (playlist(1), playlist(2)))
    assert spotify.owners == ["fakeuser"]


def test_the_user_id_is_asked_for_once(
    controller: PlaylistController, jobs: HeldJobs, spotify: FakeSpotify
) -> None:
    controller.refresh()
    jobs.release()
    controller.refresh()
    jobs.release()

    assert spotify.user_calls == 1
    assert spotify.owners == ["fakeuser", "fakeuser"]


def test_while_loading_the_last_list_stays_on_show(
    controller: PlaylistController, jobs: HeldJobs, spotify: FakeSpotify
) -> None:
    controller.refresh()
    jobs.release()
    controller.refresh()

    assert controller.status.state is PlaylistsState.LOADING
    assert controller.status.playlists == (playlist(1), playlist(2))


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (SpotifyUnavailable("Couldn't reach Spotify (ConnectionError)."), "Couldn't reach"),
        (RateLimited("Spotify asked FairShuffle to slow down.", 5, False), "slow down"),
        (SignInRequired("Spotify needs you to sign in again."), "sign in again"),
        (KeyError("a bug of ours"), UNEXPECTED),
    ],
)
def test_a_failed_load_says_why(
    controller: PlaylistController,
    jobs: HeldJobs,
    spotify: FakeSpotify,
    error: Exception,
    message: str,
) -> None:
    spotify.error = error
    controller.refresh()
    jobs.release()

    assert controller.status.state is PlaylistsState.FAILED
    assert message in (controller.status.message or "")


def test_a_crash_is_logged_by_class_name_only(
    controller: PlaylistController,
    jobs: HeldJobs,
    spotify: FakeSpotify,
    caplog: pytest.LogCaptureFixture,
) -> None:
    spotify.error = KeyError("Secret Crush Songs")
    controller.refresh()
    jobs.release()

    assert "KeyError" in caplog.text
    assert "Secret Crush" not in caplog.text


def test_a_job_that_hands_back_nonsense_reports_the_fixed_message(
    controller: PlaylistController, jobs: HeldJobs
) -> None:
    controller.refresh()
    _job, done = jobs.jobs.pop()
    done("not a result")  # what the thread pool's own crash handler would deliver

    assert controller.status == PlaylistsStatus(PlaylistsState.FAILED, message=UNEXPECTED)


def test_no_user_id_from_spotify_is_a_failure(
    controller: PlaylistController, jobs: HeldJobs, spotify: FakeSpotify
) -> None:
    spotify.user = None
    controller.refresh()
    jobs.release()

    assert controller.status == PlaylistsStatus(PlaylistsState.FAILED, message=NO_USER_ID)
    assert spotify.owners == []


def test_a_failure_keeps_the_last_list(
    controller: PlaylistController, jobs: HeldJobs, spotify: FakeSpotify
) -> None:
    controller.refresh()
    jobs.release()
    spotify.error = SpotifyUnavailable("Couldn't reach Spotify (ConnectionError).")
    controller.refresh()
    jobs.release()

    assert controller.status.state is PlaylistsState.FAILED
    assert controller.status.playlists == (playlist(1), playlist(2))


def test_signing_out_drops_the_list_and_any_late_result(
    controller: PlaylistController, jobs: HeldJobs, account: FakeAccount, spotify: FakeSpotify
) -> None:
    controller.refresh()
    account.sign_out()
    jobs.release()  # arrives after the sign-out

    assert controller.status == PlaylistsStatus(PlaylistsState.IDLE)


def test_a_new_sign_in_asks_for_the_user_id_again(
    controller: PlaylistController, jobs: HeldJobs, account: FakeAccount, spotify: FakeSpotify
) -> None:
    controller.refresh()
    jobs.release()
    account.sign_out()
    account.sign_in()
    spotify.user = "otheruser"
    controller.refresh()
    jobs.release()

    assert spotify.owners == ["fakeuser", "otheruser"]


def test_an_older_refresh_that_finishes_last_is_dropped(
    controller: PlaylistController, jobs: HeldJobs, spotify: FakeSpotify
) -> None:
    controller.refresh()
    controller.refresh()
    spotify.playlists = [playlist(3)]
    jobs.release(1)  # the newer one finishes first
    spotify.playlists = [playlist(9)]
    jobs.release(0)

    assert controller.status.playlists == (playlist(3),)


def test_refresh_while_signed_out_does_nothing(
    controller: PlaylistController, jobs: HeldJobs, account: FakeAccount
) -> None:
    account.sign_out()
    controller.refresh()

    assert jobs.jobs == []
    assert controller.status == PlaylistsStatus(PlaylistsState.IDLE)


def test_load_if_needed_skips_a_loaded_or_loading_list(
    controller: PlaylistController, jobs: HeldJobs, spotify: FakeSpotify
) -> None:
    controller.load_if_needed()
    controller.load_if_needed()  # already loading
    assert len(jobs.jobs) == 1
    jobs.release()
    controller.load_if_needed()  # loaded
    assert jobs.jobs == []
    spotify.error = SpotifyUnavailable("Couldn't reach Spotify (ConnectionError).")
    controller.refresh()
    jobs.release()
    controller.load_if_needed()  # failed, so it tries again
    assert len(jobs.jobs) == 1


def test_names_never_show_in_the_status_repr() -> None:
    status = PlaylistsStatus(PlaylistsState.READY, (playlist(1, name="Secret Crush Songs"),))

    assert "Secret Crush" not in repr(status)


def test_staying_signed_in_keeps_the_list(
    controller: PlaylistController, jobs: HeldJobs, account: FakeAccount, spotify: FakeSpotify
) -> None:
    controller.refresh()
    jobs.release()
    account.sign_in(name="Renamed")  # a status update while still signed in

    assert controller.status.state is PlaylistsState.READY


def test_logging_is_quiet_about_names(
    controller: PlaylistController,
    jobs: HeldJobs,
    spotify: FakeSpotify,
    caplog: pytest.LogCaptureFixture,
) -> None:
    spotify.playlists = [playlist(1, name="Secret Crush Songs")]
    with caplog.at_level(logging.DEBUG):
        controller.refresh()
        jobs.release()

    assert "Secret Crush" not in caplog.text
