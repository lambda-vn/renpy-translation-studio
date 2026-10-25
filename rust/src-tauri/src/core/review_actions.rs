//! What the review screen does to units, kept out of the Tauri commands so
//! the MCP server and the tests reach the same code. Port of the logic
//! that lives inside `app/views/review_view.py` in 1.0.0: bulk clear
//! scopes, the filters (including the quality-error one), validation with
//! propagation to duplicates, and the maps the save action writes.

use std::collections::{HashMap, HashSet};

use rusqlite::Connection;

use crate::core::storage::repositories::{self, TranslationUnit};
use crate::core::translation::providers::base::TranslateBatchResult;
use crate::core::translation::quality::{self, QualityIssue, LENGTH_WARNING_KIND};

/// The statuses a bulk clear is allowed to reset, by the name the clear
/// dialog gives them. `unvalidated` is everything a person has not signed
/// off on; `None` (or `all`) also reaches validated lines.
///
/// Returns `Ok(None)` for "any translated line", an error for a name
/// 1.0.0 does not have.
pub fn clear_statuses(scope: Option<&str>) -> Result<Option<Vec<String>>, String> {
    match scope {
        None | Some("") | Some("all") => Ok(None),
        Some("unvalidated") => Ok(Some(
            ["ai_suggested", "draft", "imported"]
                .map(String::from)
                .to_vec(),
        )),
        Some("ai_suggested") => Ok(Some(vec!["ai_suggested".to_string()])),
        Some(other) => Err(format!("Unknown clear scope: {other}")),
    }
}

/// The filters of the review list. `errors_only` selects the translated
/// lines a quality check refuses, whatever their status; it is not a
/// status because a quality error weighs the source against the
/// translation, which no query can do.
#[derive(Debug, Clone, Default)]
pub struct UnitFilter {
    pub status: Option<String>,
    pub search: String,
    pub speaker: Option<String>,
    pub needs_review: bool,
    pub errors_only: bool,
}

/// Every line of a file the filter keeps, in file order.
pub fn filtered_units(
    conn: &Connection,
    source_file: &str,
    filter: &UnitFilter,
) -> rusqlite::Result<Vec<TranslationUnit>> {
    let matching = repositories::get_matching(
        conn,
        source_file,
        filter.status.as_deref(),
        &filter.search,
        filter.speaker.as_deref(),
        filter.needs_review,
    )?;
    if !filter.errors_only {
        return Ok(matching);
    }
    Ok(matching
        .into_iter()
        .filter(|u| {
            !u.translated_text.is_empty()
                && quality::has_blocking_issue(&u.source_text, &u.translated_text)
        })
        .collect())
}

/// One page of the filtered lines plus the total that match.
///
/// Plain filters page in SQL. The error filter reads the whole open file
/// and slices it here, the one filter that costs a full quality pass of
/// the file per call; only translated lines are checked.
pub fn page_of_units(
    conn: &Connection,
    source_file: &str,
    filter: &UnitFilter,
    page: i64,
    page_size: i64,
) -> rusqlite::Result<(Vec<TranslationUnit>, i64)> {
    if !filter.errors_only {
        return repositories::get_page(
            conn,
            source_file,
            page,
            page_size,
            filter.status.as_deref(),
            &filter.search,
            filter.speaker.as_deref(),
            filter.needs_review,
        );
    }
    let matching = filtered_units(conn, source_file, filter)?;
    let total = matching.len() as i64;
    let start = (page.max(0) * page_size.max(0)) as usize;
    let slice = matching
        .into_iter()
        .skip(start)
        .take(page_size.max(0) as usize)
        .collect();
    Ok((slice, total))
}

/// Outcome of validating one line.
#[derive(Debug, Clone)]
pub struct Validation {
    /// Quality problems that refuse the validation; nothing was written.
    pub blocking: Vec<QualityIssue>,
    /// The length suspicion, advisory only.
    pub warnings: Vec<QualityIssue>,
    /// The text as stored (trimmed), when it was written.
    pub stored: Option<String>,
}

