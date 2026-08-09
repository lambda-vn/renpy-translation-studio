"""Tests for core/export_sync.py."""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.export_sync import (
    META_SAVED_AT,
    check_sync,
    latest_rpy_mtime,
    record_save,
)
from core.storage.database import Database
from core.storage.repositories import ProjectMetaRepository, TranslationUnitRepository

_PAST = "2000-01-01 00:00:00"
_FUTURE = "2999-01-01 00:00:00"

Repos = tuple[ProjectMetaRepository, TranslationUnitRepository, sqlite3.Connection]


@pytest.fixture()
def repos(tmp_path: Path) -> Iterator[Repos]:
    """Provide both repositories and the connection backing them."""
    db = Database(tmp_path / "test.db")
    db.connect()
    yield (
        ProjectMetaRepository(db.conn, db.lock),
        TranslationUnitRepository(db.conn, db.lock),
        db.conn,
    )
    db.close()


def _make_tl_dir(root: Path) -> Path:
    """Create a tl directory holding one generated translation file."""
    tl_dir = root / "tl" / "french"
    tl_dir.mkdir(parents=True)
    (tl_dir / "script.rpy").write_text("translate french strings:\n", encoding="utf-8")
    return tl_dir


def _add_unit(units: TranslationUnitRepository, block_id: str) -> None:
    """Insert a single untranslated unit."""
    units.bulk_insert(
        [
            {
                "block_id": block_id,
                "source_file": "game/script.rpy",
                "source_line": 1,
                "character_variable": "e",
                "source_text": "Hello",
            }
        ]
    )


def _backdate_creation(conn: sqlite3.Connection, block_id: str) -> None:
    """Move a unit's creation time back so its later edits stand out."""
    conn.execute(
        "UPDATE translation_units SET created_at = ? WHERE block_id = ?",
        (_PAST, block_id),
    )
    conn.commit()


def test_latest_rpy_mtime_without_files(tmp_path: Path) -> None:
    assert latest_rpy_mtime(tmp_path) == 0.0


def test_latest_rpy_mtime_ignores_other_extensions(tmp_path: Path) -> None:
    tl_dir = _make_tl_dir(tmp_path)
    rpy_mtime = (tl_dir / "script.rpy").stat().st_mtime
    compiled = tl_dir / "script.rpyc"
    compiled.write_bytes(b"")
    os.utime(compiled, (rpy_mtime + 100, rpy_mtime + 100))

    assert latest_rpy_mtime(tl_dir) == rpy_mtime


def test_check_sync_reports_never_saved(tmp_path: Path, repos: Repos) -> None:
    meta, units, _ = repos
    tl_dir = _make_tl_dir(tmp_path)

    state = check_sync(tl_dir, meta, units)

    assert state.never_saved
    assert not state.in_sync


def test_record_save_marks_files_in_sync(tmp_path: Path, repos: Repos) -> None:
    meta, units, _ = repos
    tl_dir = _make_tl_dir(tmp_path)
    _add_unit(units, "start_1")
    units.update_translation("start_1", "Bonjour", "human_validated")

    record_save(meta, tl_dir)

    assert check_sync(tl_dir, meta, units).in_sync


def test_check_sync_counts_units_edited_after_save(
    tmp_path: Path, repos: Repos
) -> None:
    meta, units, _ = repos
    tl_dir = _make_tl_dir(tmp_path)
    record_save(meta, tl_dir)
    meta.set(META_SAVED_AT, _PAST)
    _add_unit(units, "start_1")
    units.update_translation("start_1", "Bonjour", "ai_suggested")

    state = check_sync(tl_dir, meta, units)

    assert state.unsaved_units == 1
    assert not state.in_sync


def test_check_sync_counts_cleared_units(tmp_path: Path, repos: Repos) -> None:
    meta, units, conn = repos
    tl_dir = _make_tl_dir(tmp_path)
    _add_unit(units, "start_1")
    units.update_translation("start_1", "Bonjour", "human_validated")
    _backdate_creation(conn, "start_1")
    record_save(meta, tl_dir)
    meta.set(META_SAVED_AT, _PAST)
    units.clear_translations()

    assert check_sync(tl_dir, meta, units).unsaved_units == 1


def test_check_sync_ignores_freshly_extracted_units(
    tmp_path: Path, repos: Repos
) -> None:
    meta, units, _ = repos
    tl_dir = _make_tl_dir(tmp_path)
    record_save(meta, tl_dir)
    meta.set(META_SAVED_AT, _PAST)
    _add_unit(units, "start_1")

    assert check_sync(tl_dir, meta, units).unsaved_units == 0


def test_check_sync_ignores_units_edited_before_save(
    tmp_path: Path, repos: Repos
) -> None:
    meta, units, _ = repos
    tl_dir = _make_tl_dir(tmp_path)
    _add_unit(units, "start_1")
    units.update_translation("start_1", "Bonjour", "human_validated")
    record_save(meta, tl_dir)
    meta.set(META_SAVED_AT, _FUTURE)

    assert check_sync(tl_dir, meta, units).unsaved_units == 0


def test_check_sync_detects_external_edit(tmp_path: Path, repos: Repos) -> None:
    meta, units, _ = repos
    tl_dir = _make_tl_dir(tmp_path)
    record_save(meta, tl_dir)
    edited = tl_dir / "script.rpy"
    later = edited.stat().st_mtime + 10
    os.utime(edited, (later, later))

    state = check_sync(tl_dir, meta, units)

    assert state.externally_modified
    assert not state.in_sync
