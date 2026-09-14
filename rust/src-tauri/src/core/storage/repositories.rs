//! Data access layer for translation units, characters and project
//! metadata. Port of `core/storage/repositories.py`.
//!
//! Deliberately partial for `2.0.0-alpha.2`, extended in `2.0.0-beta.1`
//! with the pagination, neighbour-window, batch-update and bulk-clear
//! queries the MCP server needs. Still not ported:
//! extraction-pipeline methods (`resync_sources`,
//! `transfer_orphan_translations`, `delete_stale`) and the
//! duplicate/search-count helpers used only by the review UI's side
//! panel — they belong with the extraction engine and a future UI
//! respectively, neither built yet.
//!
//! Python's repositories take an explicit `threading.Lock` shared across
//! callers on the same connection, working around `sqlite3.Connection`
//! not being safe to share across threads on its own. `rusqlite::
//! Connection` has the same restriction, but Rust already forces that
//! synchronization to be visible at the type level — a caller sharing a
//! connection across threads holds it behind a `Mutex`, so nothing extra
//! is threaded through every function here.

use rusqlite::{params, params_from_iter, Connection, OptionalExtension};

pub const STATUS_NOT_TRANSLATED: &str = "not_translated";
pub const STATUS_DRAFT: &str = "draft";
pub const STATUS_HUMAN_VALIDATED: &str = "human_validated";

const SELECT_COLUMNS: &str = "id, block_id, source_file, source_line, character_variable, \
     source_text, translated_text, status, needs_review, note";

#[derive(Debug, Clone, PartialEq)]
pub struct TranslationUnit {
    pub id: i64,
    pub block_id: String,
    pub source_file: String,
    pub source_line: i64,
    pub character_variable: Option<String>,
    pub source_text: String,
    pub translated_text: String,
    pub status: String,
    pub needs_review: bool,
    pub note: Option<String>,
}

fn unit_from_row(row: &rusqlite::Row) -> rusqlite::Result<TranslationUnit> {
    Ok(TranslationUnit {
        id: row.get(0)?,
        block_id: row.get(1)?,
        source_file: row.get(2)?,
        source_line: row.get(3)?,
        character_variable: row.get(4)?,
        source_text: row.get(5)?,
        translated_text: row.get(6)?,
        status: row.get(7)?,
        needs_review: row.get::<_, i64>(8)? != 0,
        note: row.get(9)?,
    })
}

pub struct NewUnit<'a> {
    pub block_id: &'a str,
    pub source_file: &'a str,
    pub source_line: i64,
    pub character_variable: Option<&'a str>,
    pub source_text: &'a str,
}

/// Insert a batch of new units, skipping existing `block_id`s.
///
/// Uses `INSERT OR IGNORE` so that re-extraction never overwrites a
/// validated or suggested translation.
pub fn bulk_insert(conn: &Connection, units: &[NewUnit]) -> rusqlite::Result<()> {
    let mut stmt = conn.prepare(
        "INSERT OR IGNORE INTO translation_units
         (block_id, source_file, source_line, character_variable, source_text)
         VALUES (?1, ?2, ?3, ?4, ?5)",
    )?;
    for unit in units {
        stmt.execute(params![
            unit.block_id,
            unit.source_file,
            unit.source_line,
            unit.character_variable,
            unit.source_text,
        ])?;
    }
    Ok(())
}

/// Units ordered by file and line, optionally filtered by status and/or
/// source file.
pub fn get_all(
    conn: &Connection,
    status_filter: Option<&str>,
    source_file: Option<&str>,
) -> rusqlite::Result<Vec<TranslationUnit>> {
    let mut query = format!("SELECT {SELECT_COLUMNS} FROM translation_units");
    let mut conditions = Vec::new();
    let mut params: Vec<&dyn rusqlite::ToSql> = Vec::new();
    if status_filter.is_some() {
        conditions.push("status = ?");
        params.push(&status_filter);
    }
    if source_file.is_some() {
        conditions.push("source_file = ?");
        params.push(&source_file);
    }
    if !conditions.is_empty() {
        query.push_str(" WHERE ");
        query.push_str(&conditions.join(" AND "));
    }
    query.push_str(" ORDER BY source_file, source_line");

    let mut stmt = conn.prepare(&query)?;
    let rows = stmt.query_map(params.as_slice(), unit_from_row)?;
    rows.collect()
}