/// Validate a line: refuse on a blocking quality issue, otherwise write
/// `human_validated`. Rejects an empty translation with an error.
pub fn validate_translation(
    conn: &Connection,
    unit: &TranslationUnit,
    translated_text: &str,
) -> Result<Validation, String> {
    let translated = translated_text.trim();
    if translated.is_empty() {
        return Err("Empty translation.".to_string());
    }
    let (blocking, warnings): (Vec<_>, Vec<_>) = quality::check(&unit.source_text, translated)
        .into_iter()
        .partition(|i| i.kind != LENGTH_WARNING_KIND);
    if !blocking.is_empty() {
        return Ok(Validation {
            blocking,
            warnings,
            stored: None,
        });
    }
    repositories::update_translation(
        conn,
        &unit.block_id,
        translated,
        repositories::STATUS_HUMAN_VALIDATED,
    )
    .map_err(|e| e.to_string())?;
    Ok(Validation {
        blocking,
        warnings,
        stored: Some(translated.to_string()),
    })
}

/// Hand a validated translation to every other line sharing its source
/// text that is not already validated; returns the lines it reached.
///
/// The quality checks already passed on this exact source text when the
/// line was validated, so they hold for these too and are not run again.
pub fn spread_to_duplicates(
    conn: &Connection,
    source_text: &str,
    block_id: &str,
    translated: &str,
) -> rusqlite::Result<Vec<String>> {
    let block_ids = repositories::find_duplicate_block_ids(conn, source_text, block_id)?;
    let entries: Vec<(String, String, String)> = block_ids
        .iter()
        .map(|id| {
            (
                id.clone(),
                translated.to_string(),
                repositories::STATUS_HUMAN_VALIDATED.to_string(),
            )
        })
        .collect();
    repositories::update_translations(conn, &entries)?;
    Ok(block_ids)
}

/// What the save action writes into the `.rpy` files, as
/// `(dialogue: block_id -> text, strings: old text -> new text)`.
///
/// Statuses are deliberately not filtered: the SDK fills each block with a
/// copy of the source, so the line an unvalidated suggestion replaces is
/// the source language itself. A unit with no translation is written back
/// as its source text, which is exactly what the SDK had generated;
/// skipping it would leave a translation the user just cleared alive in
/// the file. For `strings:` blocks a translation wins over a cleared unit
/// sharing the same source text.
pub fn save_maps(units: &[TranslationUnit]) -> (HashMap<String, String>, HashMap<String, String>) {
    let mut dialogue = HashMap::new();
    let mut old_to_new: HashMap<String, String> = HashMap::new();
    for unit in units {
        if unit.block_id.starts_with("strings_") {
            old_to_new.insert(unit.source_text.clone(), unit.source_text.clone());
        } else {
            let text = if unit.translated_text.is_empty() {
                &unit.source_text
            } else {
                &unit.translated_text
            };
            dialogue.insert(unit.block_id.clone(), text.clone());
        }
    }
    for unit in units {
        if unit.block_id.starts_with("strings_") && !unit.translated_text.is_empty() {
            old_to_new.insert(unit.source_text.clone(), unit.translated_text.clone());
        }
    }
    (dialogue, old_to_new)
}

