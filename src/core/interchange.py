"""Bilingual interchange files: CSV, XLIFF 1.2 and JSON round-trips.

Translations leave the studio for a proofreader or a CAT tool (OmegaT,
memoQ) and come back in the same file. Units travel keyed by their Ren'Py
block id, never by position, and carry their source text along: a file
written against an older extraction is then detected instead of silently
pairing a translation with a line that changed underneath it.

CSV and JSON also carry the studio's own status, so a file that never left
the tool comes back exactly as it went out. XLIFF only knows its own
`state` vocabulary, so the round-trip through it is lossy by construction:
everything a CAT tool did not mark final returns as `imported`, the status
for text nobody has read in this project yet.

Reading XLIFF goes through defusedxml: the standard library expands
internal entities, which turns a hostile file into an entity bomb.
"""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from typing import cast, get_args

from defusedxml.ElementTree import fromstring

from core.languages import get_language
from core.storage.repositories import (
    TranslationStatus,
    TranslationUnit,
    TranslationUnitRepository,
)
from core.translation.quality import LENGTH_WARNING_KIND
from core.translation.quality import check as quality_check

XLIFF_NAMESPACE = "urn:oasis:names:tc:xliff:document:1.2"

JSON_FORMAT = "renpy-translation-studio"
JSON_VERSION = 1

FORMAT_EXTENSION: dict[str, str] = {
    "csv": "csv",
    "xliff": "xlf",
    "json": "json",
}

READABLE_EXTENSIONS = ["csv", "xlf", "xliff", "json"]

_XML_FORBIDDEN = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")

_FORMAT_BY_SUFFIX: dict[str, str] = {
    ".csv": "csv",
    ".xlf": "xliff",
    ".xliff": "xliff",
    ".json": "json",
}

_CSV_FIELDS = [
    "block_id",
    "source_file",
    "source_line",
    "character",
    "source_text",
    "translated_text",
    "status",
]

_STATUSES: frozenset[str] = frozenset(get_args(TranslationStatus))

_STATUS_TO_XLIFF: dict[str, str] = {
    "not_translated": "new",
    "draft": "needs-translation",
    "imported": "needs-review-translation",
    "ai_suggested": "needs-review-translation",
    "human_validated": "final",
}

_XLIFF_REVIEWED = frozenset({"final", "signed-off"})


class InterchangeError(Exception):
    """Raised when an interchange file cannot be read or its format is unknown."""


@dataclass(frozen=True)
class InterchangeUnit:
    """One translation read back from an interchange file.

    Attributes:
        block_id: Ren'Py block identifier the translation belongs to.
        source_text: Source the file was written against, empty when the
            file carries no source column.
        translated_text: The translation as it comes back.
        status: Status to apply, already normalised by _read_status().
    """

    block_id: str
    source_text: str
    translated_text: str
    status: TranslationStatus


@dataclass(frozen=True)
class ImportPlan:
    """What an interchange file would do to the project, before it does it.

    Nothing here has been written yet, so a plan can be shown, counted and
    thrown away. apply_plan() is what commits it.

    Attributes:
        entries: The (block_id, translated_text, status) triples that would
            be written.
        unknown: Block ids the project does not hold, typically a file
            exported from another game.
        stale: Units whose source text no longer matches the project, so
            the translation would land on a line that has since changed.
        empty: Units the file brought back without a translation, left
            alone rather than clearing what the project already holds.
        protected: Units already validated by a human, which only an
            incoming validated status may replace.
        flagged: Units written as drafts instead of validated, a quality
            check having refused the text. They are part of entries.
    """

    entries: list[tuple[str, str, TranslationStatus]]
    unknown: int
    stale: int
    empty: int
    protected: int
    flagged: int

    @property
    def applicable(self) -> int:
        """Return how many translations applying this plan would write."""
        return len(self.entries)


def write_interchange(
    path: Path,
    units: list[TranslationUnit],
    *,
    source_language: str,
    target_language: str,
) -> None:
    """Write translation units to a file, in the format its suffix names.

    Args:
        path: Destination file, whose suffix selects the format.
        units: The units to write, in the order they should appear.
        source_language: Ren'Py folder name of the source language.
        target_language: Ren'Py folder name of the target language.

    Raises:
        InterchangeError: If the suffix names no supported format.
        OSError: If the file cannot be written.
    """
    fmt = _format_of(path)
    if fmt == "csv":
        _write_csv(path, units)
    elif fmt == "xliff":
        _write_xliff(path, units, source_language, target_language)
    else:
        _write_json(path, units, source_language, target_language)


