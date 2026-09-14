//! Read-only access to a project's translations.db.
//!
//! Proves the alpha.1 spike's one real question: can a Rust binary open
//! a `.rts/translations.db` written by the 1.0.0 Python application and
//! read it back correctly, on the schema frozen in CLAUDE.md's
//! compatibility policy. Nothing here writes to the database yet.

use rusqlite::Connection;
use serde::Serialize;

#[derive(Serialize)]
pub struct TranslationUnit {
    block_id: String,
    source_file: String,
    source_line: i64,
    source_text: String,
    translated_text: String,
    status: String,
}

#[derive(Serialize)]
pub struct ProjectSummary {
    total: i64,
    human_validated: i64,
    units: Vec<TranslationUnit>,
}

#[tauri::command]
pub fn open_project(db_path: String, limit: i64) -> Result<ProjectSummary, String> {
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let total: i64 = conn
        .query_row("SELECT COUNT(*) FROM translation_units", [], |row| {
            row.get(0)
        })
        .map_err(|e| e.to_string())?;

    let human_validated: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM translation_units WHERE status = 'human_validated'",
            [],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())?;

    let mut stmt = conn
        .prepare(
            "SELECT block_id, source_file, source_line, source_text, translated_text, status
             FROM translation_units
             ORDER BY source_file, source_line
             LIMIT ?1",
        )
        .map_err(|e| e.to_string())?;

    let units = stmt
        .query_map([limit], |row| {
            Ok(TranslationUnit {
                block_id: row.get(0)?,
                source_file: row.get(1)?,
                source_line: row.get(2)?,
                source_text: row.get(3)?,
                translated_text: row.get(4)?,
                status: row.get(5)?,
            })
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;

    Ok(ProjectSummary {
        total,
        human_validated,
        units,
    })
}
