"""Data access layer for translation units."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Literal, TypedDict

TranslationStatus = Literal[
    "not_translated", "draft", "imported", "ai_suggested", "human_validated"
]


class FileStats(TypedDict):
    """Per-file translation progress, as returned by get_files()."""

    source_file: str
    total: int
    validated: int
    ai_suggested: int
    draft: int
    imported: int


class ProjectProgress(TypedDict):
    """Whole-project counts, as returned by project_progress()."""

    lines: int
    validated_lines: int
    words: int
    validated_words: int


class DuplicateStats(TypedDict):
    """How often one source text occurs, as returned by count_duplicates()."""

    total: int
    other_files: int


class SourceResync(TypedDict):
    """What realigning stored units on a fresh parse changed.

    Attributes:
        repaired: Units whose stored source text was replaced.
        dropped: Translations cleared along with it, none of them
            reviewed by a human.
        kept: Repaired units whose translation was human_validated and
            therefore left in place, for someone to look at again.
    """

    repaired: int
    dropped: int
    kept: int


@dataclass
class TranslationUnit:
    """A single row from the translation_units table.

    needs_review and note are set by hand and by nobody else. They sit
    beside the status rather than inside it because the five statuses are
    derived from the pipeline: a translation job or an import rewrites
    them, and a mark meant to survive until its owner clears it cannot
    live there.
    """

    id: int
    block_id: str
    source_file: str
    source_line: int
    character_variable: str | None
    source_text: str
    translated_text: str
    status: TranslationStatus
    needs_review: bool = False
    note: str | None = None


_SELECT_COLUMNS = (
    "id, block_id, source_file, source_line, character_variable,"
    " source_text, translated_text, status, needs_review, note"
)

_MIN_PARSE_COVERAGE = 0.5

_LIKE_ESCAPE = "\\"

_SEARCH_CONDITION = (
    "(source_text LIKE ? ESCAPE '\\' OR translated_text LIKE ? ESCAPE '\\')"
)


def _like_pattern(query: str) -> str:
    """Return the pattern matching a searched substring literally.

    LIKE reads % and _ inside the bound value as wildcards, so a search
    for "100%" would answer with every line holding "100". Both, and the
    escape character itself, are neutralised here; the condition they go
    with must carry the matching ESCAPE clause, which _SEARCH_CONDITION
    does.

    Args:
        query: The substring searched, as typed.

    Returns:
        The pattern to bind to a LIKE placeholder.
    """
    escaped = (
        query.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )
    return f"%{escaped}%"


def _unit_from_row(row: sqlite3.Row) -> TranslationUnit:
    """Build a unit from a row selected with _SELECT_COLUMNS.

    Args:
        row: The database row to convert.

    Returns:
        The unit, its needs_review flag turned from SQLite's integer into
        the bool the dataclass declares.
    """
    data = dict(row)
    data["needs_review"] = bool(data["needs_review"])
    return TranslationUnit(**data)


class TranslationUnitRepository:
    """CRUD operations for translation units."""

    def __init__(
        self, conn: sqlite3.Connection, lock: threading.Lock | None = None
    ) -> None:
        """Initialize with an open database connection.

        Args:
            conn: Active sqlite3 connection with row_factory = sqlite3.Row.
            lock: Lock serializing access to conn across threads. A dedicated
                lock is created if omitted, but callers that share the same
                connection across threads (e.g. a background translation
                job) must pass the same lock to every repository instance.
        """
        self._conn = conn
        self._lock = lock or threading.Lock()
        self._source_words: int | None = None

    def bulk_insert(self, units: list[dict[str, object]]) -> None:
        """Insert a batch of new units, skipping existing block_ids.

        Uses INSERT OR IGNORE so that re-extraction never overwrites
        validated or suggested translations.

        Args:
            units: List of dicts with keys block_id, source_file,
                   source_line, character_variable, source_text.
        """
        with self._lock:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO translation_units
                (block_id, source_file, source_line, character_variable, source_text)
                VALUES (:block_id, :source_file, :source_line,
                        :character_variable, :source_text)
                """,
                units,
            )
            self._conn.commit()
        self._source_words = None

    def resync_sources(self, units: list[dict[str, object]]) -> SourceResync:
        """Replace a stored source text the parser now reads differently.

        bulk_insert() ignores a block id it already knows, which is what
        keeps a re-extraction from wiping the work. The cost is that a
        unit inserted by an older, wronger parse keeps that text forever:
        the say statements whose speaker and transition used to be stored
        as part of the spoken text stayed that way in every database
        created before the parser learned to split them.

        A translation answering the old text answers a question that was
        never asked, so it goes with it. Not a human_validated one: it may
        have been typed by someone reading past the noise, and throwing
        away reviewed work to fix a display bug is the worse trade. Those
        are counted instead, so the caller can say how many lines deserve
        a second look.

        Must run before transfer_orphan_translations(), which pairs
        orphans by source text and would otherwise pair them on the text
        being corrected here.

        Args:
            units: The freshly parsed units, in bulk_insert() shape.

        Returns:
            What changed, per SourceResync.
        """
        parsed = {str(unit["block_id"]): unit for unit in units}
        if not parsed:
            return SourceResync(repaired=0, dropped=0, kept=0)

        with self._lock:
            rows = self._conn.execute(
                "SELECT block_id, source_text, translated_text, status"
                " FROM translation_units"
            ).fetchall()

        repairs: list[tuple[str, str | None, str]] = []
        drops: list[str] = []
        kept = 0
        for row in rows:
            unit = parsed.get(row["block_id"])
            if unit is None or unit["source_text"] == row["source_text"]:
                continue
            character = unit["character_variable"]
            repairs.append(
                (
                    str(unit["source_text"]),
                    str(character) if character is not None else None,
                    row["block_id"],
                )
            )
            if row["status"] == "human_validated":
                kept += 1
            elif row["translated_text"]:
                drops.append(row["block_id"])

        if not repairs:
            return SourceResync(repaired=0, dropped=0, kept=0)

        with self._lock:
            self._conn.executemany(
                "UPDATE translation_units"
                " SET source_text = ?, character_variable = ?"
                " WHERE block_id = ?",
                repairs,
            )
            self._conn.executemany(
                "UPDATE translation_units"
                " SET translated_text = '', status = 'not_translated'"
                " WHERE block_id = ?",
                [(block_id,) for block_id in drops],
            )
            self._conn.commit()
        self._source_words = None
        return SourceResync(repaired=len(repairs), dropped=len(drops), kept=kept)

    def transfer_orphan_translations(self, current_block_ids: set[str]) -> int:
        """Move translations off vanished block ids onto the lines that remain.

        Ren'Py rebuilds block ids from the script, so an id can disappear
        while its line is still in the game under a new one. The source text
        is what identifies a line across versions: every unit still awaiting
        a translation inherits the text of an orphan sharing its source text.
        A line the game really dropped has no such match anywhere, and its
        translation simply dies with it.

        Only not_translated units are filled, so no reviewed work is ever
        replaced. Should several orphans share one source text with different
        translations, the first in file order wins; they translate the same
        sentence, so any of them is a defensible choice.

        The orphan keeps its status only when a single line inherits from it,
        the signature of a line whose id was merely rebuilt. As soon as
        several lines share the text, the translation is spread by
        similarity, not identity: they become imported, the status for text
        of unknown provenance. Propagating human_validated there would mark
        as reviewed lines nobody ever saw, and lock them against any later
        correction.

        Must run before delete_stale(), which removes the drained orphans.

        Args:
            current_block_ids: Block ids returned by the latest parse.

        Returns:
            The number of units that inherited a translation.
        """
        units = self.get_all()
        by_text: dict[str, TranslationUnit] = {}
        for unit in units:
            if (
                unit.block_id not in current_block_ids
                and unit.status != "not_translated"
            ):
                by_text.setdefault(unit.source_text, unit)
        if not by_text:
            return 0

        heirs: dict[str, list[str]] = {}
        for unit in units:
            if (
                unit.status == "not_translated"
                and unit.block_id in current_block_ids
                and unit.source_text in by_text
            ):
                heirs.setdefault(unit.source_text, []).append(unit.block_id)

        entries: list[tuple[str, str, TranslationStatus]] = []
        for source_text, block_ids in heirs.items():
            orphan = by_text[source_text]
            status = orphan.status if len(block_ids) == 1 else "imported"
            entries.extend(
                (block_id, orphan.translated_text, status) for block_id in block_ids
            )
        return self.update_translations(entries)

    def delete_stale(self, current_block_ids: set[str]) -> int:
        """Remove every unit whose block id is absent from the latest parse.

        A row is keyed by its block id: once no file carries that id, nothing
        can ever be written back to it, whatever its status. Validated units
        are no exception, and are dropped like the rest. What protects the
        work is transfer_orphan_translations(), which must run first to hand
        each translation over to the line that survived it.

        Nothing is deleted when the parse covers less than half the stored
        units. A truncated tl/ folder is a real possibility (the SDK hitting
        its timeout leaves one behind, and resuming without rebuilding reads
        it as-is) and it is indistinguishable from a game that legitimately
        lost that many lines. Keeping obsolete rows costs nothing but a few
        unwritable rows until the next full extraction; deleting live ones
        destroys reviewed work.

        Args:
            current_block_ids: Block ids returned by the latest parse.

        Returns:
            The number of obsolete units that were deleted, zero when the
            parse was too small to be trusted.
        """
        with self._lock:
            stored = self._conn.execute(
                "SELECT COUNT(*) FROM translation_units"
            ).fetchone()[0]
        if len(current_block_ids) < stored * _MIN_PARSE_COVERAGE:
            return 0

        with self._lock:
            self._conn.execute(
                "CREATE TEMPORARY TABLE IF NOT EXISTS _current_ids"
                " (block_id TEXT PRIMARY KEY)"
            )
            self._conn.execute("DELETE FROM _current_ids")
            self._conn.executemany(
                "INSERT OR IGNORE INTO _current_ids VALUES (?)",
                [(bid,) for bid in current_block_ids],
            )
            cursor = self._conn.execute(
                """
                DELETE FROM translation_units
                WHERE block_id NOT IN (SELECT block_id FROM _current_ids)
                """
            )
            deleted = cursor.rowcount
            self._conn.execute("DROP TABLE _current_ids")
            self._conn.commit()
        self._source_words = None
        return deleted

    def get_all(
        self,
        status_filter: str | None = None,
        source_file: str | None = None,
    ) -> list[TranslationUnit]:
        """Return units ordered by file and line, optionally filtered.

        Args:
            status_filter: If given, only return units with this status.
            source_file: If given, only return units from this source file.

        Returns:
            List of TranslationUnit dataclass instances.
        """
        conditions: list[str] = []
        params: list[str] = []
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        if source_file:
            conditions.append("source_file = ?")
            params.append(source_file)

        query = f"SELECT {_SELECT_COLUMNS} FROM translation_units"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY source_file, source_line"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_unit_from_row(row) for row in rows]

    def get_many(self, block_ids: list[str]) -> list[TranslationUnit]:
        """Return the units carrying these identifiers.

        Answers the live refresh, which is told exactly which lines
        another process just wrote and has no reason to read the file
        around them. Callers pass what is on screen, so the list is
        bounded by a page and needs no slicing.

        Args:
            block_ids: Identifiers to look for; unknown ones are skipped.

        Returns:
            The matching units, in no particular order.
        """
        if not block_ids:
            return []
        placeholders = ",".join("?" * len(block_ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM translation_units"
                f" WHERE block_id IN ({placeholders})",
                block_ids,
            ).fetchall()
        return [_unit_from_row(row) for row in rows]

    def update_translation(
        self, block_id: str, translated_text: str, status: TranslationStatus
    ) -> None:
        """Update translation and status for a unit.

        A human_validated unit is never overwritten by ai_suggested.

        Args:
            block_id: The unique identifier of the block.
            translated_text: The new translated string.
            status: The new status for this unit.
        """
        with self._lock:
            current = self._conn.execute(
                "SELECT status FROM translation_units WHERE block_id = ?",
                (block_id,),
            ).fetchone()

            if (
                current
                and current["status"] == "human_validated"
                and status != "human_validated"
            ):
                return

            self._conn.execute(
                """
                UPDATE translation_units
                SET translated_text = ?, status = ?
                WHERE block_id = ?
                """,
                (translated_text, status, block_id),
            )
            self._conn.commit()

    def count_duplicates(
        self, source_texts: list[str], source_file: str
    ) -> dict[str, DuplicateStats]:
        """Count how often each of several source texts occurs in the project.

        Answered for a whole page at once rather than row by row, since the
        review list would otherwise fire one query per displayed line.

        Args:
            source_texts: The texts to look up, duplicates allowed.
            source_file: The file being displayed, used to tell occurrences
                sitting elsewhere from those in the file at hand.

        Returns:
            Stats per source text, restricted to the texts occurring more
            than once. `total` counts every occurrence including the
            displayed one, `other_files` only those outside source_file.
        """
        unique = list(dict.fromkeys(source_texts))
        if not unique:
            return {}
        placeholders = ",".join("?" * len(unique))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    source_text,
                    COUNT(*) AS total,
                    SUM(CASE WHEN source_file != ? THEN 1 ELSE 0 END) AS other_files
                FROM translation_units
                WHERE source_text IN ({placeholders})
                GROUP BY source_text
                HAVING total > 1
                """,
                [source_file, *unique],
            ).fetchall()
        return {
            row["source_text"]: DuplicateStats(
                total=row["total"], other_files=row["other_files"]
            )
            for row in rows
        }

    def count_matches_by_file(
        self,
        search_query: str,
        status_filter: str | None = None,
        character: str | None = None,
        needs_review: bool = False,
    ) -> dict[str, int]:
        """Count the units matching a search in every file of the project.

        The review list only ever shows one file, so without this neither
        the search field, the speaker filter nor the review flag can tell
        an absent line from one living in another file. The status filter
        is applied too, so a count always matches what opening that file
        shows.

        Args:
            search_query: Substring searched in source_text/translated_text.
            status_filter: Optional status the units must have.
            character: Optional Ren'Py character variable the lines belong to.
            needs_review: Count only the lines flagged for a second look.

        Returns:
            Match count per source file, files without a match omitted.
            Empty when nothing narrows the project down, since the panel
            then has no count to show.
        """
        query = search_query.strip()
        if not query and not character and not needs_review:
            return {}
        conditions: list[str] = []
        params: list[str] = []
        if query:
            like = _like_pattern(query)
            conditions.append(_SEARCH_CONDITION)
            params.extend([like, like])
        if character:
            conditions.append("character_variable = ?")
            params.append(character)
        if needs_review:
            conditions.append("needs_review = 1")
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT source_file, COUNT(*) AS matches
                FROM translation_units
                WHERE {" AND ".join(conditions)}
                GROUP BY source_file
                """,
                params,
            ).fetchall()
        return {row["source_file"]: row["matches"] for row in rows}

    def find_duplicate_block_ids(
        self, source_text: str, exclude_block_id: str
    ) -> list[str]:
        """Return the units sharing a source text and still open to a change.

        Units already human_validated are left out: they carry reviewed
        work that must not be replaced, and update_translations() would
        refuse them anyway.

        Args:
            source_text: The exact source text to match.
            exclude_block_id: The unit the text comes from, never returned.

        Returns:
            Block ids of the matching units, in file order.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT block_id FROM translation_units
                WHERE source_text = ?
                  AND block_id != ?
                  AND status != 'human_validated'
                ORDER BY source_file, source_line
                """,
                (source_text, exclude_block_id),
            ).fetchall()
        return [row["block_id"] for row in rows]

    def update_translations(
        self, entries: list[tuple[str, str, TranslationStatus]]
    ) -> int:
        """Apply many translations in a single transaction.

        Carries the same protection as update_translation(): a
        human_validated unit is never downgraded. Batching is what makes the
        bulk paths usable, since they come in whole-project bursts (adopting
        an existing tl/ folder, re-keying after an SDK rebuild) and one
        commit per row freezes the UI for minutes on a large game.

        Args:
            entries: (block_id, translated_text, status) triples.

        Returns:
            The number of units actually updated.
        """
        if not entries:
            return 0
        with self._lock:
            cursor = self._conn.executemany(
                """
                UPDATE translation_units
                SET translated_text = ?, status = ?
                WHERE block_id = ?
                  AND (status != 'human_validated' OR ? = 'human_validated')
                """,
                [
                    (translated_text, status, block_id, status)
                    for block_id, translated_text, status in entries
                ],
            )
            updated = cursor.rowcount
            self._conn.commit()
            return updated

    def mark_as_draft(self, block_id: str, translated_text: str) -> TranslationStatus:
        """Store a unit's live text as a draft, or reset it when emptied.

        Unlike update_translation(), this always applies regardless of
        the current status. It exists for the one case where a human
        should be allowed to un-validate a unit: they are actively
        editing a field that was previously ai_suggested or
        human_validated, so the stored text no longer matches what's
        displayed. The field's current value is persisted so the edit
        (including clearing it) is not lost if the user navigates away
        before pressing validate.

        Non-empty text becomes a 'draft' so it is counted, cleared and
        skipped by automatic jobs like any other translated state;
        emptied text falls back to 'not_translated'.

        Args:
            block_id: The unique identifier of the block.
            translated_text: The field's current value.

        Returns:
            The resulting status: 'draft' if text remains, else
            'not_translated'.
        """
        status: TranslationStatus = (
            "draft" if translated_text.strip() else "not_translated"
        )
        with self._lock:
            self._conn.execute(
                "UPDATE translation_units SET status = ?, translated_text = ?"
                " WHERE block_id = ?",
                (status, translated_text, block_id),
            )
            self._conn.commit()
        return status

    def set_needs_review(self, block_id: str, needs_review: bool) -> None:
        """Raise or clear the "look at this again" flag on a unit.

        Independent of the status and of the translation: a line can be
        flagged untranslated, validated, or anywhere in between, and
        nothing but this call ever moves the flag.

        Args:
            block_id: The unique identifier of the block.
            needs_review: True to flag the line, False to clear it.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE translation_units SET needs_review = ? WHERE block_id = ?",
                (int(needs_review), block_id),
            )
            self._conn.commit()

    def set_note(self, block_id: str, note: str) -> None:
        """Store the free-form note a translator left on a unit.

        A note raises the review flag, and that is an invariant rather
        than a convenience: nothing lists the notes on their own, so one
        sitting on an unflagged line could be found again only by
        whoever remembered which line carried it.

        Args:
            block_id: The unique identifier of the block.
            note: The note to keep, empty to drop the one already there.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE translation_units"
                " SET note = ?,"
                "     needs_review = CASE WHEN ? != '' THEN 1 ELSE needs_review END"
                " WHERE block_id = ?",
                (note or None, note, block_id),
            )
            self._conn.commit()

    def count_modified_since(self, timestamp: str | None) -> int:
        """Count units edited after a given instant.

        A row still holding its insertion timestamp and no text was never
        edited, so a re-extraction adding blocks is not mistaken for pending
        edits. A cleared translation does count: the source text has to be
        written back to the .rpy file just like a new translation.

        A None timestamp means the project was never written out, so every
        unit carrying work is still pending. Callers get one count either
        way rather than a count and a separate "never saved" case, since
        the answer they act on is the same number.

        Args:
            timestamp: UTC 'YYYY-MM-DD HH:MM:SS' string, in the same format
                as the updated_at column maintained by the database trigger,
                or None to count without a lower bound.

        Returns:
            The number of units whose row changed after that instant.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS total FROM translation_units
                WHERE updated_at > COALESCE(?, '')
                  AND (translated_text != '' OR created_at != updated_at)
                """,
                (timestamp,),
            ).fetchone()
        return int(row["total"])

    def clear_translations(
        self,
        source_file: str | None = None,
        statuses: list[TranslationStatus] | None = None,
    ) -> int:
        """Reset translations back to not_translated, clearing their text.

        Bypasses the human_validated protection in update_translation()
        since this is an explicit, deliberate bulk action the user
        confirmed, not an automated AI-suggestion update. Restricting the
        statuses is what makes it usable after a bad AI job: the point is
        then to drop the suggestions without touching reviewed work.

        Args:
            source_file: If given, only clear units from this file;
                otherwise clear every unit in the project.
            statuses: If given, only clear units currently in one of these
                statuses; otherwise clear whatever is translated.

        Returns:
            The number of units that were actually cleared.
        """
        conditions = ["status != 'not_translated'"]
        params: list[str] = []
        if source_file is not None:
            conditions.append("source_file = ?")
            params.append(source_file)
        if statuses:
            conditions.append(f"status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)

        with self._lock:
            cursor = self._conn.execute(
                f"""
                UPDATE translation_units
                SET translated_text = '', status = 'not_translated'
                WHERE {" AND ".join(conditions)}
                """,
                params,
            )
            self._conn.commit()
            return cursor.rowcount

    def character_variables(self) -> list[str]:
        """Return every character variable speaking in the project.

        Returns:
            The distinct character variables, sorted, lines with no
            speaker left out.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT DISTINCT character_variable FROM translation_units
                WHERE character_variable IS NOT NULL AND character_variable != ''
                ORDER BY character_variable
                """
            ).fetchall()
        return [row["character_variable"] for row in rows]

    def count_by_status(self) -> dict[str, int]:
        """Return a dict mapping each status to its row count.

        Returns:
            Dict like {'not_translated': 500, 'human_validated': 12}.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) as n FROM translation_units GROUP BY status"
            ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def all_block_ids(self) -> set[str]:
        """Return the set of every block id stored in the project.

        Returns:
            All block ids currently in the database.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT block_id FROM translation_units"
            ).fetchall()
        return {row["block_id"] for row in rows}

    def project_progress(self) -> ProjectProgress:
        """Return how far the whole project is, in lines and in words.

        Words are what a translator plans and bills with, so they are
        counted alongside the lines. The count is the number of
        space-separated runs in the source text: an estimate, not a
        billing-grade figure, since Ren'Py markup ({i}, [name]) counts as
        text and escaped newlines do not separate words.

        Counting them is four string operations per row, which on a large
        game is most of what this costs: 44 ms of the 47, and 27 of those
        for the project total alone. That total is over the source texts,
        so only an extraction can move it, and it is remembered until one
        does. The validated share is asked every time, since that is the
        figure the screen is watching.

        Returns:
            Totals over every unit of the project, validated ones apart.
        """
        words = (
            "CASE WHEN TRIM(source_text) = '' THEN 0 ELSE"
            " LENGTH(TRIM(source_text))"
            " - LENGTH(REPLACE(TRIM(source_text), ' ', '')) + 1 END"
        )
        with self._lock:
            if self._source_words is None:
                self._source_words = int(
                    self._conn.execute(
                        f"SELECT COALESCE(SUM({words}), 0) FROM translation_units"
                    ).fetchone()[0]
                )
            row = self._conn.execute(f"""
                SELECT
                    COUNT(*) AS lines,
                    COALESCE(SUM(CASE WHEN status = 'human_validated'
                        THEN 1 ELSE 0 END), 0) AS validated_lines,
                    COALESCE(SUM(CASE WHEN status = 'human_validated'
                        THEN {words} ELSE 0 END), 0) AS validated_words
                FROM translation_units
            """).fetchone()
        return ProjectProgress(
            lines=int(row["lines"]),
            validated_lines=int(row["validated_lines"]),
            words=self._source_words,
            validated_words=int(row["validated_words"]),
        )

    def get_files(self) -> list[FileStats]:
        """Return all distinct source files with their block and status counts.

        Returns:
            List of FileStats sorted by source_file.
        """
        with self._lock:
            rows = self._conn.execute("""
                SELECT
                    source_file,
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'human_validated' THEN 1 ELSE 0 END)
                        AS validated,
                    SUM(CASE WHEN status = 'ai_suggested' THEN 1 ELSE 0 END)
                        AS ai_suggested,
                    SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END)
                        AS draft,
                    SUM(CASE WHEN status = 'imported' THEN 1 ELSE 0 END)
                        AS imported
                FROM translation_units
                GROUP BY source_file
                ORDER BY source_file
            """).fetchall()
        return [
            FileStats(
                source_file=row["source_file"],
                total=row["total"],
                validated=row["validated"],
                ai_suggested=row["ai_suggested"],
                draft=row["draft"],
                imported=row["imported"],
            )
            for row in rows
        ]

    @staticmethod
    def _page_filters(
        source_file: str,
        status_filter: str | None,
        search_query: str,
        character: str | None = None,
        needs_review: bool = False,
    ) -> tuple[str, list[str]]:
        """Build the WHERE clause shared by the paginated review queries.

        Args:
            source_file: Exact source_file value to filter on.
            status_filter: Optional status ('not_translated', 'human_validated', …).
            search_query: Optional substring search on source_text/translated_text.
            character: Optional Ren'Py character variable the line belongs to.
            needs_review: Keep only the lines flagged for a second look.

        Returns:
            Tuple of (SQL condition, parameters in placeholder order).
        """
        conditions: list[str] = ["source_file = ?"]
        params: list[str] = [source_file]

        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)

        if character:
            conditions.append("character_variable = ?")
            params.append(character)

        if needs_review:
            conditions.append("needs_review = 1")

        if search_query.strip():
            conditions.append(_SEARCH_CONDITION)
            like = _like_pattern(search_query.strip())
            params.extend([like, like])

        return " AND ".join(conditions), params

    def get_neighbours(
        self, source_file: str, source_line: int, radius: int
    ) -> list[TranslationUnit]:
        """Return the window of the file centred on one of its lines.

        Answered outside the filter and the pagination of the review list:
        the point is precisely to show the lines the current view hides,
        since a reply reads nothing like the question it answers.

        The line itself is part of the window rather than cut out of it.
        A caller showing only the neighbours shows a list with no anchor,
        where the lines that come before are indistinguishable from the
        ones that follow.

        Args:
            source_file: File the line belongs to.
            source_line: The line the window is centred on.
            radius: How many lines to take on each side.

        Returns:
            The units around the line and the line itself, in file order.
            Empty when the file holds nothing at that line.
        """
        with self._lock:
            before = self._conn.execute(
                f"""
                SELECT {_SELECT_COLUMNS} FROM translation_units
                WHERE source_file = ? AND source_line < ?
                ORDER BY source_line DESC
                LIMIT ?
                """,
                (source_file, source_line, radius),
            ).fetchall()
            here = self._conn.execute(
                f"""
                SELECT {_SELECT_COLUMNS} FROM translation_units
                WHERE source_file = ? AND source_line = ?
                ORDER BY source_line
                """,
                (source_file, source_line),
            ).fetchall()
            after = self._conn.execute(
                f"""
                SELECT {_SELECT_COLUMNS} FROM translation_units
                WHERE source_file = ? AND source_line > ?
                ORDER BY source_line
                LIMIT ?
                """,
                (source_file, source_line, radius),
            ).fetchall()
        return [_unit_from_row(row) for row in [*reversed(before), *here, *after]]

    def get_matching(
        self,
        source_file: str,
        status_filter: str | None = None,
        search_query: str = "",
        character: str | None = None,
        needs_review: bool = False,
    ) -> list[TranslationUnit]:
        """Return every unit of a file the review filters keep, unpaginated.

        Exists for the one filter SQL cannot express: a quality warning is
        computed in Python from the source and the translation, so the
        whole file has to be handed over and sliced afterwards.

        Args:
            source_file: Exact source_file value to filter on.
            status_filter: Optional status ('not_translated', 'human_validated', …).
            search_query: Optional substring search on source_text/translated_text.
            character: Optional Ren'Py character variable the line belongs to.
            needs_review: Keep only the lines flagged for a second look.

        Returns:
            The matching units in file order.
        """
        where, params = self._page_filters(
            source_file, status_filter, search_query, character, needs_review
        )
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM translation_units"
                f" WHERE {where} ORDER BY source_line",
                params,
            ).fetchall()
        return [_unit_from_row(row) for row in rows]

    def get_page(
        self,
        source_file: str,
        page: int,
        page_size: int,
        status_filter: str | None = None,
        search_query: str = "",
        character: str | None = None,
        needs_review: bool = False,
    ) -> tuple[list[TranslationUnit], int]:
        """Return one page of units for a given file plus the total matching count.

        Args:
            source_file: Exact source_file value to filter on.
            page: Zero-based page index.
            page_size: Number of rows per page.
            status_filter: Optional status ('not_translated', 'human_validated', …).
            search_query: Optional substring search on source_text/translated_text.
            character: Optional Ren'Py character variable the line belongs to.
            needs_review: Keep only the lines flagged for a second look.

        Returns:
            Tuple of (units for this page, total matching row count).
        """
        where, params = self._page_filters(
            source_file, status_filter, search_query, character, needs_review
        )

        with self._lock:
            total: int = self._conn.execute(
                f"SELECT COUNT(*) FROM translation_units WHERE {where}", params
            ).fetchone()[0]

            offset = page * page_size
            rows = self._conn.execute(
                f"""
                SELECT {_SELECT_COLUMNS} FROM translation_units
                WHERE {where}
                ORDER BY source_line
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()

        return [_unit_from_row(row) for row in rows], total


@dataclass
class Character:
    """A single row from the characters table."""

    id: int
    variable: str
    display_name: str
    notes: str | None


class CharacterRepository:
    """CRUD operations for the character glossary."""

    def __init__(
        self, conn: sqlite3.Connection, lock: threading.Lock | None = None
    ) -> None:
        """Initialize with an open database connection.

        Args:
            conn: Active sqlite3 connection with row_factory = sqlite3.Row.
            lock: Lock serializing access to conn across threads. A dedicated
                lock is created if omitted, but callers that share the same
                connection across threads must pass the same lock to every
                repository instance.
        """
        self._conn = conn
        self._lock = lock or threading.Lock()

    def upsert(self, variable: str, display_name: str) -> None:
        """Insert or update a character by its Ren'Py variable name.

        Args:
            variable: The Ren'Py variable the character is defined as.
            display_name: The name shown to players.
        """
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO characters (variable, display_name)
                VALUES (?, ?)
                ON CONFLICT(variable) DO UPDATE SET display_name = excluded.display_name
                """,
                (variable, display_name),
            )
            self._conn.commit()

    def update_notes(self, variable: str, notes: str) -> None:
        """Update free-form notes for a character.

        Args:
            variable: The Ren'Py variable identifying the character.
            notes: Free-form notes (gender, register, remarks…).
        """
        with self._lock:
            self._conn.execute(
                "UPDATE characters SET notes = ? WHERE variable = ?",
                (notes, variable),
            )
            self._conn.commit()

    def get_all(self) -> list[Character]:
        """Return all characters ordered by display name.

        Returns:
            List of Character dataclass instances.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, variable, display_name, notes FROM characters"
                " ORDER BY display_name"
            ).fetchall()
        return [Character(**dict(row)) for row in rows]

    def delete(self, variable: str) -> None:
        """Remove a character entry.

        Args:
            variable: The Ren'Py variable identifying the character.
        """
        with self._lock:
            self._conn.execute("DELETE FROM characters WHERE variable = ?", (variable,))
            self._conn.commit()

    def delete_all(self) -> int:
        """Remove every character of the project.

        Auto-detection can find the characters again, but not their notes:
        those are written by hand and nothing else holds them.

        Returns:
            The number of characters that were deleted.
        """
        with self._lock:
            cursor = self._conn.execute("DELETE FROM characters")
            self._conn.commit()
            return cursor.rowcount


class ProjectMetaRepository:
    """Key/value store for per-project metadata (universe summary, etc.)."""

    def __init__(
        self, conn: sqlite3.Connection, lock: threading.Lock | None = None
    ) -> None:
        """Initialize with an open database connection.

        Args:
            conn: Active sqlite3 connection with row_factory = sqlite3.Row.
            lock: Lock serializing access to conn across threads. A dedicated
                lock is created if omitted, but callers that share the same
                connection across threads must pass the same lock to every
                repository instance.
        """
        self._conn = conn
        self._lock = lock or threading.Lock()

    def get(self, key: str) -> str | None:
        """Return the value for a given key, or None if absent.

        Args:
            key: The metadata key to look up.

        Returns:
            The stored value, or None if not set.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM project_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        """Insert or replace a key/value pair.

        Args:
            key: The metadata key to store.
            value: The value to associate with the key.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO project_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
            self._conn.commit()
