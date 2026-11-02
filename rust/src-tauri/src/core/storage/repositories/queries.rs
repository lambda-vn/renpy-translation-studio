//! Filtered, paginated and aggregate reads over translation units.

use rusqlite::{params, Connection};

use super::sql_placeholders;
use super::units::{unit_from_row, TranslationUnit, SELECT_COLUMNS};

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

/// The WHERE clause and bound values shared by the review queries
/// ([`get_page`], [`get_matching`], and [`count_matches_by_file`] across
/// every file when `source_file` is `None`).
///
/// The clause is empty when nothing filters; a caller passing no file
/// makes sure something else does.
fn page_filters(
    source_file: Option<&str>,
    status_filter: Option<&str>,
    search_query: &str,
    character: Option<&str>,
    needs_review: bool,
) -> (String, Vec<Box<dyn rusqlite::ToSql>>) {
    let mut conditions: Vec<String> = Vec::new();
    let mut params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();

    if let Some(file) = source_file {
        conditions.push("source_file = ?".to_string());
        params.push(Box::new(file.to_string()));
    }
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
    (conditions.join(" AND "), params)
}

/// Every unit of a file the review filters keep, unpaginated.
///
/// Exists for the one filter SQL cannot express: a quality error is
/// computed from the source and the translation, so the whole file has
/// to be handed over and sliced afterwards.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn get_matching(
    conn: &Connection,
    source_file: &str,
    status_filter: Option<&str>,
    search_query: &str,
    character: Option<&str>,
    needs_review: bool,
) -> rusqlite::Result<Vec<TranslationUnit>> {
    let (where_clause, params) = page_filters(
        Some(source_file),
        status_filter,
        search_query,
        character,
        needs_review,
    );
    let bound: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let mut stmt = conn.prepare(&format!(
        "SELECT {SELECT_COLUMNS} FROM translation_units WHERE {where_clause} \
         ORDER BY source_line"
    ))?;
    let rows = stmt.query_map(bound.as_slice(), unit_from_row)?;
    rows.collect()
}

/// The most units one page may hold, whatever the caller asks for.
pub const MAX_PAGE_SIZE: i64 = 500;

/// One page of a file's units plus the total matching row count, filtered
/// like the review screen: status, a search substring across source and
/// translation, a speaker, and the "needs another look" flag.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn get_page(
    conn: &Connection,
    query: &UnitQuery,
) -> rusqlite::Result<(Vec<TranslationUnit>, i64)> {
    let (where_clause, params) = page_filters(
        Some(query.source_file),
        query.status_filter,
        query.search_query,
        query.character,
        query.needs_review,
    );
    let bound: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();

    let total: i64 = conn.query_row(
        &format!("SELECT COUNT(*) FROM translation_units WHERE {where_clause}"),
        bound.as_slice(),
        |row| row.get(0),
    )?;

    let page_size = query.page_size.clamp(1, MAX_PAGE_SIZE);
    let mut page_params = bound;
    let offset = query.page.max(0).saturating_mul(page_size);
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
///
/// # Errors
///
/// Fails when the database cannot be read.
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

/// Units edited after a given instant. `None` counts without a lower
/// bound. A row still holding its insertion timestamp and no text was
/// never edited; a cleared translation still counts, since the source
/// text has to be written back to the `.rpy` file just like a new one.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn count_modified_since(conn: &Connection, timestamp: Option<&str>) -> rusqlite::Result<i64> {
    conn.query_row(
        "SELECT COUNT(*) FROM translation_units \
         WHERE updated_at > COALESCE(?1, '') \
           AND (translated_text != '' OR created_at != updated_at)",
        params![timestamp],
        |row| row.get(0),
    )
}

/// Per-file count of the units matching a search, a speaker and/or the
/// review flag, so the file panel can tell an absent line from one living
/// in another file. The status filter applies too: a count always matches
/// what opening that file shows.
///
/// Empty when nothing narrows the project down (no search, no speaker, no
/// flag), since the panel then has no count to show.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn count_matches_by_file(
    conn: &Connection,
    search_query: &str,
    status_filter: Option<&str>,
    character: Option<&str>,
    needs_review: bool,
) -> rusqlite::Result<std::collections::HashMap<String, i64>> {
    if search_query.trim().is_empty() && character.is_none() && !needs_review {
        return Ok(std::collections::HashMap::new());
    }
    let (where_clause, params) =
        page_filters(None, status_filter, search_query, character, needs_review);
    let bound: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let mut stmt = conn.prepare(&format!(
        "SELECT source_file, COUNT(*) FROM translation_units WHERE {where_clause} \
         GROUP BY source_file"
    ))?;
    let rows = stmt.query_map(bound.as_slice(), |row| Ok((row.get(0)?, row.get(1)?)))?;
    rows.collect()
}

