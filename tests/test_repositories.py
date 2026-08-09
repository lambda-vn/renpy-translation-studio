"""Tests for core/repositories.py."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.storage.database import Database
from core.storage.repositories import (
    CharacterRepository,
    TranslationUnit,
    TranslationUnitRepository,
)


@pytest.fixture()
def repo(tmp_path: object) -> TranslationUnitRepository:
    """Provide a fresh in-memory repository for each test."""
    db = Database(tmp_path / "test.db")  # type: ignore[operator]
    db.connect()
    yield TranslationUnitRepository(db.conn)
    db.close()


_LEGACY_SCHEMA = """
CREATE TABLE translation_units (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id        TEXT NOT NULL UNIQUE,
    source_file     TEXT NOT NULL,
    source_line     INTEGER NOT NULL,
    character_variable TEXT,
    source_text     TEXT NOT NULL,
    translated_text TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'not_translated'
                    CHECK(status IN (
                        'not_translated', 'ai_suggested', 'human_validated'
                    )),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def test_connect_migrates_legacy_status_check(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(_LEGACY_SCHEMA)
    legacy.execute(
        "INSERT INTO translation_units"
        " (block_id, source_file, source_line, source_text, status, translated_text)"
        " VALUES ('legacy_a', 'game/script.rpy', 1, 'Hi', 'human_validated', 'Salut')"
    )
    legacy.commit()
    legacy.close()

    db = Database(db_path)
    db.connect()
    repo = TranslationUnitRepository(db.conn)
    repo.bulk_insert([_unit("legacy_b")])
    status = repo.mark_as_draft("legacy_b", "Ébauche")
    units = {u.block_id: u for u in repo.get_all()}
    db.close()

    assert status == "draft"
    assert units["legacy_b"].status == "draft"
    assert units["legacy_a"].status == "human_validated"
    assert units["legacy_a"].translated_text == "Salut"


_DRAFT_ERA_SCHEMA = _LEGACY_SCHEMA.replace(
    "'not_translated', 'ai_suggested', 'human_validated'",
    "'not_translated', 'draft', 'ai_suggested', 'human_validated'",
)


def test_connect_migrates_draft_era_status_check(tmp_path: Path) -> None:
    db_path = tmp_path / "draft_era.db"
    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(_DRAFT_ERA_SCHEMA)
    legacy.commit()
    legacy.close()

    db = Database(db_path)
    db.connect()
    repo = TranslationUnitRepository(db.conn)
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Bonjour", "imported")
    units = {u.block_id: u for u in repo.get_all()}
    db.close()

    assert units["block_a"].status == "imported"


def test_connect_adds_the_review_columns_to_an_older_database(tmp_path: Path) -> None:
    """A base predating the review flag keeps its rows and gains the columns."""
    db_path = tmp_path / "no_review.db"
    older = sqlite3.connect(str(db_path))
    older.executescript(
        _LEGACY_SCHEMA.replace(
            "'not_translated', 'ai_suggested', 'human_validated'",
            "'not_translated', 'draft', 'imported', 'ai_suggested', 'human_validated'",
        )
    )
    older.execute(
        "INSERT INTO translation_units"
        " (block_id, source_file, source_line, source_text, status, translated_text)"
        " VALUES ('old_a', 'game/script.rpy', 1, 'Hi', 'human_validated', 'Salut')"
    )
    older.commit()
    older.close()

    db = Database(db_path)
    db.connect()
    repo = TranslationUnitRepository(db.conn)
    repo.set_needs_review("old_a", True)
    repo.set_note("old_a", "A revoir")
    unit = repo.get_all()[0]
    db.close()

    assert unit.translated_text == "Salut"
    assert unit.status == "human_validated"
    assert unit.needs_review is True
    assert unit.note == "A revoir"


def test_connect_twice_leaves_the_review_columns_alone(tmp_path: Path) -> None:
    """The migration must not run again and wipe what it added last time."""
    db_path = tmp_path / "twice.db"
    db = Database(db_path)
    db.connect()
    repo = TranslationUnitRepository(db.conn)
    repo.bulk_insert([_unit("block_a")])
    repo.set_needs_review("block_a", True)
    db.close()

    reopened = Database(db_path)
    reopened.connect()
    unit = TranslationUnitRepository(reopened.conn).get_all()[0]
    reopened.close()

    assert unit.needs_review is True


def _unit(block_id: str) -> dict:
    return {
        "block_id": block_id,
        "source_file": "game/script.rpy",
        "source_line": 1,
        "character_variable": None,
        "source_text": f"Hello from {block_id}",
    }


def test_bulk_insert_populates_db(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_a"), _unit("block_b")])
    units = repo.get_all()
    assert len(units) == 2
    assert {u.block_id for u in units} == {"block_a", "block_b"}


def test_bulk_insert_ignore_on_conflict(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.bulk_insert([_unit("block_a"), _unit("block_b")])
    units = repo.get_all()
    assert len(units) == 2


def test_new_unit_status_not_translated(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_x")])
    units = repo.get_all()
    assert units[0].status == "not_translated"
    assert units[0].translated_text == ""


def test_update_translation(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Bonjour", "human_validated")
    units = repo.get_all()
    assert units[0].translated_text == "Bonjour"
    assert units[0].status == "human_validated"


def test_human_validated_cannot_be_overwritten_by_ai(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Human translation", "human_validated")
    repo.update_translation("block_a", "AI suggestion", "ai_suggested")
    units = repo.get_all()
    assert units[0].translated_text == "Human translation"
    assert units[0].status == "human_validated"


def test_human_validated_can_be_updated_by_human(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "First", "human_validated")
    repo.update_translation("block_a", "Revised", "human_validated")
    units = repo.get_all()
    assert units[0].translated_text == "Revised"


def test_mark_as_draft_stores_live_text_as_draft(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Bonjour", "human_validated")
    status = repo.mark_as_draft("block_a", "Bonjou")
    units = repo.get_all()
    assert status == "draft"
    assert units[0].status == "draft"
    assert units[0].translated_text == "Bonjou"


def test_mark_as_draft_persists_cleared_text(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Bonjour", "ai_suggested")
    status = repo.mark_as_draft("block_a", "")
    units = repo.get_all()
    assert status == "not_translated"
    assert units[0].status == "not_translated"
    assert units[0].translated_text == ""


def test_mark_as_draft_whitespace_only_is_not_translated(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    status = repo.mark_as_draft("block_a", "   ")
    assert status == "not_translated"
    assert repo.get_all()[0].status == "not_translated"


def test_mark_as_draft_bypasses_human_validated_protection(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Bonjour", "human_validated")
    repo.update_translation("block_a", "AI garbage", "ai_suggested")
    units = repo.get_all()
    assert units[0].status == "human_validated"

    repo.mark_as_draft("block_a", "Bonjour")
    units = repo.get_all()
    assert units[0].status == "draft"


def test_clear_translations_all_files(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_a"), _unit("block_b")])
    repo.update_translation("block_a", "Oui", "human_validated")
    repo.update_translation("block_b", "AI", "ai_suggested")
    count = repo.clear_translations()
    units = repo.get_all()
    assert count == 2
    assert all(u.status == "not_translated" for u in units)
    assert all(u.translated_text == "" for u in units)


def test_clear_translations_scoped_to_file(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy"),
            _unit_for_file("b", "game/chapter1.rpy"),
        ]
    )
    repo.update_translation("a", "Oui", "human_validated")
    repo.update_translation("b", "Oui", "human_validated")
    count = repo.clear_translations(source_file="game/script.rpy")
    units = {u.block_id: u for u in repo.get_all()}
    assert count == 1
    assert units["a"].status == "not_translated"
    assert units["a"].translated_text == ""
    assert units["b"].status == "human_validated"
    assert units["b"].translated_text == "Oui"


def test_clear_translations_returns_zero_when_nothing_to_clear(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    assert repo.clear_translations() == 0


def test_clear_translations_restricted_to_statuses(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("a"), _unit("b"), _unit("c")])
    repo.update_translation("a", "Oui", "human_validated")
    repo.update_translation("b", "AI", "ai_suggested")
    repo.mark_as_draft("c", "Brouillon")

    count = repo.clear_translations(statuses=["ai_suggested", "draft", "imported"])

    units = {u.block_id: u for u in repo.get_all()}
    assert count == 2
    assert units["a"].translated_text == "Oui"
    assert units["a"].status == "human_validated"
    assert units["b"].status == "not_translated"
    assert units["c"].status == "not_translated"


def test_clear_translations_clears_drafts(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.mark_as_draft("block_a", "Ébauche")
    count = repo.clear_translations()
    units = repo.get_all()
    assert count == 1
    assert units[0].status == "not_translated"
    assert units[0].translated_text == ""


def test_filter_by_status(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_a"), _unit("block_b"), _unit("block_c")])
    repo.update_translation("block_a", "Oui", "human_validated")
    validated = repo.get_all(status_filter="human_validated")
    not_translated = repo.get_all(status_filter="not_translated")
    assert len(validated) == 1
    assert len(not_translated) == 2


def test_count_by_status(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_a"), _unit("block_b"), _unit("block_c")])
    repo.update_translation("block_a", "Oui", "human_validated")
    counts = repo.count_by_status()
    assert counts.get("human_validated") == 1
    assert counts.get("not_translated") == 2


def test_get_all_returns_dataclass(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_x")])
    units = repo.get_all()
    assert isinstance(units[0], TranslationUnit)


def _unit_for_file(block_id: str, source_file: str, line: int = 1) -> dict:
    return {
        "block_id": block_id,
        "source_file": source_file,
        "source_line": line,
        "character_variable": None,
        "source_text": f"Text {block_id}",
    }


def test_get_files_returns_all_files(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy"),
            _unit_for_file("b", "game/chapter1.rpy"),
        ]
    )
    files = repo.get_files()
    names = [f["source_file"] for f in files]
    assert "game/script.rpy" in names
    assert "game/chapter1.rpy" in names


def test_get_files_counts(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy"),
            _unit_for_file("b", "game/script.rpy"),
            _unit_for_file("c", "game/script.rpy"),
        ]
    )
    repo.update_translation("a", "Traduction", "human_validated")
    repo.mark_as_draft("b", "Ébauche")
    files = repo.get_files()
    assert len(files) == 1
    f = files[0]
    assert f["total"] == 3
    assert f["validated"] == 1
    assert f["draft"] == 1


def test_get_files_counts_imported(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy"),
            _unit_for_file("b", "game/script.rpy"),
        ]
    )
    repo.update_translation("a", "Traduction", "imported")
    files = repo.get_files()
    assert files[0]["imported"] == 1


def test_project_progress_counts_lines_and_words(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_with_text("a", "Three little words"),
            _unit_with_text("b", "Two words", 2),
        ]
    )
    repo.update_translation("a", "Trois petits mots", "human_validated")
    progress = repo.project_progress()
    assert progress["lines"] == 2
    assert progress["validated_lines"] == 1
    assert progress["words"] == 5
    assert progress["validated_words"] == 3


def test_project_progress_on_an_empty_project(
    repo: TranslationUnitRepository,
) -> None:
    progress = repo.project_progress()
    assert progress == {
        "lines": 0,
        "validated_lines": 0,
        "words": 0,
        "validated_words": 0,
    }


def test_get_neighbours_returns_the_window_around_the_line(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [_unit_for_file(str(line), "game/script.rpy", line) for line in (1, 2, 3, 4, 5)]
    )
    neighbours = repo.get_neighbours("game/script.rpy", 3, 1)
    assert [u.source_line for u in neighbours] == [2, 3, 4]


def test_get_neighbours_stops_at_the_file_edges(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy", 1),
            _unit_for_file("b", "game/script.rpy", 2),
            _unit_for_file("c", "game/other.rpy", 3),
        ]
    )
    neighbours = repo.get_neighbours("game/script.rpy", 1, 2)
    assert [u.source_line for u in neighbours] == [1, 2]


def test_get_neighbours_keeps_the_line_it_is_centred_on(
    repo: TranslationUnitRepository,
) -> None:
    """The panel marks the current line, so it has to be in the window."""
    repo.bulk_insert(
        [_unit_for_file(str(line), "game/script.rpy", line) for line in (1, 2, 3)]
    )
    neighbours = repo.get_neighbours("game/script.rpy", 2, 1)
    assert [u.block_id for u in neighbours] == ["1", "2", "3"]


def _unit_with_text(block_id: str, source_text: str, line: int = 1) -> dict:
    return {
        "block_id": block_id,
        "source_file": "game/script.rpy",
        "source_line": line,
        "character_variable": None,
        "source_text": source_text,
    }


def test_delete_stale_drops_blocks_absent_from_the_game(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("kept"), _unit("removed")])
    repo.update_translation("removed", "Bonjour", "imported")
    deleted = repo.delete_stale({"kept"})
    assert deleted == 1
    assert [u.block_id for u in repo.get_all()] == ["kept"]


def test_delete_stale_drops_validated_blocks_too(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("kept"), _unit("removed")])
    repo.update_translation("removed", "Bonjour", "human_validated")
    deleted = repo.delete_stale({"kept"})
    assert deleted == 1
    assert [u.block_id for u in repo.get_all()] == ["kept"]


def test_transfer_moves_translation_to_the_new_block_id(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [_unit_with_text("old_id", "Hello"), _unit_with_text("new_id", "Hello", 2)]
    )
    repo.update_translation("old_id", "Bonjour", "human_validated")
    moved = repo.transfer_orphan_translations({"new_id"})
    units = {u.block_id: u for u in repo.get_all()}
    assert moved == 1
    assert units["new_id"].translated_text == "Bonjour"
    assert units["new_id"].status == "human_validated"


def test_transfer_fills_every_block_sharing_the_source_text(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_with_text("old_id", "Yes"),
            _unit_with_text("new_a", "Yes", 2),
            _unit_with_text("new_b", "Yes", 3),
        ]
    )
    repo.update_translation("old_id", "Oui", "imported")
    moved = repo.transfer_orphan_translations({"new_a", "new_b"})
    units = {u.block_id: u for u in repo.get_all()}
    assert moved == 2
    assert units["new_a"].translated_text == "Oui"
    assert units["new_b"].translated_text == "Oui"


def test_transfer_keeps_the_status_when_a_single_line_inherits(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [_unit_with_text("old_id", "Hello"), _unit_with_text("new_id", "Hello", 2)]
    )
    repo.update_translation("old_id", "Bonjour", "human_validated")
    repo.transfer_orphan_translations({"new_id"})
    units = {u.block_id: u for u in repo.get_all()}
    assert units["new_id"].status == "human_validated"


def test_transfer_downgrades_a_translation_spread_over_several_lines(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_with_text("old_id", "Yes"),
            _unit_with_text("new_a", "Yes", 2),
            _unit_with_text("new_b", "Yes", 3),
        ]
    )
    repo.update_translation("old_id", "Oui", "human_validated")
    repo.transfer_orphan_translations({"new_a", "new_b"})
    units = {u.block_id: u for u in repo.get_all()}
    assert units["new_a"].status == "imported"
    assert units["new_b"].status == "imported"
    assert units["new_a"].translated_text == "Oui"


def test_delete_stale_keeps_everything_when_the_parse_is_truncated(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit(f"block_{i}") for i in range(4)])
    repo.update_translation("block_3", "Bonjour", "human_validated")
    deleted = repo.delete_stale({"block_0"})
    assert deleted == 0
    assert len(repo.get_all()) == 4


def _unit_in_file(block_id: str, source_text: str, source_file: str) -> dict:
    return {
        "block_id": block_id,
        "source_file": source_file,
        "source_line": 1,
        "character_variable": None,
        "source_text": source_text,
    }


def test_count_duplicates_splits_this_file_from_the_others(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_in_file("a", "Yes", "game/a.rpy"),
            _unit_in_file("b", "Yes", "game/a.rpy"),
            _unit_in_file("c", "Yes", "game/b.rpy"),
            _unit_in_file("d", "Yes", "game/c.rpy"),
        ]
    )
    stats = repo.count_duplicates(["Yes"], "game/a.rpy")
    assert stats["Yes"]["total"] == 4
    assert stats["Yes"]["other_files"] == 2


def test_count_duplicates_ignores_texts_occurring_once(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_in_file("a", "Unique", "game/a.rpy"),
            _unit_in_file("b", "Twice", "game/a.rpy"),
            _unit_in_file("c", "Twice", "game/b.rpy"),
        ]
    )
    stats = repo.count_duplicates(["Unique", "Twice"], "game/a.rpy")
    assert list(stats) == ["Twice"]


def test_count_duplicates_without_texts_queries_nothing(
    repo: TranslationUnitRepository,
) -> None:
    assert repo.count_duplicates([], "game/a.rpy") == {}


def test_count_matches_by_file_counts_every_file(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_in_file("a", "Yes sir", "game/a.rpy"),
            _unit_in_file("b", "Yes", "game/b.rpy"),
            _unit_in_file("c", "No", "game/b.rpy"),
        ]
    )
    assert repo.count_matches_by_file("Yes") == {"game/a.rpy": 1, "game/b.rpy": 1}


def test_count_matches_by_file_obeys_the_status_filter(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_in_file("a", "Yes", "game/a.rpy"),
            _unit_in_file("b", "Yes", "game/b.rpy"),
        ]
    )
    repo.update_translation("b", "Oui", "human_validated")
    assert repo.count_matches_by_file("Yes", "not_translated") == {"game/a.rpy": 1}


def test_count_matches_by_file_is_empty_without_a_query(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit_in_file("a", "Yes", "game/a.rpy")])
    assert repo.count_matches_by_file("   ") == {}


