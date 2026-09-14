//! SQLite connection management for a single project.
//!
//! Port of `core/storage/database.py`, targeting the schema already
//! frozen by the 1.0.0 release: the final column set (`needs_review`,
//! `note`) and the five-status CHECK constraint. The two migrations
//! Python carries for pre-1.0 databases (`_migrate_status_check`,
//! `_migrate_review_columns`) are deliberately not ported — the
//! compatibility policy in `CLAUDE.md` promises reading what 1.0.0
//! wrote, not re-deriving the upgrade path from 0.x, which a user
//! already crossed by going through 1.x first.

use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};

const CREATE_TABLE: &str = "
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
";

const UPDATE_TIMESTAMP: &str = "
CREATE TRIGGER IF NOT EXISTS update_timestamp
AFTER UPDATE OF translated_text, status ON translation_units
BEGIN
    UPDATE translation_units SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;
";

const CREATE_CHARACTERS_TABLE: &str = "
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
";

const CREATE_PROJECT_META_TABLE: &str = "
CREATE TABLE IF NOT EXISTS project_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);
";

// See database.py's own comment: the indexes are created last since a
// migration rebuild (not ported here, but the ordering is kept in case
// one returns) would drop every index attached to the table it replaces.
const CREATE_INDEXES: &str = "
CREATE INDEX IF NOT EXISTS idx_status ON translation_units(status);
CREATE INDEX IF NOT EXISTS idx_file_line
    ON translation_units(source_file, source_line);
CREATE INDEX IF NOT EXISTS idx_file_status
    ON translation_units(source_file, status);
CREATE INDEX IF NOT EXISTS idx_source_text ON translation_units(source_text);
CREATE INDEX IF NOT EXISTS idx_pending ON translation_units(updated_at)
    WHERE translated_text != '' OR created_at != updated_at;
";

pub struct Database {
    conn: Connection,
}

impl Database {
    /// Where a project keeps its database: `<project>/.rts/translations.db`,
    /// whether or not it exists yet.
    pub fn path_for(project: &Path) -> PathBuf {
        project.join(".rts").join("translations.db")
    }

    /// Open the connection, switch to WAL, and create tables if needed.
    pub fn open(db_path: &Path) -> rusqlite::Result<Self> {
        let conn = Connection::open(db_path)?;
        enable_wal(&conn, db_path);
        conn.execute_batch(CREATE_TABLE)?;
        conn.execute_batch(UPDATE_TIMESTAMP)?;
        conn.execute_batch(CREATE_CHARACTERS_TABLE)?;
        conn.execute_batch(CREATE_PROJECT_META_TABLE)?;
        conn.execute_batch(CREATE_INDEXES)?;
        Ok(Self { conn })
    }

    /// Open the connection read-only, without running any schema DDL.
    ///
    /// Meant for cheap, side-effect-free inspection. Unlike `open()`,
    /// this never creates missing tables, so callers must tolerate a
    /// database that predates one of them.
    pub fn open_readonly(db_path: &Path) -> rusqlite::Result<Self> {
        let conn = Connection::open_with_flags(
            db_path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        Ok(Self { conn })
    }

    pub fn conn(&self) -> &Connection {
        &self.conn
    }
}

/// Let a reader and a writer work at the same time.
///
/// A project is reached by more than one process by construction (the
/// MCP server, a second window). Under the default rollback journal a
/// writer locks the whole file; WAL lets readers and one writer proceed
/// together. Written into the file header, so this converts the
/// database once and every later connection inherits it. A filesystem
/// without shared memory (a network share) refuses WAL and keeps the
/// previous mode rather than failing — logged, not fatal.
fn enable_wal(conn: &Connection, db_path: &Path) {
    let mode: rusqlite::Result<String> =
        conn.query_row("PRAGMA journal_mode=WAL", [], |row| row.get(0));
    match mode {
        Ok(mode) if mode.eq_ignore_ascii_case("wal") => {}
        Ok(mode) => eprintln!(
            "warning: could not switch {} to WAL, still in {mode}. Two processes \
             reaching this project at once may block each other.",
            db_path.display()
        ),
        Err(e) => eprintln!(
            "warning: could not query journal_mode for {}: {e}",
            db_path.display()
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn open_creates_all_tables() {
        let dir = tempfile();
        let db = Database::open(&dir).unwrap();
        let count: i64 = db
            .conn()
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' \
                 AND name IN ('translation_units', 'characters', 'project_meta')",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 3);
    }

    #[test]
    fn open_is_idempotent() {
        let dir = tempfile();
        Database::open(&dir).unwrap();
        Database::open(&dir).unwrap();
    }

    #[test]
    fn path_for_is_dot_rts_translations_db() {
        let project = Path::new("/games/my-game");
        assert_eq!(
            Database::path_for(project),
            Path::new("/games/my-game/.rts/translations.db")
        );
    }

    fn tempfile() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "rts-db-test-{nanos}-{:?}.db",
            std::thread::current().id()
        ))
    }
}