/// The units carrying these identifiers, in no particular order. Unknown
/// ids are skipped. Answers the live-refresh channel, told exactly which
/// `block_id`s another process just wrote.
pub fn get_many(conn: &Connection, block_ids: &[String]) -> rusqlite::Result<Vec<TranslationUnit>> {
    if block_ids.is_empty() {
        return Ok(Vec::new());
    }
    let placeholders = vec!["?"; block_ids.len()].join(",");
    let query = format!(
        "SELECT {SELECT_COLUMNS} FROM translation_units WHERE block_id IN ({placeholders})"
    );
    let mut stmt = conn.prepare(&query)?;
    let rows = stmt.query_map(params_from_iter(block_ids), unit_from_row)?;
    rows.collect()
}

/// Escape `%`, `_` and the escape character itself so a substring search
/// cannot be read as a LIKE wildcard pattern.
///
/// Pairs with a `LIKE ... ESCAPE '\'` clause; used by [`get_page`] and
/// [`get_neighbours`]'s search filter.
fn like_pattern(query: &str) -> String {
    let escaped = query
        .replace('\\', "\\\\")
        .replace('%', "\\%")
        .replace('_', "\\_");
    format!("%{escaped}%")
}

/// One page of a file's units plus the total matching row count, filtered
/// like the review screen: status, a search substring across source and
/// translation, a speaker, and the "needs another look" flag.
#[allow(clippy::too_many_arguments)]
pub fn get_page(
    conn: &Connection,
    source_file: &str,
    page: i64,
    page_size: i64,
    status_filter: Option<&str>,
    search_query: &str,
    character: Option<&str>,
    needs_review: bool,
) -> rusqlite::Result<(Vec<TranslationUnit>, i64)> {
    let mut conditions = vec!["source_file = ?".to_string()];
    let mut params: Vec<Box<dyn rusqlite::ToSql>> = vec![Box::new(source_file.to_string())];

    if let Some(status) = status_filter {
        conditions.push("status = ?".to_string());
        params.push(Box::new(status.to_string()));
    }
    if let Some(speaker) = character {
        conditions.push("character_variable = ?".to_string());
        params.push(Box::new(speaker.to_string()));
    }
    if needs_review {
        conditions.push("needs_review = 1".to_string());
    }
    let search_query = search_query.trim();
    if !search_query.is_empty() {
        conditions.push(
            "(source_text LIKE ? ESCAPE '\\' OR translated_text LIKE ? ESCAPE '\\')".to_string(),
        );
        let like = like_pattern(search_query);
        params.push(Box::new(like.clone()));
        params.push(Box::new(like));
    }
    let where_clause = conditions.join(" AND ");
    let bound: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();

    let total: i64 = conn.query_row(
        &format!("SELECT COUNT(*) FROM translation_units WHERE {where_clause}"),
        bound.as_slice(),
        |row| row.get(0),
    )?;

    let mut page_params = bound;
    let offset = page.max(0) * page_size.max(0);
    let page_size_box: Box<dyn rusqlite::ToSql> = Box::new(page_size);
    let offset_box: Box<dyn rusqlite::ToSql> = Box::new(offset);
    page_params.push(page_size_box.as_ref());
    page_params.push(offset_box.as_ref());

    let mut stmt = conn.prepare(&format!(
        "SELECT {SELECT_COLUMNS} FROM translation_units WHERE {where_clause} \
         ORDER BY source_line LIMIT ? OFFSET ?"
    ))?;
    let rows = stmt.query_map(page_params.as_slice(), unit_from_row)?;
    Ok((rows.collect::<rusqlite::Result<Vec<_>>>()?, total))
}