/// The writes a translated chunk becomes: `ai_suggested`, except for lines
/// whose source has nothing to translate, which the job copied verbatim
/// and which are `human_validated` since there is nothing to review.
pub fn chunk_entries(
    result: &TranslateBatchResult,
    symbol_only: &HashSet<String>,
) -> Vec<(String, String, String)> {
    result
        .translations
        .iter()
        .map(|t| {
            let status = if symbol_only.contains(&t.block_id) {
                repositories::STATUS_HUMAN_VALIDATED
            } else {
                "ai_suggested"
            };
            (
                t.block_id.clone(),
                t.translated_text.clone(),
                status.to_string(),
            )
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::storage::repositories::NewUnit;
    use crate::core::storage::Database;
    use crate::core::translation::providers::base::TranslatedUnit;

    fn open_temp() -> Database {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "rts-review-actions-test-{nanos}-{:?}.db",
            std::thread::current().id()
        ));
        Database::open(&path).unwrap()
    }

    fn unit(
        block_id: &'static str,
        file: &'static str,
        line: i64,
        text: &'static str,
    ) -> NewUnit<'static> {
        NewUnit {
            block_id,
            source_file: file,
            source_line: line,
            character_variable: None,
            source_text: text,
        }
    }

    fn get(conn: &Connection, block_id: &str) -> TranslationUnit {
        repositories::get_many(conn, &[block_id.to_string()])
            .unwrap()
            .remove(0)
    }

    #[test]
    fn clear_scopes_match_the_dialog() {
        assert_eq!(clear_statuses(None).unwrap(), None);
        assert_eq!(clear_statuses(Some("all")).unwrap(), None);
        assert_eq!(
            clear_statuses(Some("unvalidated")).unwrap().unwrap(),
            vec!["ai_suggested", "draft", "imported"]
        );
        assert_eq!(
            clear_statuses(Some("ai_suggested")).unwrap().unwrap(),
            vec!["ai_suggested"]
        );
        assert!(clear_statuses(Some("nonsense")).is_err());
    }

    #[test]
    fn clearing_unvalidated_spares_validated_and_keeps_flag_and_note() {
        let db = open_temp();
        let conn = db.conn();
        repositories::bulk_insert(
            conn,
            &[
                unit("a", "f1.rpy", 1, "One."),
                unit("b", "f1.rpy", 2, "Two."),
                unit("c", "f2.rpy", 1, "Three."),
            ],
        )
        .unwrap();
        repositories::update_translation(conn, "a", "Un.", "human_validated").unwrap();
        repositories::update_translation(conn, "b", "Deux.", "ai_suggested").unwrap();
        repositories::update_translation(conn, "c", "Trois.", "draft").unwrap();
        repositories::set_note(conn, "b", "check").unwrap();

        let statuses = clear_statuses(Some("unvalidated")).unwrap();
        let cleared = repositories::clear_translations(conn, None, statuses.as_deref()).unwrap();
        assert_eq!(cleared, 2);
        assert_eq!(get(conn, "a").status, "human_validated");
        let b = get(conn, "b");
        assert_eq!(
            (b.status.as_str(), b.translated_text.as_str()),
            ("not_translated", "")
        );
        assert!(b.needs_review);
        assert_eq!(b.note.as_deref(), Some("check"));
    }

    #[test]
    fn clearing_everything_in_one_file_reaches_validated_lines() {
        let db = open_temp();
        let conn = db.conn();
        repositories::bulk_insert(
            conn,
            &[
                unit("a", "f1.rpy", 1, "One."),
                unit("c", "f2.rpy", 1, "Three."),
            ],
        )
        .unwrap();
        repositories::update_translation(conn, "a", "Un.", "human_validated").unwrap();
        repositories::update_translation(conn, "c", "Trois.", "human_validated").unwrap();

        let cleared = repositories::clear_translations(conn, Some("f1.rpy"), None).unwrap();
        assert_eq!(cleared, 1);
        assert_eq!(get(conn, "a").status, "not_translated");
        assert_eq!(get(conn, "c").status, "human_validated");
    }

    #[test]
    fn error_filter_keeps_translated_lines_a_check_refuses() {
        let db = open_temp();
        let conn = db.conn();
        repositories::bulk_insert(
            conn,
            &[
                unit("ok", "f.rpy", 1, "Hello {i}you{/i}."),
                unit("bad", "f.rpy", 2, "Hello {i}you{/i}."),
                unit("none", "f.rpy", 3, "Hello {i}you{/i}."),
            ],
        )
        .unwrap();
        repositories::update_translation(conn, "ok", "Salut {i}toi{/i}.", "draft").unwrap();
        repositories::update_translation(conn, "bad", "Salut toi.", "draft").unwrap();

        let filter = UnitFilter {
            errors_only: true,
            ..Default::default()
        };
        let (page, total) = page_of_units(conn, "f.rpy", &filter, 0, 10).unwrap();
        assert_eq!(total, 1);
        assert_eq!(page[0].block_id, "bad");

        let (page, total) = page_of_units(conn, "f.rpy", &filter, 1, 1).unwrap();
        assert_eq!((page.len(), total), (0, 1));
    }

    #[test]
    fn plain_filters_page_in_sql() {
        let db = open_temp();
        let conn = db.conn();
        repositories::bulk_insert(
            conn,
            &[
                unit("a", "f.rpy", 1, "100% sure."),
                unit("b", "f.rpy", 2, "1000 sure."),
            ],
        )
        .unwrap();
        let filter = UnitFilter {
            search: "100%".into(),
            ..Default::default()
        };
        let (page, total) = page_of_units(conn, "f.rpy", &filter, 0, 10).unwrap();
        assert_eq!((page.len(), total), (1, 1));
    }

    #[test]
    fn validating_refuses_a_blocking_issue_and_empty_text() {
        let db = open_temp();
        let conn = db.conn();
        repositories::bulk_insert(conn, &[unit("a", "f.rpy", 1, "Hi [name].")]).unwrap();
        let u = get(conn, "a");

        let refused = validate_translation(conn, &u, "Salut.").unwrap();
        assert!(!refused.blocking.is_empty());
        assert!(refused.stored.is_none());
        assert_eq!(get(conn, "a").status, "not_translated");

        assert!(validate_translation(conn, &u, "   ").is_err());

        let accepted = validate_translation(conn, &u, " Salut [name]. ").unwrap();
        assert_eq!(accepted.stored.as_deref(), Some("Salut [name]."));
        assert_eq!(get(conn, "a").status, "human_validated");
    }

    #[test]
    fn spreading_skips_validated_duplicates_and_reports_the_reached_lines() {
        let db = open_temp();
        let conn = db.conn();
        repositories::bulk_insert(
            conn,
            &[
                unit("a", "f1.rpy", 1, "Yes."),
                unit("b", "f1.rpy", 2, "Yes."),
                unit("c", "f2.rpy", 1, "Yes."),
                unit("d", "f2.rpy", 2, "Yes."),
                unit("e", "f2.rpy", 3, "No."),
            ],
        )
        .unwrap();
        repositories::update_translation(conn, "d", "Si.", "human_validated").unwrap();
        repositories::update_translation(conn, "c", "Peut-etre.", "ai_suggested").unwrap();
        let a = get(conn, "a");
        let outcome = validate_translation(conn, &a, "Oui.").unwrap();

        let reached =
            spread_to_duplicates(conn, &a.source_text, "a", &outcome.stored.unwrap()).unwrap();
        assert_eq!(reached, vec!["b", "c"]);
        assert_eq!(get(conn, "b").translated_text, "Oui.");
        assert_eq!(get(conn, "c").status, "human_validated");
        assert_eq!(get(conn, "d").translated_text, "Si.");
        assert_eq!(get(conn, "e").status, "not_translated");
    }

    #[test]
    fn save_maps_write_the_source_back_for_cleared_units() {
        let db = open_temp();
        let conn = db.conn();
        repositories::bulk_insert(
            conn,
            &[
                unit("d1", "f.rpy", 1, "Hello."),
                unit("d2", "f.rpy", 2, "Bye."),
                unit("strings_1", "f.rpy", 3, "Yes"),
                unit("strings_2", "f.rpy", 4, "Yes"),
                unit("strings_3", "f.rpy", 5, "No"),
            ],
        )
        .unwrap();
        repositories::update_translation(conn, "d1", "Salut.", "draft").unwrap();
        repositories::update_translation(conn, "strings_2", "Oui", "draft").unwrap();
        let units = repositories::get_all(conn, None, None).unwrap();

        let (dialogue, old_to_new) = save_maps(&units);
        assert_eq!(dialogue["d1"], "Salut.");
        assert_eq!(dialogue["d2"], "Bye.");
        assert_eq!(old_to_new["Yes"], "Oui");
        assert_eq!(old_to_new["No"], "No");
    }

    #[test]
    fn symbol_only_lines_are_validated_and_the_rest_suggested() {
        let result = TranslateBatchResult {
            translations: vec![
                TranslatedUnit {
                    block_id: "dots".into(),
                    translated_text: "...".into(),
                },
                TranslatedUnit {
                    block_id: "text".into(),
                    translated_text: "Salut".into(),
                },
            ],
            ..Default::default()
        };
        let symbol_only: HashSet<String> = ["dots".to_string()].into();
        let entries = chunk_entries(&result, &symbol_only);
        assert_eq!(entries[0].2, "human_validated");
        assert_eq!(entries[1].2, "ai_suggested");
    }
}
