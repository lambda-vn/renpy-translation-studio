"""Tests for handling a tl/ folder already present before extraction."""

from pathlib import Path

import pytest

from app.views.project_setup import ProjectSetupView
from core.renpy.parser import TranslationBlock
from core.storage.database import Database
from core.storage.repositories import TranslationUnitRepository


@pytest.fixture
def repo(tmp_path: Path) -> TranslationUnitRepository:
    """Return a repository backed by a fresh database."""
    db = Database(tmp_path / "translations.db")
    db.connect()
    return TranslationUnitRepository(db.conn, db.lock)


def _block(block_id: str, source: str, translated: str) -> TranslationBlock:
    """Build a dialogue block with the given source and translation."""
    return TranslationBlock(
        block_id=block_id,
        source_file="script.rpy",
        source_line=1,
        character_variable=None,
        source_text=source,
        translated_text=translated,
    )


def _insert(repo: TranslationUnitRepository, block: TranslationBlock) -> None:
    """Insert the unit matching a parsed block, without its translation."""
    repo.bulk_insert(
        [
            {
                "block_id": block.block_id,
                "source_file": block.source_file,
                "source_line": block.source_line,
                "character_variable": block.character_variable,
                "source_text": block.source_text,
            }
        ]
    )


def _status(repo: TranslationUnitRepository, block_id: str) -> tuple[str, str | None]:
    """Return the (status, translated_text) pair stored for a block."""
    unit = next(u for u in repo.get_all() if u.block_id == block_id)
    return unit.status, unit.translated_text


def _make_tl(project: Path, language: str) -> Path:
    """Create a tl/<language> folder holding one .rpy file."""
    tl_dir = project / "game" / "tl" / language
    tl_dir.mkdir(parents=True)
    (tl_dir / "script.rpy").write_text("translate french start_1:\n", encoding="utf-8")
    return tl_dir


def test_existing_tl_is_detected(tmp_path: Path) -> None:
    _make_tl(tmp_path, "french")
    assert ProjectSetupView._has_existing_tl(tmp_path, "french") is True


def test_missing_tl_is_not_detected(tmp_path: Path) -> None:
    _make_tl(tmp_path, "french")
    assert ProjectSetupView._has_existing_tl(tmp_path, "spanish") is False


def test_empty_tl_folder_is_not_detected(tmp_path: Path) -> None:
    (tmp_path / "game" / "tl" / "french").mkdir(parents=True)
    assert ProjectSetupView._has_existing_tl(tmp_path, "french") is False


def test_disk_translation_is_imported(repo: TranslationUnitRepository) -> None:
    block = _block("block_a", "Hello!", "Bonjour !")
    _insert(repo, block)
    ProjectSetupView._import_disk_translations(repo, [block])
    assert _status(repo, "block_a") == ("imported", "Bonjour !")


def test_untranslated_copy_is_not_imported(repo: TranslationUnitRepository) -> None:
    block = _block("block_a", "Hello!", "Hello!")
    _insert(repo, block)
    ProjectSetupView._import_disk_translations(repo, [block])
    assert _status(repo, "block_a") == ("not_translated", "")


def test_empty_translation_is_not_imported(repo: TranslationUnitRepository) -> None:
    block = _block("block_a", "Hello!", "")
    _insert(repo, block)
    ProjectSetupView._import_disk_translations(repo, [block])
    assert _status(repo, "block_a") == ("not_translated", "")


def test_validated_unit_is_not_overwritten(repo: TranslationUnitRepository) -> None:
    block = _block("block_a", "Hello!", "Bonjour !")
    _insert(repo, block)
    repo.update_translation("block_a", "Salut !", "human_validated")
    ProjectSetupView._import_disk_translations(repo, [block])
    assert _status(repo, "block_a") == ("human_validated", "Salut !")


def test_archive_copies_tl_dir_out_of_game(tmp_path: Path) -> None:
    tl_dir = _make_tl(tmp_path, "french")
    ProjectSetupView._archive_tl_dir(tmp_path, tl_dir)
    archived = list((tmp_path / ".rts" / "backups").iterdir())
    assert len(archived) == 1
    assert archived[0].name.startswith("french-")
    assert (archived[0] / "script.rpy").is_file()


def test_archive_empties_the_tl_dir_without_removing_it(tmp_path: Path) -> None:
    tl_dir = _make_tl(tmp_path, "french")
    (tl_dir / "sub").mkdir()
    (tl_dir / "sub" / "common.rpy").write_text(
        "translate french b:\n", encoding="utf-8"
    )
    (tl_dir / "script.rpyc").write_bytes(b"\x00")
    ProjectSetupView._archive_tl_dir(tmp_path, tl_dir)
    assert tl_dir.is_dir()
    assert list(tl_dir.rglob("*.rpy")) == []
    assert list(tl_dir.rglob("*.rpyc")) == []


def test_archive_never_overwrites_a_previous_archive(tmp_path: Path) -> None:
    tl_dir = _make_tl(tmp_path, "french")
    ProjectSetupView._archive_tl_dir(tmp_path, tl_dir)
    (tl_dir / "script.rpy").write_text("translate french a:\n", encoding="utf-8")
    ProjectSetupView._archive_tl_dir(tmp_path, tl_dir)
    archived = list((tmp_path / ".rts" / "backups").iterdir())
    assert len(archived) == 2


def test_archive_ignores_missing_tl_dir(tmp_path: Path) -> None:
    ProjectSetupView._archive_tl_dir(tmp_path, tmp_path / "game" / "tl" / "french")
    assert not (tmp_path / ".rts").exists()