/// The window of a file centred on one of its lines: `radius` units on
/// each side plus the line itself, in file order.
///
/// Answers what the paginated, filtered review list hides by
/// construction: the point is to show the lines around a given one,
/// whatever page or filter the caller was looking at.
pub fn get_neighbours(
    conn: &Connection,
    source_file: &str,
    source_line: i64,
    radius: i64,
) -> rusqlite::Result<Vec<TranslationUnit>> {
    let mut stmt = conn.prepare(&format!(
        "SELECT {SELECT_COLUMNS} FROM translation_units \
         WHERE source_file = ?1 AND source_line < ?2 \
         ORDER BY source_line DESC LIMIT ?3"
    ))?;
    let mut before = stmt
        .query_map(params![source_file, source_line, radius], unit_from_row)?
        .collect::<rusqlite::Result<Vec<_>>>()?;

    let mut stmt = conn.prepare(&format!(
        "SELECT {SELECT_COLUMNS} FROM translation_units \
         WHERE source_file = ?1 AND source_line = ?2 ORDER BY source_line"
    ))?;
    let here = stmt
        .query_map(params![source_file, source_line], unit_from_row)?
        .collect::<rusqlite::Result<Vec<_>>>()?;

    let mut stmt = conn.prepare(&format!(
        "SELECT {SELECT_COLUMNS} FROM translation_units \
         WHERE source_file = ?1 AND source_line > ?2 \
         ORDER BY source_line LIMIT ?3"
    ))?;
    let after = stmt
        .query_map(params![source_file, source_line, radius], unit_from_row)?
        .collect::<rusqlite::Result<Vec<_>>>()?;

    before.reverse();
    Ok(before.into_iter().chain(here).chain(after).collect())
}

/// Update translation and status for a unit.
///
/// A `human_validated` unit is never overwritten by anything else — this
/// is the one invariant CLAUDE.md calls out by name.
pub fn update_translation(
    conn: &Connection,
    block_id: &str,
    translated_text: &str,
    status: &str,
) -> rusqlite::Result<()> {
    let current: Option<String> = conn
        .query_row(
            "SELECT status FROM translation_units WHERE block_id = ?1",
            params![block_id],
            |row| row.get(0),
        )
        .optional()?;

    if current.as_deref() == Some(STATUS_HUMAN_VALIDATED) && status != STATUS_HUMAN_VALIDATED {
        return Ok(());
    }

    conn.execute(
        "UPDATE translation_units SET translated_text = ?1, status = ?2 WHERE block_id = ?3",
        params![translated_text, status, block_id],
    )?;
    Ok(())
}

/// Apply many translations in a single pass.
///
/// Carries the same protection as [`update_translation`]: a
/// `human_validated` unit is never downgraded, checked in SQL by only
/// applying the write when the row is not `human_validated` or the
/// incoming status is `human_validated` too. Exists for the MCP
/// `submit_translations` tool, which hands back a whole batch rather than
/// one unit at a time.
///
/// Returns the number of units actually updated.
pub fn update_translations(
    conn: &Connection,
    entries: &[(String, String, String)],
) -> rusqlite::Result<usize> {
    if entries.is_empty() {
        return Ok(0);
    }
    let mut stmt = conn.prepare(
        "UPDATE translation_units SET translated_text = ?1, status = ?2 \
         WHERE block_id = ?3 AND (status != 'human_validated' OR ?2 = 'human_validated')",
    )?;
    let mut updated = 0;
    for (block_id, translated_text, status) in entries {
        updated += stmt.execute(params![translated_text, status, block_id])?;
    }
    Ok(updated)
}

/// Store a unit's live text as a draft, or reset it when emptied.
///
/// Unlike [`update_translation`], this always applies regardless of the
/// current status: it exists for a human actively editing a field that
/// was previously `ai_suggested` or `human_validated`, un-validating it
/// on purpose. Non-empty text becomes `draft`; emptied text falls back
/// to `not_translated`.
///
/// Returns the resulting status.
pub fn mark_as_draft(
    conn: &Connection,
    block_id: &str,
    translated_text: &str,
) -> rusqlite::Result<&'static str> {
    let status = if translated_text.trim().is_empty() {
        STATUS_NOT_TRANSLATED
    } else {
        STATUS_DRAFT
    };
    conn.execute(
        "UPDATE translation_units SET status = ?1, translated_text = ?2 WHERE block_id = ?3",
        params![status, translated_text, block_id],
    )?;
    Ok(status)
}

/// Raise or clear the "look at this again" flag on a unit, independent
/// of its status and translation.
pub fn set_needs_review(
    conn: &Connection,
    block_id: &str,
    needs_review: bool,
) -> rusqlite::Result<()> {
    conn.execute(
        "UPDATE translation_units SET needs_review = ?1 WHERE block_id = ?2",
        params![needs_review as i64, block_id],
    )?;
    Ok(())
}