/// How often a source text occurs in the project: every occurrence
/// (`total`, the displayed one included) and those outside `source_file`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DuplicateStats {
    pub total: i64,
    pub other_files: i64,
}

/// Occurrence counts for several source texts at once, restricted to the
/// texts occurring more than once. Answered for a whole page in one query
/// rather than one per displayed line.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn count_duplicates(
    conn: &Connection,
    source_texts: &[String],
    source_file: &str,
) -> rusqlite::Result<std::collections::HashMap<String, DuplicateStats>> {
    let mut unique: Vec<&String> = Vec::new();
    for text in source_texts {
        if !unique.contains(&text) {
            unique.push(text);
        }
    }
    if unique.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let placeholders = sql_placeholders(unique.len());
    let mut stmt = conn.prepare(&format!(
        "SELECT source_text, COUNT(*) AS total, \
                SUM(CASE WHEN source_file != ? THEN 1 ELSE 0 END) \
         FROM translation_units WHERE source_text IN ({placeholders}) \
         GROUP BY source_text HAVING total > 1"
    ))?;
    let mut bound: Vec<&dyn rusqlite::ToSql> = vec![&source_file];
    bound.extend(unique.iter().map(|t| *t as &dyn rusqlite::ToSql));
    let rows = stmt.query_map(bound.as_slice(), |row| {
        Ok((
            row.get::<_, String>(0)?,
            DuplicateStats {
                total: row.get(1)?,
                other_files: row.get(2)?,
            },
        ))
    })?;
    rows.collect()
}

/// The units sharing a source text and still open to a change, in file
/// order. Units already `human_validated` are left out: they carry
/// reviewed work that must not be replaced, and [`update_translations`]
/// would refuse them anyway.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn find_duplicate_block_ids(
    conn: &Connection,
    source_text: &str,
    exclude_block_id: &str,
) -> rusqlite::Result<Vec<String>> {
    let mut stmt = conn.prepare(
        "SELECT block_id FROM translation_units \
         WHERE source_text = ?1 AND block_id != ?2 AND status != 'human_validated' \
         ORDER BY source_file, source_line",
    )?;
    let rows = stmt.query_map(params![source_text, exclude_block_id], |row| row.get(0))?;
    rows.collect()
}

/// Every Ren'Py character variable speaking in the project, sorted; lines
/// with no speaker are left out.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn character_variables(conn: &Connection) -> rusqlite::Result<Vec<String>> {
    let mut stmt = conn.prepare(
        "SELECT DISTINCT character_variable FROM translation_units \
         WHERE character_variable IS NOT NULL AND character_variable != '' \
         ORDER BY character_variable",
    )?;
    let rows = stmt.query_map([], |row| row.get(0))?;
    rows.collect()
}

/// Every unit holding a translation, whatever its status, in file order.
/// Asked for by the checks that weigh a translation against its source
/// and have nothing to say about a line with no translation at all.
///
/// # Errors
///
/// Fails when the database cannot be read.
pub fn get_translated(conn: &Connection) -> rusqlite::Result<Vec<TranslationUnit>> {
    let mut stmt = conn.prepare(&format!(
        "SELECT {SELECT_COLUMNS} FROM translation_units WHERE translated_text != '' \
         ORDER BY source_file, source_line"
    ))?;
    let rows = stmt.query_map([], unit_from_row)?;
    rows.collect()
}

/// Row count per status, e.g. `{"not_translated": 500, "human_validated": 12}`.
///
/// # Errors
///
/// Fails when the database cannot be read.
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

/// Line and word counts of the whole project, validated ones apart.
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
///
/// # Errors
///
/// Fails when the database cannot be read.
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

