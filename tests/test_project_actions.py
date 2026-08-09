"""Tests for core/project_actions.py."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from core import project_actions
from core.storage.database import Database
from core.storage.repositories import (
    CharacterRepository,
    TranslationUnitRepository,
)
from core.storage.translation_memory import TranslationMemory


@pytest.fixture()
def repo(tmp_path: Path) -> Iterator[TranslationUnitRepository]:
    """Provide a fresh translation repository backed by a throwaway file."""
    db = Database(tmp_path / "project.db")
    db.connect()
    yield TranslationUnitRepository(db.conn)
    db.close()


@pytest.fixture()
def characters(tmp_path: Path) -> Iterator[CharacterRepository]:
    """Provide a fresh character repository backed by a throwaway file."""
    db = Database(tmp_path / "characters.db")
    db.connect()
    yield CharacterRepository(db.conn)
    db.close()


@pytest.fixture()
def memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TranslationMemory]:
    """Replace the shared memory singleton with a throwaway one."""
    store = TranslationMemory(tmp_path / "memory.db")
    monkeypatch.setattr(project_actions, "translation_memory", store)
    yield store
    store.close()


def _unit(block_id: str, source_text: str) -> dict[str, object]:
    return {
        "block_id": block_id,
        "source_file": "game/script.rpy",
        "source_line": 1,
        "character_variable": None,
        "source_text": source_text,
    }


def test_fill_from_memory_fills_an_exact_match(
    repo: TranslationUnitRepository, memory: TranslationMemory
) -> None:
    repo.bulk_insert([_unit("a", "Hello")])
    memory.remember([("Hello", "Bonjour")], "english", "french")

    filled = project_actions.fill_from_memory(
        repo, source_language="english", target_language="french"
    )

    unit = repo.get_all()[0]
    assert filled == 1
    assert unit.translated_text == "Bonjour"
    assert unit.status == "imported"


def test_fill_from_memory_leaves_a_validated_line_alone(
    repo: TranslationUnitRepository, memory: TranslationMemory
) -> None:
    """A line someone already read must survive the fill untouched.

    update_translations() refuses to downgrade a human_validated unit, and
    the fill only asks for not_translated ones, so this holds twice over.
    """
    repo.bulk_insert([_unit("a", "Hello")])
    repo.update_translation("a", "Salut", "human_validated")
    memory.remember([("Hello", "Bonjour")], "english", "french")

    filled = project_actions.fill_from_memory(
        repo, source_language="english", target_language="french"
    )

    assert filled == 0
    assert repo.get_all()[0].translated_text == "Salut"


def test_fill_from_memory_is_scoped_to_the_language_pair(
    repo: TranslationUnitRepository, memory: TranslationMemory
) -> None:
    repo.bulk_insert([_unit("a", "Hello")])
    memory.remember([("Hello", "Bonjour")], "english", "french")

    filled = project_actions.fill_from_memory(
        repo, source_language="english", target_language="spanish"
    )

    assert filled == 0
    assert repo.get_all()[0].status == "not_translated"


def test_fill_from_memory_returns_zero_on_an_empty_memory(
    repo: TranslationUnitRepository, memory: TranslationMemory
) -> None:
    repo.bulk_insert([_unit("a", "Hello")])

    assert (
        project_actions.fill_from_memory(
            repo, source_language="english", target_language="french"
        )
        == 0
    )


def _write_game(root: Path, source: str) -> Path:
    game = root / "game"
    game.mkdir(parents=True)
    (game / "script.rpy").write_text(source, encoding="utf-8")
    return root


def test_detect_and_store_characters_saves_what_it_finds(
    characters: CharacterRepository, tmp_path: Path
) -> None:
    project = _write_game(
        tmp_path,
        'define e = Character("Eileen")\ndefine m = Character("Marc")\n',
    )

    count = project_actions.detect_and_store_characters(characters, project)

    stored = {c.variable: c.display_name for c in characters.get_all()}
    assert count == 2
    assert stored == {"e": "Eileen", "m": "Marc"}


def test_detect_and_store_characters_keeps_the_notes(
    characters: CharacterRepository, tmp_path: Path
) -> None:
    """A second scan must not wipe what no scan can produce.

    Notes carry the gender and register the providers rely on, and they
    are the one field a user types by hand.
    """
    project = _write_game(tmp_path, 'define e = Character("Eileen")\n')
    project_actions.detect_and_store_characters(characters, project)
    characters.update_notes("e", "female, informal")

    project_actions.detect_and_store_characters(characters, project)

    assert characters.get_all()[0].notes == "female, informal"


def test_detect_and_store_characters_returns_zero_without_definitions(
    characters: CharacterRepository, tmp_path: Path
) -> None:
    project = _write_game(tmp_path, 'label start:\n    "Nobody speaks."\n')

    assert project_actions.detect_and_store_characters(characters, project) == 0
    assert characters.get_all() == []