/// Store the free-form note a translator left on a unit.
///
/// A non-empty note raises the review flag — an invariant, not a
/// convenience: nothing lists notes on their own, so one sitting on an
/// unflagged line could only be found again by whoever remembered it.
pub fn set_note(conn: &Connection, block_id: &str, note: &str) -> rusqlite::Result<()> {
    let stored = if note.is_empty() { None } else { Some(note) };
    conn.execute(
        "UPDATE translation_units \
         SET note = ?1, needs_review = CASE WHEN ?2 != '' THEN 1 ELSE needs_review END \
         WHERE block_id = ?3",
        params![stored, note, block_id],
    )?;
    Ok(())
}

/// Units edited after a given instant. `None` counts without a lower
/// bound. A row still holding its insertion timestamp and no text was
/// never edited; a cleared translation still counts, since the source
/// text has to be written back to the `.rpy` file just like a new one.
pub fn count_modified_since(conn: &Connection, timestamp: Option<&str>) -> rusqlite::Result<i64> {
    conn.query_row(
        "SELECT COUNT(*) FROM translation_units \
         WHERE updated_at > COALESCE(?1, '') \
           AND (translated_text != '' OR created_at != updated_at)",
        params![timestamp],
        |row| row.get(0),
    )
}

/// Reset translations back to `not_translated`, clearing their text.
///
/// Bypasses the `human_validated` protection everything else here
/// carries: this is the one destructive bulk action in the schema,
/// gated at the MCP tool layer behind `--allow-clear` rather than here.
/// Restricting the statuses is what makes it usable after a bad AI job —
/// the point is then to drop the suggestions without touching reviewed
/// work.
///
/// Returns the number of units actually cleared.
pub fn clear_translations(
    conn: &Connection,
    source_file: Option<&str>,
    statuses: Option<&[String]>,
) -> rusqlite::Result<usize> {
    let mut conditions = vec!["status != 'not_translated'".to_string()];
    let mut params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();
    if let Some(source_file) = source_file {
        conditions.push("source_file = ?".to_string());
        params.push(Box::new(source_file.to_string()));
    }
    if let Some(statuses) = statuses {
        if statuses.is_empty() {
            return Ok(0);
        }
        let placeholders = vec!["?"; statuses.len()].join(",");
        conditions.push(format!("status IN ({placeholders})"));
        for status in statuses {
            params.push(Box::new(status.clone()));
        }
    }
    let bound: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    conn.execute(
        &format!(
            "UPDATE translation_units SET translated_text = '', status = 'not_translated' \
             WHERE {}",
            conditions.join(" AND ")
        ),
        bound.as_slice(),
    )
}

/// Row count per status, e.g. `{"not_translated": 500, "human_validated": 12}`.
pub fn count_by_status(
    conn: &Connection,
) -> rusqlite::Result<std::collections::HashMap<String, i64>> {
    let mut stmt =
        conn.prepare("SELECT status, COUNT(*) FROM translation_units GROUP BY status")?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
    })?;
    rows.collect()
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ProjectProgress {
    pub lines: i64,
    pub validated_lines: i64,
    pub words: i64,
    pub validated_words: i64,
}

