//! Per-project key/value metadata.

use rusqlite::{params, Connection, OptionalExtension};

/// The `project_meta` key under which the universe summary is stored.
pub const UNIVERSE_SUMMARY_KEY: &str = "universe_summary";

/// A per-project key/value pair (universe summary, etc.).
pub fn get_project_meta(conn: &Connection, key: &str) -> rusqlite::Result<Option<String>> {
    conn.query_row(
        "SELECT value FROM project_meta WHERE key = ?1",
        params![key],
        |row| row.get(0),
    )
    .optional()
}

/// Insert or replace a project metadata key/value pair.
pub fn set_project_meta(conn: &Connection, key: &str, value: &str) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT OR REPLACE INTO project_meta (key, value) VALUES (?1, ?2)",
        params![key, value],
    )?;
    Ok(())
}
