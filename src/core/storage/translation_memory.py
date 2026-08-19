"""Translation memory shared by every project of this machine.

A project database only ever knows its own lines, so a translator moving
to the next episode of a series retypes what they already validated in the
previous one. Validated translations are therefore also written here, in a
single SQLite file next to settings.json, keyed by language pair and exact
source text.

A source text is matched twice: on itself, and on a normalised key that
ignores letter case, repeated whitespace and trailing punctuation. A visual
novel repeats itself while varying barely, and "Riley...", "Riley?!" and
"RILEY!" are one line to translate, not three. Measured over half of a
40 820-unit script used as the memory for the other half, the normalised
key answers 286 further source texts, covering 1595 lines that exact
matching leaves empty.

Nothing looser is served. A similarity search over the same corpus adds
652 more, but reads them off shared markup and boilerplate rather than
shared meaning: at 0.91 it pairs "Bad dog! A complete guide to negative
reinforcement" with its "Good dog! ... positive reinforcement" counterpart,
which would put the opposite of the source in front of a player. A wrong
translation costs more than an empty field.

The normalised key leaves every [interpolation] and {tag} untouched, so two
texts whose code differs never share one. That is what keeps quality.check()
from meeting a variable that belongs to another source.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from pathlib import Path

from core.app_dirs import config_dir

_logger = logging.getLogger(__name__)

_CODE = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
_SPACES = re.compile(r"\s+")
_TRAILING = re.compile(r"[.!?…,;:\-—– ]+$")


def normalized_key(text: str) -> str:
    """Return the key under which near-identical source texts meet.

    Letter case is folded, runs of whitespace become one space and
    trailing punctuation goes. Interpolations and tags are copied
    verbatim, case included: a key is built from the segments between
    them, never from their contents, so "Hello [MC]" and "Hello [mc]"
    stay apart and no translation can arrive carrying a variable its new
    source does not have.

    A text made only of punctuation would otherwise normalise to nothing
    and meet every other one, so the trailing trim is dropped when it
    empties the key.

    Args:
        text: The source text, as Ren'Py wrote it.

    Returns:
        The key. Equal keys mean the two texts differ only in case,
        spacing or trailing punctuation.
    """
    parts: list[str] = []
    last = 0
    for match in _CODE.finditer(text):
        parts.append(_SPACES.sub(" ", text[last : match.start()].lower()))
        parts.append(match.group())
        last = match.end()
    parts.append(_SPACES.sub(" ", text[last:].lower()))
    folded = "".join(parts).strip()
    return _TRAILING.sub("", folded) or folded


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memory (
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    source_text     TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source_language, target_language, source_text)
);
"""

_ADD_NORMALIZED_COLUMN = """
ALTER TABLE memory ADD COLUMN normalized_text TEXT NOT NULL DEFAULT '';
"""

_CREATE_NORMALIZED_INDEX = """
CREATE INDEX IF NOT EXISTS idx_memory_normalized
    ON memory (source_language, target_language, normalized_text);
"""

_MAX_LOOKUP_PARAMS = 500


