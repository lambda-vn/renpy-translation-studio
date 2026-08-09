"""Translation memory shared by every project of this machine.

A project database only ever knows its own lines, so a translator moving
to the next episode of a series retypes what they already validated in the
previous one. Validated translations are therefore also written here, in a
single SQLite file next to settings.json, keyed by language pair and exact
source text.

Only exact matches are served: a fuzzy hit would have to be reviewed
anyway, and a wrong one costs more than an empty field.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from core.app_dirs import config_dir

_logger = logging.getLogger(__name__)

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
            self._conn.commit()
        return self._conn

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
            (source_language, target_language, source, translated)
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
                         translated_text, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(source_language, target_language, source_text)
                    DO UPDATE SET translated_text = excluded.translated_text,
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
        found: dict[str, str] = {}
        try:
            with self._lock:
                conn = self._connect()
                for start in range(0, len(unique), _MAX_LOOKUP_PARAMS):
                    batch = unique[start : start + _MAX_LOOKUP_PARAMS]
                    placeholders = ",".join("?" * len(batch))
                    rows = conn.execute(
                        f"""
                        SELECT source_text, translated_text FROM memory
                        WHERE source_language = ? AND target_language = ?
                          AND source_text IN ({placeholders})
                        """,
                        [source_language, target_language, *batch],
                    ).fetchall()
                    found.update(
                        {row["source_text"]: row["translated_text"] for row in rows}
                    )
        except sqlite3.Error:
            _logger.warning("Could not read the translation memory", exc_info=True)
            return {}
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