def read_interchange(path: Path) -> list[InterchangeUnit]:
    """Read back the translations held in an interchange file.

    Args:
        path: File to read, whose suffix selects the format.

    Returns:
        One unit per row carrying a block id, in file order.

    Raises:
        InterchangeError: If the suffix names no supported format, the file
            is not UTF-8, or it does not parse as that format.
        OSError: If the file cannot be read.
    """
    fmt = _format_of(path)
    try:
        if fmt == "csv":
            return _read_csv(path)
        if fmt == "xliff":
            return _read_xliff(path)
        return _read_json(path)
    except UnicodeDecodeError as exc:
        raise InterchangeError(f"File is not encoded in UTF-8: {exc}") from exc
    except csv.Error as exc:
        raise InterchangeError(f"Invalid CSV file: {exc}") from exc


def plan_import(
    units: list[InterchangeUnit], repo: TranslationUnitRepository
) -> ImportPlan:
    """Work out what an interchange file would change, without changing it.

    Every unit is paired by block id, so a file may hold a subset of the
    project, come back reordered, or carry rows the project never had.
    Four cases are counted instead of applied, and reported rather than
    silently dropped: unknown ids, a source text that has changed since
    the export, an empty translation, and a line a human already
    validated.

    A fifth is counted and applied: a rewritten translation a quality
    check refuses comes in as a draft rather than validated. The same text
    typed into the review screen behaves exactly that way, stored on the
    spot and barred from validation, so an import is no longer a way to
    reach 'human_validated' with a dropped [player_name]. Dropping the
    text outright would be worse than keeping it: the project would hold
    on to whatever broken translation it already had, and saving writes
    that one to the .rpy just the same.

    Deciding before writing is what lets the user see the damage a foreign
    file would do while refusing it still costs nothing.

    What does come back has its status weighed against the text it carries,
    see _incoming_status().

    Args:
        units: Units read by read_interchange().
        repo: Repository of the project the file belongs to.

    Returns:
        What would be written, and why the rest would not be.
    """
    stored = {unit.block_id: unit for unit in repo.get_all()}
    entries: list[tuple[str, str, TranslationStatus]] = []
    unknown = 0
    stale = 0
    empty = 0
    protected = 0
    flagged = 0

    for unit in units:
        current = stored.get(unit.block_id)
        if current is None:
            unknown += 1
        elif not unit.translated_text.strip():
            empty += 1
        elif unit.source_text and unit.source_text != current.source_text:
            stale += 1
        elif current.status == "human_validated" and unit.status != "human_validated":
            protected += 1
        else:
            status = _incoming_status(unit, current)
            if _must_be_drafted(unit, current, status):
                status = "draft"
                flagged += 1
            entries.append((unit.block_id, unit.translated_text, status))

    return ImportPlan(
        entries=entries,
        unknown=unknown,
        stale=stale,
        empty=empty,
        protected=protected,
        flagged=flagged,
    )


def apply_plan(plan: ImportPlan, repo: TranslationUnitRepository) -> int:
    """Write the translations a plan holds.

    Args:
        plan: What plan_import() decided to write.
        repo: Repository of the project the plan was built against.

    Returns:
        The number of units actually updated.
    """
    return repo.update_translations(plan.entries)


def _format_of(path: Path) -> str:
    """Return the interchange format a file suffix names.

    Args:
        path: The file whose suffix is examined.

    Returns:
        One of 'csv', 'xliff' or 'json'.

    Raises:
        InterchangeError: If the suffix names no supported format.
    """
    fmt = _FORMAT_BY_SUFFIX.get(path.suffix.lower())
    if fmt is None:
        raise InterchangeError(f"Unsupported interchange format: {path.suffix}")
    return fmt


def _as_row(unit: TranslationUnit) -> dict[str, str | int]:
    """Flatten a unit into the columns shared by the CSV and JSON formats.

    Args:
        unit: The stored unit to write out.

    Returns:
        A mapping keyed by _CSV_FIELDS.
    """
    return {
        "block_id": unit.block_id,
        "source_file": unit.source_file,
        "source_line": unit.source_line,
        "character": unit.character_variable or "",
        "source_text": unit.source_text,
        "translated_text": unit.translated_text,
        "status": unit.status,
    }


def _must_be_drafted(
    unit: InterchangeUnit, current: TranslationUnit, status: TranslationStatus
) -> bool:
    """Return whether a translation may not come in as validated.

    Only a rewritten text is weighed. One that matches what the project
    already holds changes nothing, and re-judging it would have a file
    exported and imported back unchanged report refusals it did not cause.

    The rule itself is the review screen's: everything quality_check()
    reports bars validation, except the length warning, which flags an
    unusual ratio rather than something broken.

    Args:
        unit: The unit as the file carries it.
        current: The unit as the project currently holds it.
        status: The status the import would otherwise store.

    Returns:
        True when the translation must land as a draft instead.
    """
    if status != "human_validated" or unit.translated_text == current.translated_text:
        return False
    issues = quality_check(current.source_text, unit.translated_text)
    return any(issue.kind != LENGTH_WARNING_KIND for issue in issues)


def _incoming_status(
    unit: InterchangeUnit, current: TranslationUnit
) -> TranslationStatus:
    """Decide what status a translation coming back deserves.

    A file edited outside the studio keeps the status column it left with,
    so text a proofreader rewrote in a spreadsheet still reads
    'ai_suggested' on the way back. Storing it as such would hand human
    work to "clear the AI suggestions", which erases it without a word.
    Text that differs from what the project holds is therefore taken as
    'imported', the status for a translation nobody here has read yet.

    A file that went out and came back untouched keeps its status, so the
    round-trip through the studio's own formats stays lossless.

    Args:
        unit: The unit as the file carries it.
        current: The unit as the project currently holds it.

    Returns:
        The status to store.
    """
    rewritten = unit.translated_text != current.translated_text
    if unit.status == "ai_suggested" and rewritten:
        return "imported"
    return unit.status


def _read_status(status: str) -> TranslationStatus:
    """Turn the status column of a file into one the project can store.

    A file edited outside the studio has no reason to keep the column
    honest: a spreadsheet row can carry a translation and still read
    'not_translated', and a foreign tool writes whatever it likes.
    Anything the project does not recognise, and anything claiming no
    translation, becomes 'imported', which is what text of unknown
    provenance means here.

    Args:
        status: The raw value found in the file.

    Returns:
        A status the repository accepts.
    """
    if status in _STATUSES and status != "not_translated":
        return cast(TranslationStatus, status)
    return "imported"


def _write_csv(path: Path, units: list[TranslationUnit]) -> None:
    """Write units as a UTF-8 CSV file with a BOM.

    The BOM is what makes spreadsheets open the file as UTF-8 instead of
    the system codepage, which is where accented translations go to die.

    Args:
        path: Destination file.
        units: The units to write.
    """
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(_as_row(unit) for unit in units)


