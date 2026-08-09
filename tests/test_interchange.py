"""Tests for core/interchange.py."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from core.interchange import (
    ImportPlan,
    InterchangeError,
    InterchangeUnit,
    apply_plan,
    plan_import,
    read_interchange,
    write_interchange,
)
from core.storage.database import Database
from core.storage.repositories import TranslationStatus, TranslationUnitRepository


@pytest.fixture()
def repo(tmp_path: Path) -> Iterator[TranslationUnitRepository]:
    """Provide a repository holding three units of a fake project."""
    db = Database(tmp_path / "test.db")
    db.connect()
    units = TranslationUnitRepository(db.conn)
    units.bulk_insert(
        [
            {
                "block_id": "start_aaa",
                "source_file": "game/script.rpy",
                "source_line": 10,
                "character_variable": "m",
                "source_text": "Hello.",
            },
            {
                "block_id": "start_bbb",
                "source_file": "game/script.rpy",
                "source_line": 12,
                "character_variable": None,
                "source_text": "It rains.",
            },
            {
                "block_id": "strings_ccc",
                "source_file": "game/options.rpy",
                "source_line": 3,
                "character_variable": None,
                "source_text": "Start",
            },
        ]
    )
    yield units
    db.close()


def _export(repo: TranslationUnitRepository, tmp_path: Path, suffix: str) -> Path:
    """Write the whole project to a file of the given suffix."""
    path = tmp_path / f"export{suffix}"
    write_interchange(
        path,
        repo.get_all(),
        source_language="english",
        target_language="brazilian",
    )
    return path


def _run_import(
    units: list[InterchangeUnit], repo: TranslationUnitRepository
) -> tuple[ImportPlan, int]:
    """Plan an import, apply it, and hand back both halves."""
    plan = plan_import(units, repo)
    return plan, apply_plan(plan, repo)


@pytest.mark.parametrize("suffix", [".csv", ".json", ".xlf"])
def test_round_trip_keeps_block_ids_and_text(
    repo: TranslationUnitRepository, tmp_path: Path, suffix: str
) -> None:
    repo.update_translation("start_aaa", "Bonjour à toi.", "human_validated")
    path = _export(repo, tmp_path, suffix)

    read = {unit.block_id: unit for unit in read_interchange(path)}

    assert set(read) == {"start_aaa", "start_bbb", "strings_ccc"}
    assert read["start_aaa"].translated_text == "Bonjour à toi."
    assert read["start_aaa"].source_text == "Hello."
    assert read["start_aaa"].status == "human_validated"


@pytest.mark.parametrize("suffix", [".csv", ".json"])
def test_round_trip_keeps_ai_status(
    repo: TranslationUnitRepository, tmp_path: Path, suffix: str
) -> None:
    repo.update_translation("start_bbb", "Il pleut.", "ai_suggested")
    path = _export(repo, tmp_path, suffix)

    read = {unit.block_id: unit for unit in read_interchange(path)}

    assert read["start_bbb"].status == "ai_suggested"


def test_xliff_downgrades_unreviewed_status_to_imported(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    repo.update_translation("start_bbb", "Il pleut.", "ai_suggested")
    path = _export(repo, tmp_path, ".xlf")

    read = {unit.block_id: unit for unit in read_interchange(path)}

    assert read["start_bbb"].status == "imported"


def test_xliff_uses_regional_language_tags(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    path = _export(repo, tmp_path, ".xlf")

    content = path.read_text(encoding="utf-8")

    assert 'source-language="en"' in content
    assert 'target-language="pt-BR"' in content


def test_csv_is_written_with_a_bom(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    path = _export(repo, tmp_path, ".csv")

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_unknown_suffix_is_rejected(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    with pytest.raises(InterchangeError):
        write_interchange(
            tmp_path / "export.txt",
            repo.get_all(),
            source_language="english",
            target_language="french",
        )


def test_csv_without_block_id_column_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "foreign.csv"
    path.write_text("source,target\nHello,Bonjour\n", encoding="utf-8")

    with pytest.raises(InterchangeError):
        read_interchange(path)


def test_unparsable_csv_is_rejected(tmp_path: Path) -> None:
    """An unbalanced quote must surface as InterchangeError, not csv.Error."""
    path = tmp_path / "broken.csv"
    path.write_text(
        'block_id,translated_text\nstart_aaa,"' + "x" * 131073 + "\n",
        encoding="utf-8-sig",
    )

    with pytest.raises(InterchangeError):
        read_interchange(path)


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(InterchangeError):
        read_interchange(path)


def test_xliff_entity_bomb_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bomb.xlf"
    path.write_text(
        '<?xml version="1.0"?>\n'
        "<!DOCTYPE lolz [\n"
        ' <!ENTITY lol "lol">\n'
        ' <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;">\n'
        "]>\n"
        "<xliff><file><body>"
        '<trans-unit id="a"><source>&lol1;</source></trans-unit>'
        "</body></file></xliff>",
        encoding="utf-8",
    )

    with pytest.raises(InterchangeError):
        read_interchange(path)


def test_xliff_reads_namespaceless_files_and_inline_markup(tmp_path: Path) -> None:
    path = tmp_path / "cat_tool.xlf"
    path.write_text(
        '<?xml version="1.0"?>'
        '<xliff version="1.2"><file original="game/script.rpy"><body>'
        '<trans-unit id="start_aaa">'
        "<source>Hello.</source>"
        '<target state="final">Bon<g id="1">jour</g>.</target>'
        "</trans-unit></body></file></xliff>",
        encoding="utf-8",
    )

    units = read_interchange(path)

    assert len(units) == 1
    assert units[0].translated_text == "Bonjour."
    assert units[0].status == "human_validated"


def test_xliff_export_stays_readable_with_control_characters(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    repo.update_translation("start_aaa", "Bon\x0cjour.", "human_validated")

    path = _export(repo, tmp_path, ".xlf")
    units = {unit.block_id: unit for unit in read_interchange(path)}

    assert units["start_aaa"].translated_text == "Bonjour."


def test_import_applies_translations_by_block_id(
    repo: TranslationUnitRepository,
) -> None:
    _, applied = _run_import(
        [
            InterchangeUnit("strings_ccc", "Start", "Commencer", "imported"),
            InterchangeUnit("start_aaa", "Hello.", "Bonjour.", "human_validated"),
        ],
        repo,
    )

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert applied == 2
    assert stored["start_aaa"].translated_text == "Bonjour."
    assert stored["start_aaa"].status == "human_validated"
    assert stored["strings_ccc"].status == "imported"


def test_planning_an_import_writes_nothing(repo: TranslationUnitRepository) -> None:
    plan = plan_import(
        [InterchangeUnit("start_aaa", "Hello.", "Bonjour.", "imported")], repo
    )

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert plan.applicable == 1
    assert stored["start_aaa"].translated_text == ""
    assert stored["start_aaa"].status == "not_translated"


def test_import_counts_unknown_block_ids(repo: TranslationUnitRepository) -> None:
    plan, applied = _run_import(
        [InterchangeUnit("other_game_xyz", "Hi", "Salut", "imported")], repo
    )

    assert plan.unknown == 1
    assert applied == 0


def test_import_skips_units_whose_source_changed(
    repo: TranslationUnitRepository,
) -> None:
    plan, applied = _run_import(
        [InterchangeUnit("start_aaa", "Hello there.", "Bonjour.", "imported")], repo
    )

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert plan.stale == 1
    assert applied == 0
    assert stored["start_aaa"].translated_text == ""


def test_import_ignores_empty_translations(repo: TranslationUnitRepository) -> None:
    repo.update_translation("start_aaa", "Bonjour.", "human_validated")

    plan, _ = _run_import(
        [InterchangeUnit("start_aaa", "Hello.", "   ", "human_validated")], repo
    )

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert plan.empty == 1
    assert stored["start_aaa"].translated_text == "Bonjour."


def test_import_protects_validated_units(repo: TranslationUnitRepository) -> None:
    repo.update_translation("start_aaa", "Bonjour.", "human_validated")

    plan, _ = _run_import(
        [InterchangeUnit("start_aaa", "Hello.", "Salut.", "imported")], repo
    )

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert plan.protected == 1
    assert stored["start_aaa"].translated_text == "Bonjour."


def test_import_applies_when_the_file_carries_no_source(
    repo: TranslationUnitRepository,
) -> None:
    _, applied = _run_import(
        [InterchangeUnit("start_aaa", "", "Bonjour.", "imported")], repo
    )

    assert applied == 1


@pytest.mark.parametrize("raw", ["", "not_translated", "reviewed-by-someone-else"])
def test_dishonest_status_columns_become_imported(
    repo: TranslationUnitRepository, tmp_path: Path, raw: str
) -> None:
    path = tmp_path / "edited.csv"
    path.write_text(
        "block_id,source_text,translated_text,status\n"
        f"start_aaa,Hello.,Bonjour.,{raw}\n",
        encoding="utf-8-sig",
    )

    units = read_interchange(path)
    _run_import(units, repo)

    stored: dict[str, TranslationStatus] = {
        unit.block_id: unit.status for unit in repo.get_all()
    }
    assert units[0].status == "imported"
    assert stored["start_aaa"] == "imported"


def test_proofread_suggestions_come_back_as_imported(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    """A rewritten suggestion must not keep a status "clear AI" would erase."""
    repo.update_translation("start_bbb", "Il pleut.", "ai_suggested")
    path = _export(repo, tmp_path, ".csv")
    path.write_text(
        path.read_text(encoding="utf-8-sig").replace(
            "Il pleut.", "Il pleut des cordes."
        ),
        encoding="utf-8-sig",
    )

    _run_import(read_interchange(path), repo)

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert stored["start_bbb"].translated_text == "Il pleut des cordes."
    assert stored["start_bbb"].status == "imported"


def test_a_translation_that_lost_a_variable_lands_as_a_draft(
    repo: TranslationUnitRepository,
) -> None:
    """Text is kept, validation is not: the same rule as the review screen."""
    repo.bulk_insert(
        [
            {
                "block_id": "start_ddd",
                "source_file": "game/script.rpy",
                "source_line": 20,
                "character_variable": None,
                "source_text": "Hi [player_name].",
            }
        ]
    )

    plan, applied = _run_import(
        [
            InterchangeUnit(
                "start_ddd", "Hi [player_name].", "Salut toi.", "human_validated"
            )
        ],
        repo,
    )

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert plan.flagged == 1
    assert applied == 1
    assert stored["start_ddd"].translated_text == "Salut toi."
    assert stored["start_ddd"].status == "draft"


def test_an_unchanged_translation_is_never_flagged(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    """A round-trip that changed nothing must not report refusals it did not cause."""
    repo.bulk_insert(
        [
            {
                "block_id": "start_ddd",
                "source_file": "game/script.rpy",
                "source_line": 20,
                "character_variable": None,
                "source_text": "Hi [player_name].",
            }
        ]
    )
    repo.update_translation("start_ddd", "Salut toi.", "human_validated")
    path = _export(repo, tmp_path, ".csv")

    plan, _ = _run_import(read_interchange(path), repo)

    stored = {unit.block_id: unit for unit in repo.get_all()}
    assert plan.flagged == 0
    assert stored["start_ddd"].status == "human_validated"


def test_import_accepts_a_translation_that_is_merely_long(
    repo: TranslationUnitRepository,
) -> None:
    plan, applied = _run_import(
        [
            InterchangeUnit(
                "start_bbb",
                "It rains.",
                "Il pleut des cordes depuis ce matin.",
                "human_validated",
            )
        ],
        repo,
    )

    assert plan.flagged == 0
    assert applied == 1


def test_untouched_suggestions_keep_their_status(
    repo: TranslationUnitRepository, tmp_path: Path
) -> None:
    repo.update_translation("start_bbb", "Il pleut.", "ai_suggested")
    path = _export(repo, tmp_path, ".csv")

    _run_import(read_interchange(path), repo)

    stored = {unit.block_id: unit.status for unit in repo.get_all()}
    assert stored["start_bbb"] == "ai_suggested"
