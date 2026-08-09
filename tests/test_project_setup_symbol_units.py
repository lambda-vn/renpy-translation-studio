"""Tests for ProjectSetupView._validate_symbol_only_units."""

from pathlib import Path

import pytest

from app.views.project_setup import ProjectSetupView
from core.storage.database import Database
from core.storage.repositories import TranslationUnitRepository


@pytest.fixture
def repo(tmp_path: Path) -> TranslationUnitRepository:
    """Return a repository backed by a fresh database."""
    db = Database(tmp_path / "translations.db")
    db.connect()
    return TranslationUnitRepository(db.conn, db.lock)


def _insert(repo: TranslationUnitRepository, block_id: str, source_text: str) -> None:
    """Insert a single dialogue unit with the given source text."""
    repo.bulk_insert(
        [
            {
                "block_id": block_id,
                "source_file": "script.rpy",
                "source_line": 1,
                "character_variable": None,
                "source_text": source_text,
            }
        ]
    )


def _status(repo: TranslationUnitRepository, block_id: str) -> tuple[str, str | None]:
    """Return the (status, translated_text) pair stored for a block."""
    unit = next(u for u in repo.get_all() if u.block_id == block_id)
    return unit.status, unit.translated_text


def test_symbol_only_unit_is_validated(repo: TranslationUnitRepository) -> None:
    _insert(repo, "block_a", "...!?")
    ProjectSetupView._validate_symbol_only_units(repo)
    assert _status(repo, "block_a") == ("human_validated", "...!?")


def test_tag_only_unit_is_validated(repo: TranslationUnitRepository) -> None:
    _insert(repo, "block_a", "...{w=0.5}")
    ProjectSetupView._validate_symbol_only_units(repo)
    assert _status(repo, "block_a") == ("human_validated", "...{w=0.5}")


def test_translatable_unit_is_untouched(repo: TranslationUnitRepository) -> None:
    _insert(repo, "block_a", "Hello!")
    ProjectSetupView._validate_symbol_only_units(repo)
    assert _status(repo, "block_a") == ("not_translated", "")


def test_legacy_ai_suggested_copy_is_upgraded(repo: TranslationUnitRepository) -> None:
    _insert(repo, "block_a", "1234")
    repo.update_translation("block_a", "1234", "ai_suggested")
    ProjectSetupView._validate_symbol_only_units(repo)
    assert _status(repo, "block_a") == ("human_validated", "1234")


def test_hand_edited_unit_is_untouched(repo: TranslationUnitRepository) -> None:
    _insert(repo, "block_a", "1,000")
    repo.update_translation("block_a", "1 000", "ai_suggested")
    ProjectSetupView._validate_symbol_only_units(repo)
    assert _status(repo, "block_a") == ("ai_suggested", "1 000")
