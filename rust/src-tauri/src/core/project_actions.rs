//! Project-wide actions orchestrating a repository and another core
//! module. Port of `core/project_actions.py`: `fill_from_memory` and
//! `detect_and_store_characters`.

use std::path::Path;

use rusqlite::Connection;

use crate::core::renpy::character_detector;
use crate::core::storage::{recent_projects, repositories, translation_memory, Database};

/// Fill untranslated lines with what the translation memory holds.
///
/// Only `not_translated` units are touched, so nothing reviewed can be
/// overwritten and the action needs no confirmation. The text comes from
/// another project and nobody has read it in this one, which is exactly
/// what the `imported` status means. The whole project is filled, never
/// a single file: the memory answers for a language pair, not for a file.
///
/// Returns the number of lines actually filled. A memory that cannot be
/// opened or read answers nothing rather than failing, as in Python — it
/// is a convenience shared by every project.
pub fn fill_from_memory(
    conn: &Connection,
    memory_path: &Path,
    source_language: &str,
    target_language: &str,
) -> rusqlite::Result<usize> {
    let units = repositories::get_all(conn, Some(repositories::STATUS_NOT_TRANSLATED), None)?;
    let texts: Vec<String> = units.iter().map(|u| u.source_text.clone()).collect();
    let hits = translation_memory::open(memory_path)
        .and_then(|memory| {
            translation_memory::lookup(&memory, &texts, source_language, target_language)
        })
        .unwrap_or_default();

    let entries: Vec<(String, String, String)> = units
        .iter()
        .filter_map(|u| {
            hits.get(&u.source_text)
                .map(|t| (u.block_id.clone(), t.clone(), "imported".to_string()))
        })
        .collect();
    repositories::update_translations(conn, &entries)
}

/// Scan the project for `Character()` definitions and save them.
///
/// The scan is heuristic and the write is an upsert that overwrites the
/// display name, so one edited by hand goes back to whatever the scan reads
/// in the source. Notes survive, being the part no scan produces.
///
/// Returns the number of characters the scan found, whether or not each
/// was already stored.
pub fn detect_and_store_characters(conn: &Connection, project: &Path) -> rusqlite::Result<usize> {
    let detected = character_detector::detect(project);
    for character in &detected {
        repositories::upsert_character(conn, &character.variable, &character.display_name)?;
    }
    Ok(detected.len())
}

/// What a recent-projects card shows about a game, read from its own
/// database (the registry stores paths only).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResumeInfo {
    pub source_language: String,
    pub target_language: String,
    pub total: i64,
    pub validated: i64,
    pub ai_suggested: i64,
    pub imported: i64,
}

/// Read what is needed to decide whether a project can be resumed.
///
/// Resumable means the database exists and holds at least one unit, the
/// target language is recorded, and `game/tl/<language>` is still on disk
/// (it is needed to save and export without running the engine again).
/// Read-only, so listing the registry never creates a table. The 1.0.0
/// fallback that infers the language from the `tl/` folder for databases
/// predating the metadata table is not ported: such a project reads as
/// not resumable here.
pub fn read_resume_info(project: &Path) -> Option<ResumeInfo> {
    let db_path = Database::path_for(project);
    if !db_path.is_file() {
        return None;
    }
    let db = Database::open_readonly(&db_path).ok()?;
    let conn = db.conn();
    let counts = repositories::count_by_status(conn).ok()?;
    let total: i64 = counts.values().sum();
    if total == 0 {
        return None;
    }
    let target_language = repositories::get_project_meta(conn, "target_language")
        .ok()
        .flatten()
        .filter(|l| !l.is_empty())?;
    if !project
        .join("game")
        .join("tl")
        .join(&target_language)
        .is_dir()
    {
        return None;
    }
    let source_language = repositories::get_project_meta(conn, "source_language")
        .ok()
        .flatten()
        .filter(|l| !l.is_empty())
        .unwrap_or_else(|| "english".to_string());
    let count = |status: &str| counts.get(status).copied().unwrap_or(0);
    Some(ResumeInfo {
        source_language,
        target_language,
        total,
        validated: count("human_validated"),
        ai_suggested: count("ai_suggested"),
        imported: count("imported"),
    })
}

/// Delete a project's `.rts/` folder (translations, backups, live file)
/// and drop it from the registry. The game's own files are not touched.
/// A missing `.rts/` is not an error; the registry entry goes either way.
///
/// This is what the 1.0.0 cross on a recent-project card does, after a
/// confirmation. The caller closes the project first when it is open.
pub fn delete_project_data(registry: &Path, project: &Path) -> std::io::Result<()> {
    match std::fs::remove_dir_all(project.join(".rts")) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e),
    }
    recent_projects::remove(registry, project);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::storage::database::Database;
    use crate::core::storage::repositories::NewUnit;

    fn temp(name: &str) -> std::path::PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "rts-actions-{name}-{nanos}-{:?}.db",
            std::thread::current().id()
        ))
    }

    fn scratch_project(name: &str) -> std::path::PathBuf {
        let dir = temp(name).with_extension("");
        std::fs::create_dir_all(dir.join(".rts")).unwrap();
        dir
    }

    #[test]
    fn resume_info_needs_units_a_language_and_the_tl_folder() {
        let project = scratch_project("resume");
        assert!(read_resume_info(&project).is_none());

        let db = Database::open(&Database::path_for(&project)).unwrap();
        assert!(read_resume_info(&project).is_none());

        repositories::bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "a",
                source_file: "s.rpy",
                source_line: 1,
                character_variable: None,
                source_text: "Hello.",
            }],
        )
        .unwrap();
        repositories::update_translation(db.conn(), "a", "Salut.", "human_validated").unwrap();
        assert!(read_resume_info(&project).is_none());

        repositories::set_project_meta(db.conn(), "target_language", "french").unwrap();
        assert!(read_resume_info(&project).is_none());

        std::fs::create_dir_all(project.join("game").join("tl").join("french")).unwrap();
        let info = read_resume_info(&project).unwrap();
        assert_eq!(
            (info.target_language.as_str(), info.source_language.as_str()),
            ("french", "english")
        );
        assert_eq!((info.total, info.validated), (1, 1));
    }

    #[test]
    fn deleting_project_data_keeps_the_game_and_forgets_the_entry() {
        let project = scratch_project("delete");
        std::fs::create_dir_all(project.join("game")).unwrap();
        std::fs::write(project.join("game").join("script.rpy"), "label start:\n").unwrap();
        let registry = temp("registry").with_extension("json");
        recent_projects::add(&registry, &project);

        delete_project_data(&registry, &project).unwrap();

        assert!(!project.join(".rts").exists());
        assert!(project.join("game").join("script.rpy").is_file());
        assert!(recent_projects::all(&registry).is_empty());
        delete_project_data(&registry, &project).unwrap();
    }

    #[test]
    fn fills_only_not_translated_units_as_imported() {
        let db = Database::open(&temp("project")).unwrap();
        repositories::bulk_insert(
            db.conn(),
            &[
                NewUnit {
                    block_id: "a",
                    source_file: "s.rpy",
                    source_line: 1,
                    character_variable: None,
                    source_text: "Hello.",
                },
                NewUnit {
                    block_id: "b",
                    source_file: "s.rpy",
                    source_line: 2,
                    character_variable: None,
                    source_text: "Bye.",
                },
            ],
        )
        .unwrap();
        repositories::update_translation(db.conn(), "b", "Au revoir.", "human_validated").unwrap();

        let memory_path = temp("memory");
        let memory = translation_memory::open(&memory_path).unwrap();
        translation_memory::remember(
            &memory,
            &[
                ("Hello.".into(), "Bonjour.".into()),
                ("Bye.".into(), "Salut.".into()),
            ],
            "english",
            "french",
        )
        .unwrap();

        let filled = fill_from_memory(db.conn(), &memory_path, "english", "french").unwrap();
        assert_eq!(filled, 1);
        let units = repositories::get_all(db.conn(), None, None).unwrap();
        let a = units.iter().find(|u| u.block_id == "a").unwrap();
        let b = units.iter().find(|u| u.block_id == "b").unwrap();
        assert_eq!(
            (a.translated_text.as_str(), a.status.as_str()),
            ("Bonjour.", "imported")
        );
        assert_eq!(b.translated_text, "Au revoir.");
    }
}