def test_count_matches_by_file_maps_a_speaker_on_its_own(
    repo: TranslationUnitRepository,
) -> None:
    """The panel must say where a speaker talks, query or no query."""
    repo.bulk_insert(
        [
            _unit_for_speaker("a", "m", 1),
            _unit_for_speaker("b", "marie", 2),
            _unit_for_speaker("c", "m", 3, source_file="game/chapter1.rpy"),
        ]
    )

    assert repo.count_matches_by_file("", character="m") == {
        "game/script.rpy": 1,
        "game/chapter1.rpy": 1,
    }


def test_count_matches_by_file_combines_a_speaker_and_a_query(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            {**_unit_for_speaker("a", "m", 1), "source_text": "Yes sir"},
            {**_unit_for_speaker("b", "m", 2), "source_text": "No"},
            {
                **_unit_for_speaker("c", "marie", 3, source_file="game/chapter1.rpy"),
                "source_text": "Yes",
            },
        ]
    )

    assert repo.count_matches_by_file("Yes", character="m") == {"game/script.rpy": 1}


def test_needs_review_and_note_survive_a_reread(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.set_needs_review("block_a", True)
    repo.set_note("block_a", "Jeu de mots sur 'light'")

    unit = repo.get_all()[0]
    assert unit.needs_review is True
    assert unit.note == "Jeu de mots sur 'light'"


def test_clearing_a_note_leaves_nothing_behind(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.set_note("block_a", "A trancher")
    repo.set_note("block_a", "")

    assert repo.get_all()[0].note is None


def test_writing_a_note_flags_the_line(repo: TranslationUnitRepository) -> None:
    """Nothing lists notes, so an unflagged one could never be found again."""
    repo.bulk_insert([_unit("block_a")])
    repo.set_note("block_a", "Jeu de mots a trancher")

    assert repo.get_all()[0].needs_review is True


def test_clearing_a_note_leaves_the_flag_up(repo: TranslationUnitRepository) -> None:
    """A line stays flagged without a reason: marking and moving on is the point."""
    repo.bulk_insert([_unit("block_a")])
    repo.set_note("block_a", "A trancher")
    repo.set_note("block_a", "")

    assert repo.get_all()[0].needs_review is True


def test_the_review_flag_outlives_a_translation_job(
    repo: TranslationUnitRepository,
) -> None:
    """A mark set by hand is not a status: nothing automatic may clear it."""
    repo.bulk_insert([_unit("block_a")])
    repo.set_needs_review("block_a", True)
    repo.update_translation("block_a", "Bonjour", "ai_suggested")

    unit = repo.get_all()[0]
    assert unit.status == "ai_suggested"
    assert unit.needs_review is True


def test_a_note_does_not_count_as_a_line_left_to_write(tmp_path: Path) -> None:
    """Flagging a line changes nothing on disk, so the save counter ignores it.

    The row is backdated by hand rather than timed, the stored timestamp
    having a one-second resolution no test can wait out reliably.
    """
    db = Database(tmp_path / "notes.db")
    db.connect()
    repo = TranslationUnitRepository(db.conn)
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Bonjour", "human_validated")
    db.conn.execute("UPDATE translation_units SET updated_at = '2000-01-01 00:00:00'")
    db.conn.commit()
    saved_at = "2000-06-01 00:00:00"

    repo.set_note("block_a", "A revoir avec le client")
    repo.set_needs_review("block_a", True)
    assert repo.count_modified_since(saved_at) == 0

    repo.update_translation("block_a", "Salut", "human_validated")
    assert repo.count_modified_since(saved_at) == 1
    db.close()


def test_a_project_never_saved_counts_every_line_carrying_work(
    repo: TranslationUnitRepository,
) -> None:
    """Without a save marker there is no lower bound, so all work is pending."""
    repo.bulk_insert([_unit("block_a"), _unit("block_b")])
    assert repo.count_modified_since(None) == 0

    repo.update_translation("block_a", "Bonjour", "human_validated")
    assert repo.count_modified_since(None) == 1

    repo.update_translation("block_b", "Salut", "ai_suggested")
    assert repo.count_modified_since(None) == 2


def test_get_page_keeps_only_the_flagged_lines(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_with_text("block_a", "Yes"),
            _unit_with_text("block_b", "No", 2),
        ]
    )
    repo.set_needs_review("block_b", True)

    units, total = repo.get_page("game/script.rpy", 0, 50, needs_review=True)
    assert total == 1
    assert [u.block_id for u in units] == ["block_b"]


def test_count_matches_by_file_maps_the_flagged_lines(
    repo: TranslationUnitRepository,
) -> None:
    """Flags spread over the project, so the panel has to say which files hold them."""
    repo.bulk_insert(
        [
            _unit_in_file("a", "Yes", "game/a.rpy"),
            _unit_in_file("b", "No", "game/b.rpy"),
            _unit_in_file("c", "Maybe", "game/b.rpy"),
        ]
    )
    repo.set_needs_review("a", True)
    repo.set_needs_review("c", True)

    assert repo.count_matches_by_file("", needs_review=True) == {
        "game/a.rpy": 1,
        "game/b.rpy": 1,
    }


def test_find_duplicates_returns_the_other_lines_with_the_same_text(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_with_text("block_a", "Yes"),
            _unit_with_text("block_b", "Yes", 2),
            _unit_with_text("block_c", "No", 3),
        ]
    )
    assert repo.find_duplicate_block_ids("Yes", "block_a") == ["block_b"]


