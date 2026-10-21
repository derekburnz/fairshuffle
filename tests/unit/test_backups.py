"""Backups are saved and checked before a shuffle, kept per playlist and give back the old order."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from fairshuffle.spotify.models import PlaylistItem
from fairshuffle.storage import backups, paths
from fairshuffle.storage.backups import Backup, BackupError

LOCAL = "spotify:local:Fake+Artist:Fake+Album:Fake+Song:215"


def item(
    position: int, uri: str | None, kind: str | None = "track", local: bool = False
) -> PlaylistItem:
    return PlaylistItem(position=position, uri=uri, kind=kind, is_local=local)


def mixed() -> list[PlaylistItem]:
    return [
        item(0, "spotify:track:fake0001"),
        item(1, "spotify:episode:fake0002", "episode"),
        item(2, LOCAL, local=True),
        item(3, None, None),
        item(4, "spotify:track:fake0001"),  # the same song again
    ]


def test_a_backup_reads_back_exactly() -> None:
    saved = backups.save("fakelist", "fake-snapshot-1", mixed())

    assert backups.newest("fakelist") == saved
    assert saved.items == tuple(mixed())


def test_backups_live_under_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))

    backups.save("fakelist", "fake-snapshot-1", mixed())

    (path,) = (tmp_path / "FairShuffle" / "backups").iterdir()
    assert path.name.startswith("fakelist-")
    assert not list(path.parent.glob(".tmp-*"))  # the temp file was swapped in, not left over


def test_without_app_data_the_usual_folder_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert paths.backup_dir() == tmp_path / "AppData" / "Roaming" / "FairShuffle" / "backups"


def test_the_file_holds_only_the_order() -> None:
    backups.save("fakelist", "fake-snapshot-1", mixed())

    (path,) = paths.backup_dir().iterdir()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"format", "playlist_id", "snapshot_id", "saved_at", "items"}
    assert set(data["items"][0]) == {"uri", "kind", "is_local"}


def test_the_newest_backup_wins_and_old_ones_are_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backups, "KEEP_PER_PLAYLIST", 3)
    saved = [backups.save("fakelist", f"fake-snapshot-{n}", mixed()) for n in range(5)]
    backups.save("otherlist", "fake-snapshot-x", mixed())

    assert backups.newest("fakelist") == saved[-1]
    assert len(list(paths.backup_dir().glob("fakelist-*.json"))) == 3
    assert len(list(paths.backup_dir().glob("otherlist-*.json"))) == 1


def test_no_backup_yet_is_none() -> None:
    assert backups.newest("fakelist") is None


def test_a_damaged_newest_file_falls_back_to_the_one_before() -> None:
    first = backups.save("fakelist", "fake-snapshot-1", mixed())
    backups.save("fakelist", "fake-snapshot-2", mixed())
    newest_path = sorted(paths.backup_dir().glob("fakelist-*.json"))[-1]
    newest_path.write_text("{not json", encoding="utf-8")

    assert backups.newest("fakelist") == first


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(format=2),
        lambda d: d.update(playlist_id="../evil"),
        lambda d: d.update(snapshot_id=5),
        lambda d: d.update(items="nope"),
        lambda d: d.update(saved_at="yesterday"),
        lambda d: d["items"][0].update(uri="https://example.invalid/"),
        lambda d: d["items"][0].update(kind="album"),
        lambda d: d["items"][0].update(is_local="no"),
        lambda d: d["items"][0].pop("uri"),
    ],
    ids=[
        "format",
        "playlist_id",
        "snapshot_id",
        "items",
        "saved_at",
        "uri",
        "kind",
        "is_local",
        "missing_uri",
    ],
)
def test_a_tampered_file_is_refused(change: Callable[[dict[str, Any]], object]) -> None:
    backups.save("fakelist", "fake-snapshot-1", mixed())
    (path,) = paths.backup_dir().iterdir()
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BackupError):
        backups.load(path)
    assert backups.newest("fakelist") is None


@pytest.mark.parametrize("bad_id", ["", "../me", "fake/list", "fake.list", "x" * 65])
def test_a_bad_playlist_id_never_becomes_a_path(bad_id: str) -> None:
    with pytest.raises(ValueError, match="playlist ID"):
        backups.save(bad_id, "fake-snapshot-1", mixed())
    with pytest.raises(ValueError, match="playlist ID"):
        backups.newest(bad_id)


def test_a_failed_save_raises_and_logs_no_path(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Access is denied", r"C:\Users\someone\AppData\Roaming")

    monkeypatch.setattr(backups, "_write_atomically", refuse)

    with caplog.at_level(logging.DEBUG), pytest.raises(BackupError) as raised:
        backups.save("fakelist", "fake-snapshot-1", mixed())

    assert raised.value.__cause__ is None
    assert "someone" not in caplog.text
    assert "someone" not in str(raised.value)


def test_a_backup_that_reads_back_wrong_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    real_load = backups.load

    def corrupted(path: Path) -> Backup:
        loaded = real_load(path)
        return Backup(loaded.playlist_id, loaded.snapshot_id, loaded.saved_at, loaded.items[1:])

    monkeypatch.setattr(backups, "load", corrupted)

    with pytest.raises(BackupError, match="read back"):
        backups.save("fakelist", "fake-snapshot-1", mixed())


def test_a_failed_temp_write_leaves_nothing_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(backups.os, "replace", fail)

    with pytest.raises(BackupError):
        backups.save("fakelist", "fake-snapshot-1", mixed())
    assert list(paths.backup_dir().iterdir()) == []


# Undo in keep-order mode -------------------------------------------------------------------


def test_restore_target_puts_the_old_order_back() -> None:
    saved = backups.save("fakelist", "fake-snapshot-1", mixed())
    shuffled_now = [mixed()[k] for k in (3, 0, 4, 2, 1)]
    current = [
        item(n, entry.uri, entry.kind, entry.is_local) for n, entry in enumerate(shuffled_now)
    ]

    target = backups.restore_target(saved, current)

    assert target is not None
    assert [current[k].uri for k in target] == [entry.uri for entry in mixed()]
    assert sorted(target) == list(range(5))


def test_duplicates_come_back_in_their_old_order() -> None:
    saved = backups.save("fakelist", "fake-snapshot-1", [item(0, "spotify:track:a")] * 3)

    assert backups.restore_target(saved, [item(n, "spotify:track:a") for n in range(3)]) == [
        0,
        1,
        2,
    ]


@pytest.mark.parametrize(
    "current",
    [
        [item(0, "spotify:track:fake0001")],  # entries were removed
        [*mixed(), item(5, "spotify:track:new")],  # an entry was added
        [item(n, "spotify:track:other") for n in range(5)],  # different songs
    ],
)
def test_a_changed_playlist_cant_be_restored_by_reordering(current: list[PlaylistItem]) -> None:
    saved = backups.save("fakelist", "fake-snapshot-1", mixed())

    assert backups.restore_target(saved, current) is None
