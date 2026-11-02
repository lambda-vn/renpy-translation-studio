//! Translation units: the row type, the status vocabulary and every write to them.

use rusqlite::types::ToSqlOutput;
use rusqlite::{params, params_from_iter, Connection, ToSql};

use super::{begin, commit, sql_placeholders};

/// Where a line's translation stands, written to the `status` column.
///
/// The stored strings are part of the frozen 1.x schema: [`Status::as_str`]
/// is the only place they are spelled, so a write can no longer carry a
/// misspelled status.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    /// Nothing translated yet.
    NotTranslated,
    /// Text edited by hand but not validated.
    Draft,
    /// Came from elsewhere (bilingual file, translation memory) and was not reviewed here.
    Imported,
    /// Suggested by a provider or an MCP client.
    AiSuggested,
    /// Validated by a human; never overwritten by an automatic write.
    HumanValidated,
}

impl Status {
    /// The value stored in the database.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NotTranslated => "not_translated",
            Self::Draft => "draft",
            Self::Imported => "imported",
            Self::AiSuggested => "ai_suggested",
            Self::HumanValidated => "human_validated",
        }
    }

    /// The status a stored value names, `None` for one this version
    /// does not know.
    pub fn from_stored(value: &str) -> Option<Self> {
        [
            Self::NotTranslated,
            Self::Draft,
            Self::Imported,
            Self::AiSuggested,
            Self::HumanValidated,
        ]
        .into_iter()
        .find(|status| status.as_str() == value)
    }
}

impl ToSql for Status {
    fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
        Ok(ToSqlOutput::from(self.as_str()))
    }
}

/// Stored name of [`Status::NotTranslated`].
pub const STATUS_NOT_TRANSLATED: &str = Status::NotTranslated.as_str();
/// Stored name of [`Status::Draft`].
pub const STATUS_DRAFT: &str = Status::Draft.as_str();
/// Stored name of [`Status::HumanValidated`].
pub const STATUS_HUMAN_VALIDATED: &str = Status::HumanValidated.as_str();
/// Stored name of [`Status::Imported`].
pub const STATUS_IMPORTED: &str = Status::Imported.as_str();
/// Stored name of [`Status::AiSuggested`].
pub const STATUS_AI_SUGGESTED: &str = Status::AiSuggested.as_str();

/// Every status a line can carry, in the order the review screen lists them.
pub const ALL_STATUSES: [&str; 5] = [
    STATUS_NOT_TRANSLATED,
    STATUS_DRAFT,
    STATUS_IMPORTED,
    STATUS_AI_SUGGESTED,
    STATUS_HUMAN_VALIDATED,
];

/// The columns [`unit_from_row`] reads, in order.
pub(super) const SELECT_COLUMNS: &str =
    "id, block_id, source_file, source_line, character_variable, \
     source_text, translated_text, status, needs_review, note";

/// Most bound variables one `IN (...)` query carries, far below SQLite's
/// own limit so that a long list is split rather than refused.
const MAX_IN_PARAMS: usize = 500;

/// One row of `translation_units`.
#[derive(Debug, Clone, PartialEq)]
pub struct TranslationUnit {
    pub id: i64,
    pub block_id: String,
    /// Absolute path the file had when the game was extracted.
    pub source_file: String,
    pub source_line: i64,
    /// Ren'Py variable of the speaker, `None` for narration.
    pub character_variable: Option<String>,
    pub source_text: String,
    pub translated_text: String,
    /// One of the stored status names, see [`ALL_STATUSES`].
    pub status: String,
    pub needs_review: bool,
    pub note: Option<String>,
}