/// How far the whole project is, in lines and in words.
///
/// The word count is the number of space-separated runs in the source
/// text — an estimate, not a billing-grade figure, since Ren'Py markup
/// (`{i}`, `[name]`) counts as text.
pub fn project_progress(conn: &Connection) -> rusqlite::Result<ProjectProgress> {
    const WORDS: &str = "CASE WHEN TRIM(source_text) = '' THEN 0 ELSE \
         LENGTH(TRIM(source_text)) - LENGTH(REPLACE(TRIM(source_text), ' ', '')) + 1 END";

    let words: i64 = conn.query_row(
        &format!("SELECT COALESCE(SUM({WORDS}), 0) FROM translation_units"),
        [],
        |row| row.get(0),
    )?;

    let (lines, validated_lines, validated_words) = conn.query_row(
        &format!(
            "SELECT \
                COUNT(*), \
                COALESCE(SUM(CASE WHEN status = 'human_validated' THEN 1 ELSE 0 END), 0), \
                COALESCE(SUM(CASE WHEN status = 'human_validated' THEN {WORDS} ELSE 0 END), 0) \
             FROM translation_units"
        ),
        [],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    )?;

    Ok(ProjectProgress {
        lines,
        validated_lines,
        words,
        validated_words,
    })
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct FileStats {
    pub source_file: String,
    pub total: i64,
    pub validated: i64,
    pub ai_suggested: i64,
    pub draft: i64,
    pub imported: i64,
}

/// All distinct source files with their block and status counts, sorted
/// by `source_file`.
pub fn get_files(conn: &Connection) -> rusqlite::Result<Vec<FileStats>> {
    let mut stmt = conn.prepare(
        "SELECT \
            source_file, \
            COUNT(*), \
            SUM(CASE WHEN status = 'human_validated' THEN 1 ELSE 0 END), \
            SUM(CASE WHEN status = 'ai_suggested' THEN 1 ELSE 0 END), \
            SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END), \
            SUM(CASE WHEN status = 'imported' THEN 1 ELSE 0 END) \
         FROM translation_units GROUP BY source_file ORDER BY source_file",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(FileStats {
            source_file: row.get(0)?,
            total: row.get(1)?,
            validated: row.get(2)?,
            ai_suggested: row.get(3)?,
            draft: row.get(4)?,
            imported: row.get(5)?,
        })
    })?;
    rows.collect()
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Character {
    pub id: i64,
    pub variable: String,
    pub display_name: String,
    pub notes: Option<String>,
}

/// Insert or update a character by its Ren'Py variable name.
pub fn upsert_character(
    conn: &Connection,
    variable: &str,
    display_name: &str,
) -> rusqlite::Result<()> {
    conn.execute(
        "INSERT INTO characters (variable, display_name) VALUES (?1, ?2) \
         ON CONFLICT(variable) DO UPDATE SET display_name = excluded.display_name",
        params![variable, display_name],
    )?;
    Ok(())
}

/// Update free-form notes (gender, register, remarks…) for a character.
pub fn update_character_notes(
    conn: &Connection,
    variable: &str,
    notes: &str,
) -> rusqlite::Result<()> {
    conn.execute(
        "UPDATE characters SET notes = ?1 WHERE variable = ?2",
        params![notes, variable],
    )?;
    Ok(())
}

/// All characters, ordered by display name.
pub fn get_all_characters(conn: &Connection) -> rusqlite::Result<Vec<Character>> {
    let mut stmt = conn.prepare(
        "SELECT id, variable, display_name, notes FROM characters ORDER BY display_name",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(Character {
            id: row.get(0)?,
            variable: row.get(1)?,
            display_name: row.get(2)?,
            notes: row.get(3)?,
        })
    })?;
    rows.collect()
}

/// Remove a character entry.
pub fn delete_character(conn: &Connection, variable: &str) -> rusqlite::Result<()> {
    conn.execute(
        "DELETE FROM characters WHERE variable = ?1",
        params![variable],
    )?;
    Ok(())
}

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

#[cfg(test)]
mod tests {
    use super::super::database::Database;
    use super::*;