class TranslationMemory:
    """Store and look up validated translations across projects."""

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the memory.

        Args:
            path: Location of the SQLite file. Defaults to
                <config_dir>/memory.db.
        """
        self._path = path or config_dir() / "memory.db"
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        """Open the memory database, creating it on first use.

        Returns:
            The open connection, reused on every later call.
        """
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_CREATE_TABLE)
            self._add_normalized_text(self._conn)
            self._conn.executescript(_CREATE_NORMALIZED_INDEX)
            self._conn.commit()
        return self._conn

    @staticmethod
    def _add_normalized_text(conn: sqlite3.Connection) -> None:
        """Add the normalised key column to a memory that predates it.

        The column is written once, here, for every row already stored:
        a memory filled before this existed would otherwise answer only
        the exact matches it always did, and nothing would ever fill it
        in, entries being rewritten only when a translator validates the
        same source text again.

        Args:
            conn: The open memory connection.
        """
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory)")}
        if "normalized_text" in columns:
            return
        conn.executescript(_ADD_NORMALIZED_COLUMN)
        rows = conn.execute(
            "SELECT source_language, target_language, source_text FROM memory"
        ).fetchall()
        conn.executemany(
            """
            UPDATE memory SET normalized_text = ?
            WHERE source_language = ? AND target_language = ? AND source_text = ?
            """,
            [
                (
                    normalized_key(row["source_text"]),
                    row["source_language"],
                    row["target_language"],
                    row["source_text"],
                )
                for row in rows
            ],
        )

    def remember(
        self,
        entries: list[tuple[str, str]],
        source_language: str,
        target_language: str,
    ) -> None:
        """Record validated translations for a language pair.

        A later validation of the same source text replaces the earlier
        one: the memory holds what the translator settled on last.

        Failures are logged and swallowed. The memory is a convenience
        shared by every project, and a machine where it cannot be written
        must still be able to translate the project at hand.

        Args:
            entries: (source text, translation) pairs, both non-empty.
            source_language: Language the source text is written in.
            target_language: Language the translation is written in.
        """
        rows = [
            (
                source_language,
                target_language,
                source,
                normalized_key(source),
                translated,
            )
            for source, translated in entries
            if source and translated
        ]
        if not rows:
            return
        try:
            with self._lock:
                conn = self._connect()
                conn.executemany(
                    """
                    INSERT INTO memory
                        (source_language, target_language, source_text,
                         normalized_text, translated_text, updated_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(source_language, target_language, source_text)
                    DO UPDATE SET translated_text = excluded.translated_text,
                                  normalized_text = excluded.normalized_text,
                                  updated_at = excluded.updated_at
                    """,
                    rows,
                )
                conn.commit()
        except sqlite3.Error:
            _logger.warning("Could not write to the translation memory", exc_info=True)

    def lookup(
        self,
        source_texts: list[str],
        source_language: str,
        target_language: str,
    ) -> dict[str, str]:
        """Return the stored translation of each known source text.

        Two passes. The first matches the text as it is written. The
        second takes what the first left over and matches it on the
        normalised key, so a line differing only in case, spacing or
        trailing punctuation is answered too. An exact hit is never
        replaced by a normalised one, which is why the order matters.

        Queried in slices, since a whole game is asked at once and SQLite
        caps the number of bound parameters per statement.

        Args:
            source_texts: The texts to look up, duplicates allowed.
            source_language: Language the source text is written in.
            target_language: Language the translation is wanted in.

        Returns:
            Translation per source text, texts absent from the memory
            omitted. Empty when the memory cannot be read.
        """
        unique = [text for text in dict.fromkeys(source_texts) if text]
        if not unique:
            return {}
        try:
            with self._lock:
                conn = self._connect()
                found = self._select(
                    conn, "source_text", unique, source_language, target_language
                )
                missing = [text for text in unique if text not in found]
                by_key = self._select(
                    conn,
                    "normalized_text",
                    list(dict.fromkeys(normalized_key(text) for text in missing)),
                    source_language,
                    target_language,
                )
        except sqlite3.Error:
            _logger.warning("Could not read the translation memory", exc_info=True)
            return {}
        for text in missing:
            translated = by_key.get(normalized_key(text))
            if translated is not None:
                found[text] = translated
        return found

    @staticmethod
    def _select(
        conn: sqlite3.Connection,
        column: str,
        values: list[str],
        source_language: str,
        target_language: str,
    ) -> dict[str, str]:
        """Return the translation stored against each value of one column.

        Several entries can share a normalised key, so the rows come in
        oldest first and the later ones overwrite: the answer is the one
        the translator settled on last, with the source text breaking a
        tie between two validated within the same second.

        Args:
            conn: The open memory connection.
            column: Column to match on, source_text or normalized_text.
            values: The values to look up, already deduplicated.
            source_language: Language the source text is written in.
            target_language: Language the translation is wanted in.

        Returns:
            Translation per value, values matching nothing omitted.
        """
        found: dict[str, str] = {}
        for start in range(0, len(values), _MAX_LOOKUP_PARAMS):
            batch = values[start : start + _MAX_LOOKUP_PARAMS]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"""
                SELECT {column} AS matched, translated_text FROM memory
                WHERE source_language = ? AND target_language = ?
                  AND {column} IN ({placeholders})
                ORDER BY updated_at, source_text
                """,
                [source_language, target_language, *batch],
            ).fetchall()
            found.update({row["matched"]: row["translated_text"] for row in rows})
        return found

    def stats(self) -> list[tuple[str, str, int]]:
        """Return how much is stored, per language pair.

        Returns:
            (source language, target language, entry count) triples, the
            largest pair first. Empty when the memory cannot be read.
        """
        try:
            with self._lock:
                conn = self._connect()
                rows = conn.execute("""
                    SELECT source_language, target_language, COUNT(*) AS n
                    FROM memory
                    GROUP BY source_language, target_language
                    ORDER BY n DESC
                """).fetchall()
        except sqlite3.Error:
            _logger.warning("Could not read the translation memory", exc_info=True)
            return []
        return [
            (row["source_language"], row["target_language"], int(row["n"]))
            for row in rows
        ]

    def forget(self, source_language: str, target_language: str) -> int:
        """Drop everything stored for one language pair.

        Args:
            source_language: Language the source text is written in.
            target_language: Language the translation is written in.

        Returns:
            The number of entries removed, zero when nothing could be
            written.
        """
        try:
            with self._lock:
                conn = self._connect()
                cursor = conn.execute(
                    "DELETE FROM memory"
                    " WHERE source_language = ? AND target_language = ?",
                    (source_language, target_language),
                )
                conn.commit()
                return int(cursor.rowcount)
        except sqlite3.Error:
            _logger.warning("Could not write to the translation memory", exc_info=True)
            return 0

    def close(self) -> None:
        """Close the connection, if one was ever opened."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


translation_memory = TranslationMemory()