/// One source file with its unit counts per status.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct FileStats {
    pub source_file: String,
    pub total: i64,
    /// Units in `human_validated`.
    pub validated: i64,
    pub ai_suggested: i64,
    pub draft: i64,
    pub imported: i64,
}

/// All distinct source files with their block and status counts, sorted
/// by `source_file`.
///
/// # Errors
///
/// Fails when the database cannot be read.
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

/// What [`get_page`] asks for: a file, a page of it and the review
/// filters. `page_size` is clamped to `1..=MAX_PAGE_SIZE` and a negative
/// `page` reads as the first.
#[derive(Debug, Clone, Copy)]
pub struct UnitQuery<'a> {
    pub source_file: &'a str,
    pub page: i64,
    pub page_size: i64,
    pub status_filter: Option<&'a str>,
    pub search_query: &'a str,
    pub character: Option<&'a str>,
    pub needs_review: bool,
}

#[cfg(test)]
mod tests {
    use super::super::test_support::{open_temp, seed};
    use super::super::units::{
        bulk_insert, set_needs_review, update_translation, NewUnit, Status, STATUS_HUMAN_VALIDATED,
        STATUS_NOT_TRANSLATED,
    };
    use super::*;

    fn insert_units(conn: &Connection, rows: &[(&str, &str, i64, Option<&str>, &str)]) {
        let units: Vec<NewUnit> = rows
            .iter()
            .map(
                |(block_id, source_file, source_line, speaker, text)| NewUnit {
                    block_id,
                    source_file,
                    source_line: *source_line,
                    character_variable: *speaker,
                    source_text: text,
                },
            )
            .collect();
        bulk_insert(conn, &units).unwrap();
    }

    #[test]
    fn project_progress_counts_lines_and_words() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", Status::HumanValidated).unwrap();

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

        let (page, total) = get_page(
            db.conn(),
            &UnitQuery {
                source_file: "script.rpy",
                page: 0,
                page_size: 2,
                status_filter: None,
                search_query: "",
                character: None,
                needs_review: false,
            },
        )
        .unwrap();
        assert_eq!(total, 3);
        assert_eq!(page.len(), 2);
        assert_eq!(page[0].block_id, "a");

        let (page, total) = get_page(
            db.conn(),
            &UnitQuery {
                source_file: "script.rpy",
                page: 1,
                page_size: 2,
                status_filter: None,
                search_query: "",
                character: None,
                needs_review: false,
            },
        )
        .unwrap();
        assert_eq!(total, 3);
        assert_eq!(page.len(), 1);
        assert_eq!(page[0].block_id, "c");

        let (page, total) = get_page(
            db.conn(),
            &UnitQuery {
                source_file: "script.rpy",
                page: 0,
                page_size: 50,
                status_filter: None,
                search_query: "",
                character: Some("e"),
                needs_review: false,
            },
        )
        .unwrap();
        assert_eq!(total, 2);
        assert!(page
            .iter()
            .all(|u| u.character_variable.as_deref() == Some("e")));