def test_find_duplicates_skips_validated_lines(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_with_text("block_a", "Yes"),
            _unit_with_text("block_b", "Yes", 2),
            _unit_with_text("block_c", "Yes", 3),
        ]
    )
    repo.update_translation("block_b", "Oui", "human_validated")
    repo.update_translation("block_c", "Ouais", "ai_suggested")
    assert repo.find_duplicate_block_ids("Yes", "block_a") == ["block_c"]


def test_update_translations_writes_a_whole_batch(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a"), _unit("block_b")])
    updated = repo.update_translations(
        [("block_a", "Bonjour", "imported"), ("block_b", "Salut", "imported")]
    )
    units = {u.block_id: u for u in repo.get_all()}
    assert updated == 2
    assert units["block_a"].translated_text == "Bonjour"
    assert units["block_b"].status == "imported"


def test_update_translations_never_downgrades_a_validated_unit(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Salut", "human_validated")
    updated = repo.update_translations([("block_a", "Bonjour", "imported")])
    units = {u.block_id: u for u in repo.get_all()}
    assert updated == 0
    assert units["block_a"].translated_text == "Salut"


def test_transfer_leaves_reviewed_units_alone(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [_unit_with_text("old_id", "Hello"), _unit_with_text("new_id", "Hello", 2)]
    )
    repo.update_translation("old_id", "Bonjour", "imported")
    repo.update_translation("new_id", "Salut", "human_validated")
    moved = repo.transfer_orphan_translations({"new_id"})
    units = {u.block_id: u for u in repo.get_all()}
    assert moved == 0
    assert units["new_id"].translated_text == "Salut"


def test_transfer_ignores_a_line_removed_from_the_game(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [_unit_with_text("old_id", "Cut line"), _unit_with_text("new_id", "Hello", 2)]
    )
    repo.update_translation("old_id", "Ligne coupée", "human_validated")
    moved = repo.transfer_orphan_translations({"new_id"})
    repo.delete_stale({"new_id"})
    units = {u.block_id: u for u in repo.get_all()}
    assert moved == 0
    assert list(units) == ["new_id"]
    assert units["new_id"].status == "not_translated"


def test_imported_unit_is_skipped_by_jobs(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert([_unit("block_a")])
    repo.update_translation("block_a", "Bonjour", "imported")
    pending = repo.get_all(status_filter="not_translated")
    drafts = repo.get_all(status_filter="draft")
    assert pending == []
    assert drafts == []


def test_get_files_sorted_by_source_file(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("z", "game/z.rpy"),
            _unit_for_file("a", "game/a.rpy"),
            _unit_for_file("m", "game/m.rpy"),
        ]
    )
    files = repo.get_files()
    names = [f["source_file"] for f in files]
    assert names == sorted(names)


def test_get_page_basic(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy", line=1),
            _unit_for_file("b", "game/script.rpy", line=2),
            _unit_for_file("c", "game/script.rpy", line=3),
        ]
    )
    units, total = repo.get_page("game/script.rpy", page=0, page_size=10)
    assert total == 3
    assert len(units) == 3
    assert isinstance(units[0], TranslationUnit)


def test_get_page_pagination(repo: TranslationUnitRepository) -> None:
    for i in range(5):
        repo.bulk_insert([_unit_for_file(f"block_{i}", "game/script.rpy", line=i)])
    units, total = repo.get_page("game/script.rpy", page=0, page_size=2)
    assert total == 5
    assert len(units) == 2
    units2, _ = repo.get_page("game/script.rpy", page=1, page_size=2)
    assert len(units2) == 2


def test_get_page_with_status_filter(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy"),
            _unit_for_file("b", "game/script.rpy"),
        ]
    )
    repo.update_translation("a", "Traduction", "human_validated")
    units, total = repo.get_page(
        "game/script.rpy", page=0, page_size=10, status_filter="human_validated"
    )
    assert total == 1
    assert units[0].block_id == "a"