/// Read a row selected with [`SELECT_COLUMNS`].
pub(super) fn unit_from_row(row: &rusqlite::Row) -> rusqlite::Result<TranslationUnit> {
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

/// A unit freshly extracted from the game, not yet stored.
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
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn bulk_insert(conn: &Connection, units: &[NewUnit]) -> rusqlite::Result<()> {
    let tx = begin(conn)?;
    {
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
    }
    commit(tx)
}

/// Units ordered by file and line, optionally filtered by status and/or
/// source file.
///
/// # Errors
///
/// Fails when the database cannot be read.
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
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn get_many(conn: &Connection, block_ids: &[String]) -> rusqlite::Result<Vec<TranslationUnit>> {
    let mut units = Vec::with_capacity(block_ids.len());
    for slice in block_ids.chunks(MAX_IN_PARAMS) {
        let placeholders = sql_placeholders(slice.len());
        let query = format!(
            "SELECT {SELECT_COLUMNS} FROM translation_units WHERE block_id IN ({placeholders})"
        );
        let mut stmt = conn.prepare(&query)?;
        let rows = stmt.query_map(params_from_iter(slice), unit_from_row)?;
        for row in rows {
            units.push(row?);
        }
    }
    Ok(units)
}

/// Update translation and status for a unit.
///
/// A `human_validated` unit is never overwritten by anything else — this
/// is the one invariant CLAUDE.md calls out by name. The guard lives in
/// the `UPDATE` itself: a separate read would let another process (the
/// MCP server) validate the row in between.
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn update_translation(
    conn: &Connection,
    block_id: &str,
    translated_text: &str,
    status: Status,
) -> rusqlite::Result<()> {
    update_translations(
        conn,
        &[(block_id.to_string(), translated_text.to_string(), status)],
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
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn update_translations(
    conn: &Connection,
    entries: &[(String, String, Status)],
) -> rusqlite::Result<usize> {
    apply_translations(
        conn,
        entries,
        "UPDATE translation_units SET translated_text = ?1, status = ?2 \
         WHERE block_id = ?3 AND (status != 'human_validated' OR ?2 = 'human_validated')",
    )
}

/// Like [`update_translations`], but a `human_validated` unit is never
/// touched, whatever the incoming status.
///
/// [`update_translations`] lets a `human_validated` entry overwrite a row
/// already validated, which is right for a human validating a line and wrong
/// for anything propagating or filling lines on its own (duplicates, imports,
/// orphan transfers): they select their targets in a separate query, and a
/// row validated in between by another process would be replaced. Here the
/// guard lives in the `UPDATE` itself.
///
/// Returns the number of units actually updated.
///
/// # Errors
///
/// Fails when the database cannot be written.
pub fn update_translations_unvalidated(
    conn: &Connection,
    entries: &[(String, String, Status)],
) -> rusqlite::Result<usize> {
    apply_translations(
        conn,
        entries,
        "UPDATE translation_units SET translated_text = ?1, status = ?2 \
         WHERE block_id = ?3 AND status != 'human_validated'",
    )
}

fn apply_translations(
    conn: &Connection,
    entries: &[(String, String, Status)],
    update: &str,
) -> rusqlite::Result<usize> {
    if entries.is_empty() {
        return Ok(0);
    }
    let tx = begin(conn)?;
    let mut updated = 0;
    {
        let mut stmt = conn.prepare(update)?;
        for (block_id, translated_text, status) in entries {
            updated += stmt.execute(params![translated_text, status, block_id])?;
        }
    }
    commit(tx)?;
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
///
/// # Errors
///
/// Fails when the database cannot be written.
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
///
/// # Errors
///
/// Fails when the database cannot be written.
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
///
/// # Errors
///
/// Fails when the database cannot be written.
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
///
/// # Errors
///
/// Fails when the database cannot be written.
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
        let placeholders = sql_placeholders(statuses.len());
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

#[cfg(test)]
mod tests {
    use super::super::test_support::{open_temp, seed, unit};
    use super::*;

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
        update_translation(db.conn(), "a", "Bonjour.", Status::HumanValidated).unwrap();

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
        update_translation(db.conn(), "a", "Bonjour.", Status::HumanValidated).unwrap();

        update_translation(db.conn(), "a", "wrong AI guess", Status::AiSuggested).unwrap();

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
    fn update_translations_applies_batch_and_protects_human_validated() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", Status::HumanValidated).unwrap();

        let updated = update_translations(
            db.conn(),
            &[
                (
                    "a".to_string(),
                    "wrong AI guess".to_string(),
                    Status::AiSuggested,
                ),
                (
                    "b".to_string(),
                    "Au revoir.".to_string(),
                    Status::AiSuggested,
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
        update_translation(db.conn(), "a", "Bonjour.", Status::HumanValidated).unwrap();
        update_translation(db.conn(), "b", "Au revoir.", Status::AiSuggested).unwrap();

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
    fn get_many_splits_a_long_list_of_ids() {
        let db = open_temp();
        let conn = db.conn();
        let names: Vec<String> = (0..1200).map(|index| format!("id{index}")).collect();
        let units: Vec<NewUnit> = names.iter().map(|name| unit(name, "Text.")).collect();
        bulk_insert(conn, &units).unwrap();

        let mut wanted = names.clone();
        wanted.push("missing".to_string());
        let found = get_many(conn, &wanted).unwrap();

        assert_eq!(found.len(), 1200);
        assert!(get_many(conn, &[]).unwrap().is_empty());
    }

    #[test]
    fn the_strict_update_never_touches_a_validated_unit() {
        let db = open_temp();
        let conn = db.conn();
        seed(conn);
        update_translation(conn, "a", "Bonjour.", Status::HumanValidated).unwrap();
        let entries = [
            (
                "a".to_string(),
                "propagated".to_string(),
                Status::HumanValidated,
            ),
            (
                "b".to_string(),
                "propagated".to_string(),
                Status::HumanValidated,
            ),
        ];

        assert_eq!(update_translations_unvalidated(conn, &entries).unwrap(), 1);

        let units = get_many(conn, &["a".to_string(), "b".to_string()]).unwrap();
        let a = units.iter().find(|u| u.block_id == "a").unwrap();
        let b = units.iter().find(|u| u.block_id == "b").unwrap();
        assert_eq!(a.translated_text, "Bonjour.");
        assert_eq!(b.translated_text, "propagated");
        assert_eq!(update_translations(conn, &entries).unwrap(), 2);
    }

    #[test]
    fn every_stored_status_reads_back_as_itself() {
        for stored in ALL_STATUSES {
            assert_eq!(
                Status::from_stored(stored).map(Status::as_str),
                Some(stored)
            );
        }
        assert_eq!(Status::from_stored("validated"), None);
    }
}
