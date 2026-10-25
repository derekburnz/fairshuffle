"""The settings file: the "Keep date added" choice survives a restart, and a bad file is ignored."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from fairshuffle.storage import settings
from fairshuffle.storage.paths import settings_file
from fairshuffle.storage.settings import Settings


def test_settings_live_under_roaming_app_data() -> None:
    assert settings_file() == Path(os.environ["APPDATA"]) / "FairShuffle" / "settings.json"


def test_without_a_file_the_defaults_pick_fast_mode() -> None:
    assert settings.load() == Settings(keep_date_added=False)


def test_a_saved_choice_reads_back() -> None:
    assert settings.save(Settings(keep_date_added=True))

    assert settings.load() == Settings(keep_date_added=True)
    assert not list(settings_file().parent.glob(".tmp-*"))  # the temp file was swapped in


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", '{"keep_date_added": "yes"}', '{"keep_date_added": 1}', ""],
)
def test_a_damaged_file_gives_the_defaults(text: str) -> None:
    settings_file().parent.mkdir(parents=True)
    settings_file().write_text(text, encoding="utf-8")

    assert settings.load() == Settings()


def test_an_oversized_file_is_not_read() -> None:
    settings_file().parent.mkdir(parents=True)
    settings_file().write_text(" " * (settings.MAX_FILE_BYTES + 1), encoding="utf-8")

    assert settings.load() == Settings()


def test_a_failed_save_is_logged_without_the_path(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Access is denied", str(settings_file()))

    monkeypatch.setattr(settings, "_write_atomically", refuse)
    caplog.set_level(logging.WARNING)

    assert not settings.save(Settings(keep_date_added=True))
    assert caplog.messages == ["Saving the settings failed"]
    assert settings.load() == Settings()


def test_deeply_nested_json_gives_the_defaults() -> None:
    # json.loads raises RecursionError, not ValueError, on deep nesting; the app must still start.
    settings_file().parent.mkdir(parents=True)
    settings_file().write_text("[" * 99_000, encoding="utf-8")

    assert settings.load() == Settings()


def test_the_true_shuffle_playlist_is_remembered() -> None:
    assert settings.save(Settings(true_shuffle_playlist="fakeplaylist9"))

    assert settings.load().true_shuffle_playlist == "fakeplaylist9"


@pytest.mark.parametrize("value", [1, "", "../etc", "fake playlist", "x" * 65])
def test_a_bad_true_shuffle_playlist_id_is_dropped(value: object) -> None:
    settings_file().parent.mkdir(parents=True)
    data = {"keep_date_added": True, "true_shuffle_playlist": value}
    settings_file().write_text(json.dumps(data), encoding="utf-8")

    assert settings.load() == Settings(keep_date_added=True)


def test_update_keeps_the_other_choices() -> None:
    settings.save(Settings(keep_date_added=True))

    new = settings.update(true_shuffle_playlist="fakeplaylist9")

    assert new == Settings(keep_date_added=True, true_shuffle_playlist="fakeplaylist9")
    assert settings.load() == new
    assert settings.update(keep_date_added=False).true_shuffle_playlist == "fakeplaylist9"