def test_get_page_search(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            {
                "block_id": "a",
                "source_file": "game/script.rpy",
                "source_line": 1,
                "character_variable": None,
                "source_text": "Hello world",
            },
            {
                "block_id": "b",
                "source_file": "game/script.rpy",
                "source_line": 2,
                "character_variable": None,
                "source_text": "Goodbye everyone",
            },
        ]
    )
    units, total = repo.get_page(
        "game/script.rpy", page=0, page_size=10, search_query="Hello"
    )
    assert total == 1
    assert units[0].block_id == "a"


def _wildcard_units() -> list[dict[str, object]]:
    return [
        {
            "block_id": "a",
            "source_file": "game/script.rpy",
            "source_line": 1,
            "character_variable": None,
            "source_text": "Loading 100% complete",
        },
        {
            "block_id": "b",
            "source_file": "game/script.rpy",
            "source_line": 2,
            "character_variable": None,
            "source_text": "Loading 1000 files",
        },
        {
            "block_id": "c",
            "source_file": "game/script.rpy",
            "source_line": 3,
            "character_variable": None,
            "source_text": "Press A_B to continue",
        },
        {
            "block_id": "d",
            "source_file": "game/script.rpy",
            "source_line": 4,
            "character_variable": None,
            "source_text": "Press AXB to continue",
        },
    ]


