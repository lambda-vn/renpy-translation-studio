"""SQLite database setup and connection management."""

import logging
import sqlite3
import threading
from pathlib import Path

_logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS translation_units (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id        TEXT NOT NULL UNIQUE,
    source_file     TEXT NOT NULL,
    source_line     INTEGER NOT NULL,
    character_variable TEXT,
    source_text     TEXT NOT NULL,
    translated_text TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'not_translated'
                    CHECK(status IN (
                        'not_translated', 'draft', 'imported',
                        'ai_suggested', 'human_validated'
                    )),
    needs_review    INTEGER NOT NULL DEFAULT 0,
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_status ON translation_units(status);
"""

_MIGRATE_STATUS_CHECK = """
DROP TRIGGER IF EXISTS update_timestamp;
DROP INDEX IF EXISTS idx_status;
ALTER TABLE translation_units RENAME TO _translation_units_old;
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
                        'not_translated', 'draft', 'imported',
                        'ai_suggested', 'human_validated'
                    )),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO translation_units
    (id, block_id, source_file, source_line, character_variable,
     source_text, translated_text, status, created_at, updated_at)
    SELECT id, block_id, source_file, source_line, character_variable,
           source_text, translated_text, status, created_at, updated_at
    FROM _translation_units_old;
DROP TABLE _translation_units_old;
CREATE INDEX IF NOT EXISTS idx_status ON translation_units(status);
"""

_MIGRATE_REVIEW_COLUMNS = """
ALTER TABLE translation_units ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0;
ALTER TABLE translation_units ADD COLUMN note TEXT;
DROP TRIGGER IF EXISTS update_timestamp;
"""

_UPDATE_TIMESTAMP = """
CREATE TRIGGER IF NOT EXISTS update_timestamp
AFTER UPDATE OF translated_text, status ON translation_units
BEGIN
    UPDATE translation_units SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;
"""

_CREATE_CHARACTERS_TABLE = """
CREATE TABLE IF NOT EXISTS characters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    variable        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS update_characters_timestamp
AFTER UPDATE ON characters
BEGIN
    UPDATE characters SET updated_at = datetime('now') WHERE id = NEW.id;
END;
"""

_CREATE_PROJECT_META_TABLE = """
CREATE TABLE IF NOT EXISTS project_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);
"""


class Database:
    """Manages the SQLite connection for a single project."""

    @staticmethod
    def path_for(project: Path) -> Path:
        """Return where a project keeps its database.

        Args:
            project: The Ren'Py project root.

        Returns:
            The .rts/translations.db path under that root, whether or not
            it exists yet.
        """
        return project / ".rts" / "translations.db"

    def __init__(self, db_path: Path) -> None:
        """Initialize with the path to the database file.

        Args:
            db_path: Path to the .db file (will be created if absent).
        """
        self._path = db_path
        self._conn: sqlite3.Connection | None = None
        self.lock: threading.Lock = threading.Lock()

    def connect(self) -> None:
        """Open the connection, switch to WAL, and create tables if needed."""
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._enable_wal()
        self._conn.executescript(
            _CREATE_TABLE
            + _UPDATE_TIMESTAMP
            + _CREATE_CHARACTERS_TABLE
            + _CREATE_PROJECT_META_TABLE
        )
        self._migrate_status_check()
        self._migrate_review_columns()
        self._conn.commit()

    def _enable_wal(self) -> None:
        """Let a reader and a writer work at the same time.

        A project is no longer opened by one process at a time. The MCP
        server is a second one by construction, and nothing stops two
        windows of the application either. Under the default rollback
        journal a writer locks the whole file, so the other side waits
        out its five second busy timeout and then fails, which a bulk
        action holds the lock long enough to cause.

        The mode is written into the file header, so this converts the
        database once and every later connection inherits it. Two
        sidecars appear next to it, translations.db-wal and -shm, which
        matters only to someone copying a project by hand.

        A filesystem without shared memory, a network share typically,
        refuses WAL and keeps the previous mode rather than failing. The
        application still works there, with the contention it had
        before, so this warns instead of raising.

        connect_readonly() keeps working: a WAL database opens read-only
        as long as it was closed cleanly, and a project it cannot read is
        already skipped rather than fatal.
        """
        mode = self.conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            _logger.warning(
                "Could not switch %s to WAL, still in %s. Two processes "
                "reaching this project at once may block each other.",
                self._path,
                mode,
            )

    def _migrate_status_check(self) -> None:
        """Widen the status CHECK constraint to the current list of statuses.

        Databases created before a status was introduced reject it via their
        table-level CHECK. SQLite cannot alter a CHECK in place, so the table
        is rebuilt whenever its stored schema predates the newest status.
        Testing for that one status is enough: a base missing it also misses
        every status added before it, and a single rebuild installs them all.
        """
        conn = self.conn
        row = conn.execute(
            "SELECT sql FROM sqlite_master"
            " WHERE type = 'table' AND name = 'translation_units'"
        ).fetchone()
        if row is None or "'imported'" in row[0]:
            return
        conn.executescript(_MIGRATE_STATUS_CHECK)
        conn.executescript(_UPDATE_TIMESTAMP)

    def _migrate_review_columns(self) -> None:
        """Add the manual review flag and per-line note to an older database.

        Both are plain columns, so ALTER TABLE is enough and the rows are
        left untouched. Must run after _migrate_status_check(), whose
        rebuild copies a fixed column list and would drop them.

        The timestamp trigger is narrowed at the same time: updated_at
        answers "does this line still have to be written to the .rpy
        file", which the toolbar reads to count unsaved lines. Flagging a
        line or writing a note changes nothing on disk, so only an update
        touching the translation or the status may move it.
        """
        conn = self.conn
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(translation_units)")
        }
        if not columns or "needs_review" in columns:
            return
        conn.executescript(_MIGRATE_REVIEW_COLUMNS)
        conn.executescript(_UPDATE_TIMESTAMP)

    def connect_readonly(self) -> None:
        """Open the connection read-only, without running schema migrations.

        Meant for cheap, side-effect-free inspection such as counting rows
        to decide whether a project is resumable. Unlike connect(), this
        never executes DDL, so it neither rewrites the journal of every
        inspected database nor creates missing optional tables. Callers
        must therefore tolerate a legacy schema where a table is absent.
        """
        self._conn = sqlite3.connect(
            f"{self._path.as_uri()}?mode=ro", uri=True, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the active connection.

        Returns:
            The open sqlite3.Connection.

        Raises:
            RuntimeError: If connect() has not been called.
        """
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn
