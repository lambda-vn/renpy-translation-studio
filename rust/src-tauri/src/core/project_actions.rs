//! Project-wide actions orchestrating a repository and another core
//! module. Port of `core/project_actions.py`'s `fill_from_memory` —
//! `detect_and_store_characters` needs `character_detector`, still not
//! ported.

use std::path::Path;

use rusqlite::Connection;

use crate::core::storage::{repositories, translation_memory};

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
