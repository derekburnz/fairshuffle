"""Reading the Spotify settings from the environment and the dev .env file (P2-3)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fairshuffle import config
from fairshuffle.auth.loopback import RedirectTarget
from fairshuffle.config import ConfigError, dev_env_file, load_settings
from fairshuffle.storage import logging_setup

FILE_CLIENT_ID = "fake-client-id-from-file"


def write_env(folder: Path, text: str) -> Path:
    path = folder / ".env"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def no_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the fake settings conftest puts in the environment, so only the file counts."""
    monkeypatch.delenv(config.CLIENT_ID_VARIABLE)
    monkeypatch.delenv(config.REDIRECT_URI_VARIABLE)


def test_the_environment_is_read() -> None:
    settings = load_settings()

    assert settings.client_id == "fake-client-id-for-tests"
    assert settings.redirect_uri == "http://127.0.0.1:8888/callback"
    assert settings.redirect == RedirectTarget(port=8888, path="/callback")


@pytest.mark.usefixtures("no_env_vars")
def test_the_env_file_is_read_when_the_environment_has_nothing(tmp_path: Path) -> None:
    env = write_env(
        tmp_path,
        f"SPOTIFY_CLIENT_ID={FILE_CLIENT_ID}\nSPOTIFY_REDIRECT_URI=http://127.0.0.1:9000/cb\n",
    )

    settings = load_settings(env)

    assert settings.client_id == FILE_CLIENT_ID
    assert settings.redirect == RedirectTarget(port=9000, path="/cb")


def test_the_environment_wins_over_the_env_file(tmp_path: Path) -> None:
    env = write_env(tmp_path, f"SPOTIFY_CLIENT_ID={FILE_CLIENT_ID}\n")

    assert load_settings(env).client_id == "fake-client-id-for-tests"


@pytest.mark.usefixtures("no_env_vars")
def test_the_default_redirect_uri_is_used_when_none_is_set(tmp_path: Path) -> None:
    env = write_env(tmp_path, f"SPOTIFY_CLIENT_ID={FILE_CLIENT_ID}\n")

    settings = load_settings(env)

    assert settings.redirect_uri == config.DEFAULT_REDIRECT_URI


@pytest.mark.usefixtures("no_env_vars")
def test_quotes_comments_and_spaces_in_the_env_file_are_handled(tmp_path: Path) -> None:
    env = write_env(tmp_path, f'# my Spotify app\nSPOTIFY_CLIENT_ID = "  {FILE_CLIENT_ID}  "\n')

    assert load_settings(env).client_id == FILE_CLIENT_ID


@pytest.mark.usefixtures("no_env_vars")
def test_a_missing_env_file_counts_as_nothing_set(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="SPOTIFY_CLIENT_ID is not set"):
        load_settings(tmp_path / "missing.env")


@pytest.mark.usefixtures("no_env_vars")
def test_the_default_env_file_is_the_one_dev_env_file_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = write_env(tmp_path, f"SPOTIFY_CLIENT_ID={FILE_CLIENT_ID}\n")
    monkeypatch.setattr(config, "dev_env_file", lambda: env)

    assert load_settings().client_id == FILE_CLIENT_ID


@pytest.mark.usefixtures("no_env_vars")
def test_no_env_file_at_all_counts_as_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "dev_env_file", lambda: None)

    with pytest.raises(ConfigError, match="SPOTIFY_CLIENT_ID is not set"):
        load_settings()


@pytest.mark.parametrize("value", ["", "   ", config.PLACEHOLDER_CLIENT_ID])
def test_an_empty_or_placeholder_client_id_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(config.CLIENT_ID_VARIABLE, value)

    with pytest.raises(ConfigError, match=r"docs/spotify-setup\.md"):
        load_settings()


@pytest.mark.parametrize(
    "uri", ["http://localhost:8888/callback", "https://127.0.0.1:8888/callback", "nonsense"]
)
def test_an_unusable_redirect_uri_is_refused_without_a_traceback_chain(
    monkeypatch: pytest.MonkeyPatch, uri: str
) -> None:
    monkeypatch.setenv(config.REDIRECT_URI_VARIABLE, uri)

    with pytest.raises(ConfigError, match="SPOTIFY_REDIRECT_URI can't be used") as caught:
        load_settings()

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_the_client_id_is_masked_as_soon_as_it_is_read() -> None:
    load_settings()

    assert "fake-client-id-for-tests" in logging_setup._masked_values


def test_the_client_id_is_left_out_of_repr() -> None:
    settings = load_settings()

    assert "fake-client-id-for-tests" not in repr(settings)


# dev_env_file was imported above, before conftest swaps the module's copy for a stub.
def test_dev_env_file_is_the_project_folders_env() -> None:
    path = dev_env_file()

    assert path is not None
    assert path.name == ".env"
    assert (path.parent / "pyproject.toml").is_file()


def test_dev_env_file_is_none_outside_a_source_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installed = tmp_path / "site-packages" / "fairshuffle" / "config.py"
    monkeypatch.setattr(config, "__file__", str(installed))

    assert dev_env_file() is None


def test_the_built_app_reads_the_env_next_to_its_exe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "FairShuffle" / "FairShuffle.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    assert dev_env_file() == exe.parent.resolve() / ".env"


def test_the_built_app_takes_the_client_id_from_that_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "FairShuffle"
    folder.mkdir()
    (folder / ".env").write_text("SPOTIFY_CLIENT_ID=fake-client-id-from-exe-folder\n")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / "FairShuffle.exe"))

    assert load_settings(dev_env_file()).client_id == "fake-client-id-from-exe-folder"


def test_the_built_app_says_where_its_env_goes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "FairShuffle.exe"))

    with pytest.raises(ConfigError, match=r"a \.env file next to FairShuffle\.exe"):
        load_settings(dev_env_file())