        let (page, total) = get_page(
            db.conn(),
            &UnitQuery {
                source_file: "script.rpy",
                page: 0,
                page_size: 50,
                status_filter: None,
                search_query: "farewell",
                character: None,
                needs_review: false,
            },
        )
        .unwrap();
        assert_eq!(total, 1);
        assert_eq!(page[0].block_id, "c");
    }

    #[test]
    fn get_page_bounds_its_size_and_offset() {
        let db = open_temp();
        seed(db.conn());

        let (page, total) = get_page(
            db.conn(),
            &UnitQuery {
                source_file: "script.rpy",
                page: 0,
                page_size: -1,
                status_filter: None,
                search_query: "",
                character: None,
                needs_review: false,
            },
        )
        .unwrap();
        assert_eq!(total, 2);
        assert_eq!(page.len(), 1);

        let (page, _) = get_page(
            db.conn(),
            &UnitQuery {
                source_file: "script.rpy",
                page: i64::MAX,
                page_size: i64::MAX,
                status_filter: None,
                search_query: "",
                character: None,
                needs_review: false,
            },
        )
        .unwrap();
        assert!(page.is_empty());
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

        let (page, total) = get_page(
            db.conn(),
            &UnitQuery {
                source_file: "script.rpy",
                page: 0,
                page_size: 50,
                status_filter: None,
                search_query: "100%",
                character: None,
                needs_review: false,
            },
        )
        .unwrap();
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
    fn count_by_status_groups_rows() {
        let db = open_temp();
        seed(db.conn());
        update_translation(db.conn(), "a", "Bonjour.", Status::HumanValidated).unwrap();

        let counts = count_by_status(db.conn()).unwrap();
        assert_eq!(counts.get(STATUS_HUMAN_VALIDATED), Some(&1));
        assert_eq!(counts.get(STATUS_NOT_TRANSLATED), Some(&1));
    }

    #[test]
    fn match_counts_follow_search_speaker_flag_and_status() {
        let db = open_temp();
        let conn = db.conn();
        insert_units(
            conn,
            &[
                ("a", "f1.rpy", 1, Some("e"), "100% sure"),
                ("b", "f1.rpy", 2, Some("m"), "1000 sure"),
                ("c", "f2.rpy", 1, Some("e"), "100% maybe"),
            ],
        );
        assert!(count_matches_by_file(conn, "  ", None, None, false)
            .unwrap()
            .is_empty());

        let by_search = count_matches_by_file(conn, "100%", None, None, false).unwrap();
        assert_eq!(by_search.get("f1.rpy"), Some(&1));
        assert_eq!(by_search.get("f2.rpy"), Some(&1));

        let by_speaker = count_matches_by_file(conn, "", None, Some("e"), false).unwrap();
        assert_eq!(by_speaker.len(), 2);

        update_translation(conn, "a", "Oui", Status::Draft).unwrap();
        let by_status = count_matches_by_file(conn, "", Some("draft"), Some("e"), false).unwrap();
        assert_eq!(by_status.len(), 1);
        assert_eq!(by_status.get("f1.rpy"), Some(&1));

        set_needs_review(conn, "c", true).unwrap();
        let flagged = count_matches_by_file(conn, "", None, None, true).unwrap();
        assert_eq!(flagged.get("f2.rpy"), Some(&1));
    }

    #[test]
    fn duplicates_are_counted_per_text_with_other_files_split_out() {
        let db = open_temp();
        let conn = db.conn();
        insert_units(
            conn,
            &[
                ("a", "f1.rpy", 1, None, "Yes."),
                ("b", "f1.rpy", 2, None, "Yes."),
                ("c", "f2.rpy", 1, None, "Yes."),
                ("d", "f2.rpy", 2, None, "Unique."),
            ],
        );
        let texts = vec![
            "Yes.".to_string(),
            "Unique.".to_string(),
            "Yes.".to_string(),
        ];
        let found = count_duplicates(conn, &texts, "f1.rpy").unwrap();
        assert_eq!(found.len(), 1);
        assert_eq!(
            found["Yes."],
            DuplicateStats {
                total: 3,
                other_files: 1
            }
        );
        assert!(count_duplicates(conn, &[], "f1.rpy").unwrap().is_empty());
    }

    #[test]
    fn speakers_are_distinct_sorted_and_skip_narration() {
        let db = open_temp();
        let conn = db.conn();
        insert_units(
            conn,
            &[
                ("a", "f.rpy", 1, Some("m"), "One."),
                ("b", "f.rpy", 2, Some("e"), "Two."),
                ("c", "f.rpy", 3, Some("m"), "Three."),
                ("d", "f.rpy", 4, None, "Four."),
            ],
        );
        assert_eq!(character_variables(conn).unwrap(), vec!["e", "m"]);
    }

    #[test]
    fn translated_units_exclude_empty_text_whatever_the_status() {
        let db = open_temp();
        let conn = db.conn();
        seed(conn);
        update_translation(conn, "b", "Au revoir.", Status::Imported).unwrap();
        let translated = get_translated(conn).unwrap();
        assert_eq!(translated.len(), 1);
        assert_eq!(translated[0].block_id, "b");
    }

    #[test]
    fn matching_returns_the_whole_file_unpaginated() {
        let db = open_temp();
        let conn = db.conn();
        seed(conn);
        let all = get_matching(conn, "script.rpy", None, "", None, false).unwrap();
        assert_eq!(all.len(), 2);
        let speaker = get_matching(conn, "script.rpy", None, "", Some("e"), false).unwrap();
        assert_eq!(speaker.len(), 1);
    }
}
