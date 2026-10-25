//! Detects mismatches between the database and the `tl/` files before
//! export. Port of `core/export_sync.py`.
//!
//! The markers live in the project's own `project_meta` table under the
//! same two keys 1.0.0 uses, so a project saved by either version reads
//! the same in the other.

use std::path::Path;

use rusqlite::Connection;

use crate::core::storage::repositories;

pub const META_SAVED_AT: &str = "tl_saved_at";
pub const META_SAVED_MTIME: &str = "tl_saved_mtime";

/// Discrepancies found between the `tl/` files and the database.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExportSyncState {
    pub never_saved: bool,
    pub unsaved_units: i64,
    pub externally_modified: bool,
}

impl ExportSyncState {
    /// Whether the `tl/` files hold every translation kept in database.
    pub fn in_sync(&self) -> bool {
        !(self.never_saved || self.unsaved_units > 0 || self.externally_modified)
    }
}

/// The most recent modification time (seconds since the epoch) among the
/// `.rpy` files of `tl_dir`; `0.0` when it holds none.
pub fn latest_rpy_mtime(tl_dir: &Path) -> f64 {
    walkdir::WalkDir::new(tl_dir)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|e| e.file_type().is_file() && e.path().extension().is_some_and(|x| x == "rpy"))
        .filter_map(|e| e.metadata().ok()?.modified().ok())
        .filter_map(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .fold(0.0, f64::max)
}

/// Store the disk and clock state right after translations were written.
///
/// The timestamp is taken from SQLite itself, so it is formatted exactly
/// like the `updated_at` column its trigger maintains (UTC, one second
/// resolution) and both can later be compared as plain strings.
pub fn record_save(conn: &Connection, tl_dir: &Path) -> rusqlite::Result<()> {
    let saved_at: String = conn.query_row("SELECT datetime('now')", [], |row| row.get(0))?;
    repositories::set_project_meta(
        conn,
        META_SAVED_MTIME,
        &latest_rpy_mtime(tl_dir).to_string(),
    )?;
    repositories::set_project_meta(conn, META_SAVED_AT, &saved_at)
}

/// Units still missing from the `.rpy` files: those edited since the last
/// save, or every unit carrying work when the project was never saved.
/// One count either way, since the answer the caller acts on is the same.
pub fn count_unwritten(conn: &Connection) -> rusqlite::Result<i64> {
    let saved_at = repositories::get_project_meta(conn, META_SAVED_AT)?;
    repositories::count_modified_since(conn, saved_at.as_deref())
}

/// Compare the `tl/` files on disk with the translations held in database.
///
/// The SDK fills every generated block with a copy of the source text, so
/// files never written to still export as a full archive, only in the
/// source language. All three discrepancies are therefore silent without
/// this check.
pub fn check_sync(conn: &Connection, tl_dir: &Path) -> rusqlite::Result<ExportSyncState> {
    let Some(saved_at) =
        repositories::get_project_meta(conn, META_SAVED_AT)?.filter(|s| !s.is_empty())
    else {
        return Ok(ExportSyncState {
            never_saved: true,
            unsaved_units: 0,
            externally_modified: false,
        });
    };
    let saved_mtime = repositories::get_project_meta(conn, META_SAVED_MTIME)?
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0);
    Ok(ExportSyncState {
        never_saved: false,
        unsaved_units: repositories::count_modified_since(conn, Some(&saved_at))?,
        externally_modified: latest_rpy_mtime(tl_dir) > saved_mtime,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::storage::Database;

    fn scratch(name: &str) -> std::path::PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!(
            "rts-sync-test-{name}-{nanos}-{:?}",
            std::thread::current().id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn project() -> (Database, std::path::PathBuf) {
        let dir = scratch("db");
        let db = Database::open(&dir.join("t.db")).unwrap();
        let tl = dir.join("tl");
        std::fs::create_dir_all(&tl).unwrap();
        std::fs::write(tl.join("script.rpy"), "translate french x:\n").unwrap();
        (db, tl)
    }

    fn insert(conn: &Connection, block_id: &str) {
        repositories::bulk_insert(
            conn,
            &[repositories::NewUnit {
                block_id,
                source_file: "script.rpy",
                source_line: 1,
                character_variable: None,
                source_text: "Hello.",
            }],
        )
        .unwrap();
    }

    #[test]
    fn a_project_never_saved_is_out_of_sync() {
        let (db, tl) = project();
        let state = check_sync(db.conn(), &tl).unwrap();
        assert!(state.never_saved);
        assert!(!state.in_sync());
    }

    #[test]
    fn a_fresh_save_is_in_sync() {
        let (db, tl) = project();
        insert(db.conn(), "a");
        record_save(db.conn(), &tl).unwrap();
        let state = check_sync(db.conn(), &tl).unwrap();
        assert_eq!(state.unsaved_units, 0);
        assert!(!state.externally_modified);
        assert!(state.in_sync());
        assert_eq!(count_unwritten(db.conn()).unwrap(), 0);
    }

    #[test]
    fn an_edit_after_the_save_is_unsaved() {
        let (db, tl) = project();
        insert(db.conn(), "a");
        record_save(db.conn(), &tl).unwrap();
        repositories::update_translation(db.conn(), "a", "Salut.", "draft").unwrap();
        db.conn()
            .execute(
                "UPDATE translation_units SET updated_at = datetime('now', '+5 seconds')",
                [],
            )
            .unwrap();
        assert_eq!(check_sync(db.conn(), &tl).unwrap().unsaved_units, 1);
        assert_eq!(count_unwritten(db.conn()).unwrap(), 1);
    }

    #[test]
    fn a_never_saved_project_counts_every_unit_carrying_work() {
        let (db, _tl) = project();
        insert(db.conn(), "a");
        insert(db.conn(), "b");
        repositories::update_translation(db.conn(), "a", "Salut.", "draft").unwrap();
        assert_eq!(count_unwritten(db.conn()).unwrap(), 1);
    }

    #[test]
    fn a_file_touched_after_the_save_is_an_external_edit() {
        let (db, tl) = project();
        record_save(db.conn(), &tl).unwrap();
        repositories::set_project_meta(db.conn(), META_SAVED_MTIME, "1.0").unwrap();
        let state = check_sync(db.conn(), &tl).unwrap();
        assert!(state.externally_modified);
        assert!(!state.in_sync());
    }

    #[test]
    fn latest_mtime_of_an_empty_directory_is_zero() {
        assert_eq!(latest_rpy_mtime(&scratch("empty")), 0.0);
    }
}