def _read_csv(path: Path) -> list[InterchangeUnit]:
    """Read a CSV file written by _write_csv(), or any file carrying its columns.

    Args:
        path: File to read.

    Returns:
        One unit per row holding a block id.

    Raises:
        InterchangeError: If the file has no block_id column.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "block_id" not in reader.fieldnames:
            raise InterchangeError("CSV file has no block_id column")
        return [
            InterchangeUnit(
                block_id=row["block_id"],
                source_text=row.get("source_text") or "",
                translated_text=row.get("translated_text") or "",
                status=_read_status(row.get("status") or ""),
            )
            for row in reader
            if row.get("block_id")
        ]


def _write_json(
    path: Path,
    units: list[TranslationUnit],
    source_language: str,
    target_language: str,
) -> None:
    """Write units as a JSON document naming its format and language pair.

    Args:
        path: Destination file.
        units: The units to write.
        source_language: Ren'Py folder name of the source language.
        target_language: Ren'Py folder name of the target language.
    """
    payload = {
        "format": JSON_FORMAT,
        "version": JSON_VERSION,
        "source_language": source_language,
        "target_language": target_language,
        "units": [_as_row(unit) for unit in units],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> list[InterchangeUnit]:
    """Read a JSON document written by _write_json(), or a bare list of units.

    Args:
        path: File to read.

    Returns:
        One unit per entry holding a block id.

    Raises:
        InterchangeError: If the document does not parse, or holds no unit
            list.
    """
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InterchangeError(f"Invalid JSON file: {exc}") from exc

    rows: object = payload.get("units") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise InterchangeError("JSON file holds no unit list")

    units: list[InterchangeUnit] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("block_id"):
            continue
        units.append(
            InterchangeUnit(
                block_id=str(row["block_id"]),
                source_text=str(row.get("source_text") or ""),
                translated_text=str(row.get("translated_text") or ""),
                status=_read_status(str(row.get("status") or "")),
            )
        )
    return units


def _write_xliff(
    path: Path,
    units: list[TranslationUnit],
    source_language: str,
    target_language: str,
) -> None:
    """Write units as an XLIFF 1.2 document, one file element per source file.

    Args:
        path: Destination file.
        units: The units to write.
        source_language: Ren'Py folder name of the source language.
        target_language: Ren'Py folder name of the target language.
    """
    ElementTree.register_namespace("", XLIFF_NAMESPACE)
    root = ElementTree.Element(_tag("xliff"), {"version": "1.2"})

    by_file: dict[str, list[TranslationUnit]] = {}
    for unit in units:
        by_file.setdefault(unit.source_file, []).append(unit)

    for source_file, file_units in by_file.items():
        node = ElementTree.SubElement(
            root,
            _tag("file"),
            {
                "original": source_file,
                "source-language": _xliff_language(source_language),
                "target-language": _xliff_language(target_language),
                "datatype": "plaintext",
            },
        )
        body = ElementTree.SubElement(node, _tag("body"))
        for unit in file_units:
            trans = ElementTree.SubElement(
                body, _tag("trans-unit"), {"id": unit.block_id}
            )
            source = ElementTree.SubElement(trans, _tag("source"))
            source.text = _xml_safe(unit.source_text)
            target = ElementTree.SubElement(
                trans, _tag("target"), {"state": _STATUS_TO_XLIFF[unit.status]}
            )
            target.text = _xml_safe(unit.translated_text)
            if unit.character_variable:
                note = ElementTree.SubElement(trans, _tag("note"))
                note.text = _xml_safe(unit.character_variable)

    ElementTree.indent(root)
    ElementTree.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _read_xliff(path: Path) -> list[InterchangeUnit]:
    """Read the trans-units of an XLIFF document, whatever tool wrote it.

    Text is gathered with itertext() rather than read off the element
    itself, so a CAT tool that wrapped segments in inline markup still
    yields the sentence instead of the text before its first tag.

    Args:
        path: File to read.

    Returns:
        One unit per trans-unit holding an id.

    Raises:
        InterchangeError: If the document does not parse, or defuses as
            hostile.
    """
    try:
        root = fromstring(path.read_text(encoding="utf-8"))
    except (ElementTree.ParseError, ValueError) as exc:
        raise InterchangeError(f"Invalid XLIFF file: {exc}") from exc

    units: list[InterchangeUnit] = []
    for node in root.iter():
        if _local_name(node.tag) != "trans-unit":
            continue
        block_id = node.get("id")
        if not block_id:
            continue
        target = _child(node, "target")
        state = target.get("state", "") if target is not None else ""
        units.append(
            InterchangeUnit(
                block_id=block_id,
                source_text=_text_of(_child(node, "source")),
                translated_text=_text_of(target),
                status="human_validated" if state in _XLIFF_REVIEWED else "imported",
            )
        )
    return units


def _xml_safe(text: str) -> str:
    """Drop the characters an XML 1.0 document has no way to hold.

    ElementTree writes a control character out as it stands, and the file
    then fails to parse on the way back in: an export that succeeded would
    have produced something no CAT tool can open. XML 1.0 offers no escape
    for them, so dropping them is the only way through. Ren'Py dialogue has
    no reason to carry one; a game generating text at runtime might.

    Args:
        text: Text on its way into an element.

    Returns:
        The same text without the characters XML 1.0 forbids.
    """
    return _XML_FORBIDDEN.sub("", text)


def _tag(name: str) -> str:
    """Return an XLIFF element name qualified with the 1.2 namespace.

    Args:
        name: Local element name.

    Returns:
        The name in ElementTree's '{namespace}name' notation.
    """
    return f"{{{XLIFF_NAMESPACE}}}{name}"


def _local_name(tag: str) -> str:
    """Return an XML tag stripped of its namespace.

    Args:
        tag: Tag as ElementTree reports it.

    Returns:
        The local name alone.
    """
    return tag.rsplit("}", 1)[-1]


def _child(node: ElementTree.Element, name: str) -> ElementTree.Element | None:
    """Return the first direct child with a given local name.

    Args:
        node: Element to look under.
        name: Local name to match, namespace ignored.

    Returns:
        The matching child, or None if there is none.
    """
    for child in node:
        if _local_name(child.tag) == name:
            return child
    return None


def _text_of(node: ElementTree.Element | None) -> str:
    """Return every piece of text an element holds, inline markup included.

    Args:
        node: Element to flatten, possibly absent.

    Returns:
        The concatenated text, empty when the element is absent.
    """
    return "" if node is None else "".join(node.itertext())


def _xliff_language(code: str) -> str:
    """Return the language tag a CAT tool expects for a Ren'Py folder name.

    Args:
        code: Ren'Py tl/ folder name, e.g. 'brazilian'.

    Returns:
        The BCP-47 tag of that language, e.g. 'pt-BR', or the code itself
        for a folder no language declares.
    """
    language = get_language(code)
    return language.long_code if language else code