@pytest.mark.parametrize(
    ("search_query", "expected"),
    [("100%", "a"), ("A_B", "c")],
)
def test_get_page_search_reads_wildcards_literally(
    repo: TranslationUnitRepository, search_query: str, expected: str
) -> None:
    repo.bulk_insert(_wildcard_units())
    units, total = repo.get_page(
        "game/script.rpy", page=0, page_size=10, search_query=search_query
    )
    assert total == 1
    assert units[0].block_id == expected


def test_count_matches_by_file_reads_wildcards_literally(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(_wildcard_units())
    assert repo.count_matches_by_file("100%") == {"game/script.rpy": 1}


def test_search_finds_a_backslash(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            {
                "block_id": "a",
                "source_file": "game/script.rpy",
                "source_line": 1,
                "character_variable": None,
                "source_text": "A path C:\\game is not a wildcard",
            }
        ]
    )
    units, total = repo.get_page(
        "game/script.rpy", page=0, page_size=10, search_query="C:\\game"
    )
    assert total == 1
    assert units[0].block_id == "a"


def test_get_page_isolates_by_file(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_file("a", "game/script.rpy"),
            _unit_for_file("b", "game/chapter1.rpy"),
        ]
    )
    units, total = repo.get_page("game/script.rpy", page=0, page_size=10)
    assert total == 1
    assert units[0].block_id == "a"