    fn open_temp() -> Database {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "rts-repo-test-{nanos}-{:?}.db",
            std::thread::current().id()
        ));
        Database::open(&path).unwrap()
    }

    fn seed(conn: &Connection) {
        bulk_insert(
            conn,
            &[
                NewUnit {
                    block_id: "a",
                    source_file: "script.rpy",
                    source_line: 10,
                    character_variable: Some("e"),
                    source_text: "Hello.",
                },
                NewUnit {
                    block_id: "b",
                    source_file: "script.rpy",
                    source_line: 20,
                    character_variable: None,
                    source_text: "Goodbye [name].",
                },
            ],
        )
        .unwrap();
    }

    #[test]
    fn bulk_insert_skips_existing_block_ids() {
        let db = open_temp();
        seed(db.conn());
        bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "a",
                source_file: "script.rpy",
                source_line: 999,
                character_variable: None,
                source_text: "should not overwrite",
            }],
        )
        .unwrap();

        let units = get_all(db.conn(), None, None).unwrap();
        assert_eq!(units.len(), 2);
        assert_eq!(units[0].source_line, 10);
    }

    #[test]
    fn get_all_filters_by_status_and_file() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", STATUS_HUMAN_VALIDATED).unwrap();

        let validated = get_all(db.conn(), Some(STATUS_HUMAN_VALIDATED), None).unwrap();
        assert_eq!(validated.len(), 1);
        assert_eq!(validated[0].block_id, "a");

        let all_in_file = get_all(db.conn(), None, Some("script.rpy")).unwrap();
        assert_eq!(all_in_file.len(), 2);
    }

    #[test]
    fn human_validated_is_never_overwritten() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", STATUS_HUMAN_VALIDATED).unwrap();

        update_translation(db.conn(), "a", "wrong AI guess", "ai_suggested").unwrap();

        let units = get_many(db.conn(), &["a".to_string()]).unwrap();
        assert_eq!(units[0].translated_text, "Bonjour.");
        assert_eq!(units[0].status, STATUS_HUMAN_VALIDATED);
    }

    #[test]
    fn mark_as_draft_falls_back_to_not_translated_when_emptied() {
        let db = open_temp();
        seed(db.conn());

        let status = mark_as_draft(db.conn(), "a", "un texte").unwrap();
        assert_eq!(status, STATUS_DRAFT);

        let status = mark_as_draft(db.conn(), "a", "   ").unwrap();
        assert_eq!(status, STATUS_NOT_TRANSLATED);
    }

    #[test]
    fn set_note_raises_needs_review_only_when_non_empty() {
        let db = open_temp();
        seed(db.conn());

        set_note(db.conn(), "a", "check this phrasing").unwrap();
        let units = get_many(db.conn(), &["a".to_string()]).unwrap();
        assert!(units[0].needs_review);
        assert_eq!(units[0].note.as_deref(), Some("check this phrasing"));

        set_needs_review(db.conn(), "a", false).unwrap();
        set_note(db.conn(), "a", "").unwrap();
        let units = get_many(db.conn(), &["a".to_string()]).unwrap();
        assert!(!units[0].needs_review);
        assert_eq!(units[0].note, None);
    }

    #[test]
    fn project_progress_counts_lines_and_words() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", STATUS_HUMAN_VALIDATED).unwrap();

        let progress = project_progress(db.conn()).unwrap();
        assert_eq!(progress.lines, 2);
        assert_eq!(progress.validated_lines, 1);
        assert_eq!(progress.words, 1 + 2); // "Hello." + "Goodbye [name]."
        assert_eq!(progress.validated_words, 1);
    }

    #[test]
    fn get_files_groups_by_source_file() {
        let db = open_temp();
        seed(db.conn());
        bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "c",
                source_file: "other.rpy",
                source_line: 1,
                character_variable: None,
                source_text: "Hi.",
            }],
        )
        .unwrap();

        let files = get_files(db.conn()).unwrap();
        assert_eq!(files.len(), 2);
        assert_eq!(files[0].source_file, "other.rpy");
        assert_eq!(files[0].total, 1);
        assert_eq!(files[1].source_file, "script.rpy");
        assert_eq!(files[1].total, 2);
    }

    #[test]
    fn character_and_project_meta_roundtrip() {
        let db = open_temp();
        upsert_character(db.conn(), "e", "Eileen").unwrap();
        update_character_notes(db.conn(), "e", "narrator, formal register").unwrap();
        upsert_character(db.conn(), "e", "Eileen Renard").unwrap();

        let characters = get_all_characters(db.conn()).unwrap();
        assert_eq!(characters.len(), 1);
        assert_eq!(characters[0].display_name, "Eileen Renard");
        assert_eq!(
            characters[0].notes.as_deref(),
            Some("narrator, formal register")
        );

        delete_character(db.conn(), "e").unwrap();
        assert!(get_all_characters(db.conn()).unwrap().is_empty());

        assert_eq!(
            get_project_meta(db.conn(), "universe_summary").unwrap(),
            None
        );
        set_project_meta(db.conn(), "universe_summary", "A fantasy world.").unwrap();
        assert_eq!(
            get_project_meta(db.conn(), "universe_summary")
                .unwrap()
                .as_deref(),
            Some("A fantasy world.")
        );
    }

    #[test]
    fn get_page_filters_and_paginates() {
        let db = open_temp();
        seed(db.conn());
        bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "c",
                source_file: "script.rpy",
                source_line: 30,
                character_variable: Some("e"),
                source_text: "Farewell.",
            }],
        )
        .unwrap();

        let (page, total) = get_page(db.conn(), "script.rpy", 0, 2, None, "", None, false).unwrap();
        assert_eq!(total, 3);
        assert_eq!(page.len(), 2);
        assert_eq!(page[0].block_id, "a");

        let (page, total) = get_page(db.conn(), "script.rpy", 1, 2, None, "", None, false).unwrap();
        assert_eq!(total, 3);
        assert_eq!(page.len(), 1);
        assert_eq!(page[0].block_id, "c");

        let (page, total) =
            get_page(db.conn(), "script.rpy", 0, 50, None, "", Some("e"), false).unwrap();
        assert_eq!(total, 2);
        assert!(page
            .iter()
            .all(|u| u.character_variable.as_deref() == Some("e")));

        let (page, total) = get_page(
            db.conn(),
            "script.rpy",
            0,
            50,
            None,
            "farewell",
            None,
            false,
        )
        .unwrap();
        assert_eq!(total, 1);
        assert_eq!(page[0].block_id, "c");
    }

    #[test]
    fn get_page_search_escapes_like_wildcards() {
        let db = open_temp();
        bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "a",
                source_file: "script.rpy",
                source_line: 1,
                character_variable: None,
                source_text: "100% done",
            }],
        )
        .unwrap();

        let (page, total) =
            get_page(db.conn(), "script.rpy", 0, 50, None, "100%", None, false).unwrap();
        assert_eq!(total, 1);
        assert_eq!(page.len(), 1);
    }

    #[test]
    fn get_neighbours_centres_on_the_line_and_keeps_file_order() {
        let db = open_temp();
        seed(db.conn());
        bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "c",
                source_file: "script.rpy",
                source_line: 30,
                character_variable: None,
                source_text: "Farewell.",
            }],
        )
        .unwrap();

        let window = get_neighbours(db.conn(), "script.rpy", 20, 1).unwrap();
        let ids: Vec<&str> = window.iter().map(|u| u.block_id.as_str()).collect();
        assert_eq!(ids, vec!["a", "b", "c"]);
    }

    #[test]
    fn update_translations_applies_batch_and_protects_human_validated() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", STATUS_HUMAN_VALIDATED).unwrap();

        let updated = update_translations(
            db.conn(),
            &[
                (
                    "a".to_string(),
                    "wrong AI guess".to_string(),
                    "ai_suggested".to_string(),
                ),
                (
                    "b".to_string(),
                    "Au revoir.".to_string(),
                    "ai_suggested".to_string(),
                ),
            ],
        )
        .unwrap();

        assert_eq!(updated, 1);
        let units = get_many(db.conn(), &["a".to_string(), "b".to_string()]).unwrap();
        let a = units.iter().find(|u| u.block_id == "a").unwrap();
        let b = units.iter().find(|u| u.block_id == "b").unwrap();
        assert_eq!(a.translated_text, "Bonjour.");
        assert_eq!(b.translated_text, "Au revoir.");
    }

    #[test]
    fn clear_translations_respects_scope_and_statuses() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", STATUS_HUMAN_VALIDATED).unwrap();
        update_translation(db.conn(), "b", "Au revoir.", "ai_suggested").unwrap();

        let cleared =
            clear_translations(db.conn(), None, Some(&["ai_suggested".to_string()])).unwrap();
        assert_eq!(cleared, 1);

        let units = get_many(db.conn(), &["a".to_string(), "b".to_string()]).unwrap();
        let a = units.iter().find(|u| u.block_id == "a").unwrap();
        let b = units.iter().find(|u| u.block_id == "b").unwrap();
        assert_eq!(a.status, STATUS_HUMAN_VALIDATED);
        assert_eq!(b.status, STATUS_NOT_TRANSLATED);
        assert_eq!(b.translated_text, "");
    }

    #[test]
    fn count_by_status_groups_rows() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", STATUS_HUMAN_VALIDATED).unwrap();

        let counts = count_by_status(db.conn()).unwrap();
        assert_eq!(counts.get(STATUS_HUMAN_VALIDATED), Some(&1));
        assert_eq!(counts.get(STATUS_NOT_TRANSLATED), Some(&1));
    }
}
