"""Tests for ProjectSetupView._read_resume_info error handling."""

from pathlib import Path

from app.views.project_setup import ProjectSetupView
from core.storage.database import Database
from core.storage.repositories import TranslationUnitRepository


def _make_legacy_project(
    tmp_path: Path, db_block_ids: list[str], drop_meta: bool
) -> Path:
    """Create a project database seeded with units, optionally sans metadata."""
    project = tmp_path / "game_x"
    (project / ".rts").mkdir(parents=True)
    db = Database(project / ".rts" / "translations.db")
    db.connect()
    TranslationUnitRepository(db.conn, db.lock).bulk_insert(
        [
            {
                "block_id": bid,
                "source_file": "script.rpy",
                "source_line": 1,
                "character_variable": None,
                "source_text": "Hello",
            }
            for bid in db_block_ids
        ]
    )
    if drop_meta:
        db.conn.execute("DROP TABLE project_meta")
        db.conn.commit()
    db.close()
    return project


def _write_tl(project: Path, lang: str, block_ids: list[str]) -> None:
    """Write a minimal tl/<lang> folder holding the given dialogue blocks."""
    tl_dir = project / "game" / "tl" / lang
    tl_dir.mkdir(parents=True)
    lines: list[str] = []
    for bid in block_ids:
        lines.append(f"translate {lang} {bid}:")
        lines.append("")
        lines.append('    # e "Hello"')
        lines.append('    e "Bonjour"')
        lines.append("")
    (tl_dir / "script.rpy").write_text("\n".join(lines), encoding="utf-8")


def test_missing_database_returns_none(tmp_path: Path) -> None:
    assert ProjectSetupView._read_resume_info(tmp_path) is None


def test_corrupt_database_returns_none(tmp_path: Path) -> None:
    db_path = tmp_path / ".rts" / "translations.db"
    db_path.parent.mkdir()
    db_path.write_bytes(b"this is not a sqlite database")
    assert ProjectSetupView._read_resume_info(tmp_path) is None


def test_legacy_matching_tl_is_resumable(tmp_path: Path) -> None:
    project = _make_legacy_project(tmp_path, ["block_a"], drop_meta=True)
    _write_tl(project, "french", ["block_a"])
    info = ProjectSetupView._read_resume_info(project)
    assert info is not None
    assert info.target_language == "french"


def test_legacy_foreign_tl_is_rejected(tmp_path: Path) -> None:
    project = _make_legacy_project(tmp_path, ["block_a"], drop_meta=True)
    _write_tl(project, "french", ["block_z"])
    assert ProjectSetupView._read_resume_info(project) is None


def test_legacy_non_utf8_tl_returns_none(tmp_path: Path) -> None:
    project = _make_legacy_project(tmp_path, ["block_a"], drop_meta=True)
    tl_dir = project / "game" / "tl" / "french"
    tl_dir.mkdir(parents=True)
    (tl_dir / "script.rpy").write_bytes(
        b'translate french block_a:\n    e "Bonjour \xe9"\n'
    )
    assert ProjectSetupView._read_resume_info(project) is None
