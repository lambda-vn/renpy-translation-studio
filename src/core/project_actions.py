"""Project-wide actions orchestrating a repository and another core module.

These two used to live inside the views that trigger them, which made them
unreachable from anything but a click. They are the same work whoever asks
for it, so they sit here, taking their repository as an argument and
returning a count rather than touching an interface.

Neither reports progress: both run in one pass over data already in memory
or in SQLite, fast enough that the caller only ever sees the result.
"""

from pathlib import Path

from core.renpy.character_detector import CharacterDetector
from core.storage.repositories import (
    CharacterRepository,
    TranslationStatus,
    TranslationUnitRepository,
)
from core.storage.translation_memory import translation_memory


def fill_from_memory(
    repo: TranslationUnitRepository,
    *,
    source_language: str,
    target_language: str,
) -> int:
    """Fill untranslated lines with what the translation memory holds.

    Only not_translated units are touched, so nothing reviewed can be
    overwritten and the action needs no confirmation. The text comes from
    another project and nobody has read it in this one, which is exactly
    what the imported status means, and it is also what lets the memory
    answer a source text it holds only a punctuation apart.

    The whole project is filled, never a single file: the memory answers
    for a language pair, not for a file, and a per-file scope would only
    make the caller walk every file to reach the same result.

    Args:
        repo: Repository of the project to fill.
        source_language: Language the source text is written in.
        target_language: Language the translations are wanted in.

    Returns:
        The number of lines actually filled, zero when the memory holds
        nothing for this pair.
    """
    units = repo.get_all(status_filter="not_translated")
    hits = translation_memory.lookup(
        [unit.source_text for unit in units],
        source_language,
        target_language,
    )
    entries: list[tuple[str, str, TranslationStatus]] = [
        (unit.block_id, hits[unit.source_text], "imported")
        for unit in units
        if unit.source_text in hits
    ]
    return repo.update_translations(entries)


def detect_and_store_characters(
    repo: CharacterRepository,
    project_path: Path,
) -> int:
    """Scan the project for Character() definitions and save them.

    The scan is heuristic and the write is an upsert that overwrites the
    display name, so one edited by hand goes back to whatever the scan
    reads in the source. Notes survive, being the part no scan produces.

    Args:
        repo: Character repository of the project.
        project_path: Path to the Ren'Py project root.

    Returns:
        The number of characters the scan found, whether or not each was
        already stored.
    """
    detected = CharacterDetector().detect(project_path)
    for character in detected:
        repo.upsert(character.variable, character.display_name)
    return len(detected)