def _unit_for_speaker(
    block_id: str,
    speaker: str | None,
    line: int,
    source_file: str = "game/script.rpy",
) -> dict:
    return {
        "block_id": block_id,
        "source_file": source_file,
        "source_line": line,
        "character_variable": speaker,
        "source_text": f"Text {block_id}",
    }


def test_character_variables_lists_distinct_speakers_of_the_project(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_for_speaker("a", "m", 1),
            _unit_for_speaker("b", "marie", 2),
            _unit_for_speaker("c", "m", 3),
            _unit_for_speaker("d", None, 4),
            _unit_for_speaker("e", "leo", 5, source_file="game/chapter1.rpy"),
        ]
    )

    assert repo.character_variables() == ["leo", "m", "marie"]


def test_get_page_filters_on_character(repo: TranslationUnitRepository) -> None:
    repo.bulk_insert(
        [
            _unit_for_speaker("a", "m", 1),
            _unit_for_speaker("b", "marie", 2),
            _unit_for_speaker("c", "m", 3),
        ]
    )

    units, total = repo.get_page("game/script.rpy", page=0, page_size=10, character="m")

    assert total == 2
    assert [u.block_id for u in units] == ["a", "c"]


def test_get_matching_returns_every_filtered_unit(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert(
        [
            _unit_for_speaker("a", "m", 1),
            _unit_for_speaker("b", "marie", 2),
            _unit_for_speaker("c", "m", 3),
        ]
    )

    units = repo.get_matching("game/script.rpy", character="m")

    assert [u.block_id for u in units] == ["a", "c"]


@pytest.fixture()
def characters(tmp_path: Path) -> Iterator[CharacterRepository]:
    """Provide a character repository holding two entries."""
    db = Database(tmp_path / "characters.db")
    db.connect()
    repo = CharacterRepository(db.conn)
    repo.upsert("m", "Marie")
    repo.upsert("nar", "Narrator")
    repo.update_notes("m", "Femme, tutoie le joueur")
    yield repo
    db.close()


def test_delete_all_empties_the_glossary(characters: CharacterRepository) -> None:
    deleted = characters.delete_all()

    assert deleted == 2
    assert characters.get_all() == []


def test_delete_all_on_an_empty_glossary_returns_zero(
    characters: CharacterRepository,
) -> None:
    characters.delete_all()

    assert characters.delete_all() == 0


def test_connect_switches_the_database_to_wal(tmp_path: Path) -> None:
    """A project is reached by more than one process now.

    The MCP server is a second one by construction, and two windows of
    the application are not prevented either. Under the default rollback
    journal a writer locks the whole file and the other side waits out
    its busy timeout.
    """
    db = Database(tmp_path / "wal.db")
    db.connect()
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
    db.close()

    assert str(mode).lower() == "wal"


def test_a_wal_database_still_opens_read_only(tmp_path: Path) -> None:
    """Resume inspection opens read-only and must survive the switch."""
    path = tmp_path / "wal.db"
    writer = Database(path)
    writer.connect()
    TranslationUnitRepository(writer.conn).bulk_insert([_unit("block_a")])
    writer.close()

    reader = Database(path)
    reader.connect_readonly()
    count = reader.conn.execute("SELECT COUNT(*) FROM translation_units").fetchone()[0]
    reader.close()

    assert count == 1


def test_get_many_returns_only_what_was_asked(
    repo: TranslationUnitRepository,
) -> None:
    """The live refresh reads the lines it was told about, nothing else."""
    repo.bulk_insert([_unit("block_a"), _unit("block_b"), _unit("block_c")])

    units = repo.get_many(["block_a", "block_c"])

    assert {unit.block_id for unit in units} == {"block_a", "block_c"}


def test_get_many_skips_an_unknown_identifier(
    repo: TranslationUnitRepository,
) -> None:
    repo.bulk_insert([_unit("block_a")])

    units = repo.get_many(["block_a", "never_extracted"])

    assert [unit.block_id for unit in units] == ["block_a"]


def test_get_many_without_identifiers_asks_nothing(
    repo: TranslationUnitRepository,
) -> None:
    assert repo.get_many([]) == []
