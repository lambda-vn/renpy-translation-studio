//! Translation memory shared by every project of this machine. Port of
//! `core/storage/translation_memory.py`, reading and writing the same
//! `<config_dir>/memory.db` the 1.0.0 application keeps: part of the
//! frozen data contract, not a fresh format.
//!
//! A source text is matched twice: on itself, and on a normalised key
//! that ignores letter case, repeated whitespace and trailing
//! punctuation. Nothing looser is served — a wrong translation costs
//! more than an empty field. The key leaves every `[interpolation]` and
//! `{tag}` untouched, so two texts whose code differs never share one,
//! which is what keeps `quality::check` from meeting a variable that
//! belongs to another source.
//!
//! Python holds one lazily-opened connection behind a lock and swallows
//! every `sqlite3.Error`; here each function takes the connection and
//! returns the `Result`, and the callers that want Python's
//! "convenience, never fatal" behaviour discard it themselves.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;
use rusqlite::{params, params_from_iter, Connection};

static CODE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\[[^\]]*\]|\{[^}]*\}").unwrap());
static SPACES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s+").unwrap());
static TRAILING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[.!?…,;:\-—– ]+$").unwrap());

const CREATE_TABLE: &str = "
CREATE TABLE IF NOT EXISTS memory (
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    source_text     TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (source_language, target_language, source_text)
);
";

const CREATE_NORMALIZED_INDEX: &str = "
CREATE INDEX IF NOT EXISTS idx_memory_normalized
    ON memory (source_language, target_language, normalized_text);
";

const MAX_LOOKUP_PARAMS: usize = 500;

/// Where the memory lives on this machine: `<config_dir>/memory.db`.
pub fn default_path() -> PathBuf {
    crate::core::settings::config_dir().join("memory.db")
}

/// The key under which near-identical source texts meet.
///
/// Letter case is folded, runs of whitespace become one space and
/// trailing punctuation goes. Interpolations and tags are copied
/// verbatim, case included. A text made only of punctuation would
/// otherwise normalise to nothing and meet every other one, so the
/// trailing trim is dropped when it empties the key.
pub fn normalized_key(text: &str) -> String {
    let mut folded = String::new();
    let mut last = 0;
    for m in CODE.find_iter(text) {
        folded.push_str(&SPACES.replace_all(&text[last..m.start()].to_lowercase(), " "));
        folded.push_str(m.as_str());
        last = m.end();
    }
    folded.push_str(&SPACES.replace_all(&text[last..].to_lowercase(), " "));
    let folded = folded.trim();
    let trimmed = TRAILING.replace(folded, "");
    if trimmed.is_empty() {
        folded.to_string()
    } else {
        trimmed.into_owned()
    }
}

/// Open the memory database, creating it on first use and adding the
/// normalised-key column to a memory that predates it.
pub fn open(path: &Path) -> rusqlite::Result<Connection> {
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let conn = Connection::open(path)?;
    conn.execute_batch(CREATE_TABLE)?;
    add_normalized_text(&conn)?;
    conn.execute_batch(CREATE_NORMALIZED_INDEX)?;
    Ok(conn)
}

/// Written once, for every row already stored: a memory filled before
/// the column existed would otherwise answer only the exact matches it
/// always did, entries being rewritten only when a translator validates
/// the same source text again.
fn add_normalized_text(conn: &Connection) -> rusqlite::Result<()> {
    let mut stmt = conn.prepare("PRAGMA table_info(memory)")?;
    let has_column = stmt
        .query_map([], |row| row.get::<_, String>(1))?
        .collect::<rusqlite::Result<Vec<_>>>()?
        .iter()
        .any(|name| name == "normalized_text");
    drop(stmt);
    if has_column {
        return Ok(());
    }
    conn.execute_batch("ALTER TABLE memory ADD COLUMN normalized_text TEXT NOT NULL DEFAULT '';")?;
    let rows: Vec<(String, String, String)> = {
        let mut stmt =
            conn.prepare("SELECT source_language, target_language, source_text FROM memory")?;
        let collected = stmt
            .query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))?
            .collect::<rusqlite::Result<_>>()?;
        collected
    };
    let mut update = conn.prepare(
        "UPDATE memory SET normalized_text = ?1 \
         WHERE source_language = ?2 AND target_language = ?3 AND source_text = ?4",
    )?;
    for (source_language, target_language, source_text) in rows {
        update.execute(params![
            normalized_key(&source_text),
            source_language,
            target_language,
            source_text
        ])?;
    }
    Ok(())
}

/// Record validated translations for a language pair. A later
/// validation of the same source text replaces the earlier one: the
/// memory holds what the translator settled on last. Pairs with an
/// empty side are skipped.
pub fn remember(
    conn: &Connection,
    entries: &[(String, String)],
    source_language: &str,
    target_language: &str,
) -> rusqlite::Result<()> {
    let mut stmt = conn.prepare(
        "INSERT INTO memory \
             (source_language, target_language, source_text, \
              normalized_text, translated_text, updated_at) \
         VALUES (?1, ?2, ?3, ?4, ?5, datetime('now')) \
         ON CONFLICT(source_language, target_language, source_text) \
         DO UPDATE SET translated_text = excluded.translated_text, \
                       normalized_text = excluded.normalized_text, \
                       updated_at = excluded.updated_at",
    )?;
    for (source, translated) in entries {
        if source.is_empty() || translated.is_empty() {
            continue;
        }
        stmt.execute(params![
            source_language,
            target_language,
            source,
            normalized_key(source),
            translated
        ])?;
    }
    Ok(())
}

/// The stored translation of each known source text.
///
/// Two passes: the text as written, then what that left over on the
/// normalised key. An exact hit is never replaced by a normalised one.
/// Queried in slices, since a whole game is asked at once and SQLite
/// caps the number of bound parameters per statement.
pub fn lookup(
    conn: &Connection,
    source_texts: &[String],
    source_language: &str,
    target_language: &str,
) -> rusqlite::Result<HashMap<String, String>> {
    let mut seen = std::collections::HashSet::new();
    let unique: Vec<&String> = source_texts
        .iter()
        .filter(|t| !t.is_empty() && seen.insert(*t))
        .collect();
    if unique.is_empty() {
        return Ok(HashMap::new());
    }

    let exact: Vec<&str> = unique.iter().map(|t| t.as_str()).collect();
    let mut found = select(
        conn,
        "source_text",
        &exact,
        source_language,
        target_language,
    )?;

    let missing: Vec<&&String> = unique.iter().filter(|t| !found.contains_key(**t)).collect();
    let mut keys: Vec<String> = Vec::new();
    let mut seen_keys = std::collections::HashSet::new();
    for text in &missing {
        let key = normalized_key(text);
        if seen_keys.insert(key.clone()) {
            keys.push(key);
        }
    }
    let key_refs: Vec<&str> = keys.iter().map(String::as_str).collect();
    let by_key = select(
        conn,
        "normalized_text",
        &key_refs,
        source_language,
        target_language,
    )?;
    for text in missing {
        if let Some(translated) = by_key.get(&normalized_key(text)) {
            found.insert((**text).clone(), translated.clone());
        }
    }
    Ok(found)
}

/// The translation stored against each value of one column. Several
/// entries can share a normalised key, so rows come in oldest first and
/// the later ones overwrite: the answer is the one the translator
/// settled on last, the source text breaking a tie between two
/// validated within the same second.
fn select(
    conn: &Connection,
    column: &str,
    values: &[&str],
    source_language: &str,
    target_language: &str,
) -> rusqlite::Result<HashMap<String, String>> {
    let mut found = HashMap::new();
    for batch in values.chunks(MAX_LOOKUP_PARAMS) {
        let placeholders = vec!["?"; batch.len()].join(",");
        let mut stmt = conn.prepare(&format!(
            "SELECT {column}, translated_text FROM memory \
             WHERE source_language = ? AND target_language = ? \
               AND {column} IN ({placeholders}) \
             ORDER BY updated_at, source_text"
        ))?;
        let bound: Vec<&str> = [source_language, target_language]
            .into_iter()
            .chain(batch.iter().copied())
            .collect();
        let rows = stmt.query_map(params_from_iter(bound), |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        for row in rows {
            let (matched, translated) = row?;
            found.insert(matched, translated);
        }
    }
    Ok(found)
}

/// How much is stored, per language pair, the largest pair first.
pub fn stats(conn: &Connection) -> rusqlite::Result<Vec<(String, String, i64)>> {
    let mut stmt = conn.prepare(
        "SELECT source_language, target_language, COUNT(*) AS n FROM memory \
         GROUP BY source_language, target_language ORDER BY n DESC",
    )?;
    let rows = stmt.query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))?;
    rows.collect()
}

/// Drop everything stored for one language pair; returns how many
/// entries went.
pub fn forget(
    conn: &Connection,
    source_language: &str,
    target_language: &str,
) -> rusqlite::Result<usize> {
    conn.execute(
        "DELETE FROM memory WHERE source_language = ?1 AND target_language = ?2",
        params![source_language, target_language],
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_path() -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "rts-memory-test-{nanos}-{:?}.db",
            std::thread::current().id()
        ))
    }

    fn pair(a: &str, b: &str) -> (String, String) {
        (a.to_string(), b.to_string())
    }

    fn texts(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn normalized_key_folds_case_spacing_and_trailing_punctuation() {
        assert_eq!(normalized_key("Riley..."), "riley");
        assert_eq!(normalized_key("Riley?!"), "riley");
        assert_eq!(normalized_key("RILEY!"), "riley");
        assert_eq!(normalized_key("  Hello   world  "), "hello world");
    }

    #[test]
    fn normalized_key_keeps_code_verbatim_so_variables_never_merge() {
        assert_eq!(normalized_key("Hello [MC]!"), "hello [MC]");
        assert_ne!(normalized_key("Hello [MC]"), normalized_key("Hello [mc]"));
        assert_eq!(normalized_key("{i}Hi{/i}."), "{i}hi{/i}");
    }

    #[test]
    fn a_text_of_pure_punctuation_does_not_collapse_to_empty() {
        assert_eq!(normalized_key("..."), "...");
        assert_ne!(normalized_key("..."), normalized_key("?!"));
    }

    #[test]
    fn remember_then_lookup_exact_and_normalized() {
        let conn = open(&temp_path()).unwrap();
        remember(
            &conn,
            &[pair("Hello.", "Bonjour."), pair("Yes", "Oui")],
            "english",
            "french",
        )
        .unwrap();

        let found = lookup(
            &conn,
            &texts(&["Hello.", "HELLO!", "Yes", "Unknown"]),
            "english",
            "french",
        )
        .unwrap();
        assert_eq!(found["Hello."], "Bonjour.");
        assert_eq!(found["HELLO!"], "Bonjour.");
        assert_eq!(found["Yes"], "Oui");
        assert!(!found.contains_key("Unknown"));
    }

    #[test]
    fn an_exact_hit_is_never_replaced_by_a_normalized_one() {
        let conn = open(&temp_path()).unwrap();
        remember(
            &conn,
            &[pair("Hello", "Salut"), pair("Hello!", "Bonjour !")],
            "english",
            "french",
        )
        .unwrap();
        let found = lookup(&conn, &texts(&["Hello"]), "english", "french").unwrap();
        assert_eq!(found["Hello"], "Salut");
    }

    #[test]
    fn language_pairs_do_not_leak_into_each_other() {
        let conn = open(&temp_path()).unwrap();
        remember(&conn, &[pair("Hello", "Bonjour")], "english", "french").unwrap();
        let found = lookup(&conn, &texts(&["Hello"]), "english", "german").unwrap();
        assert!(found.is_empty());
    }

    #[test]
    fn a_later_validation_replaces_the_earlier_one() {
        let conn = open(&temp_path()).unwrap();
        remember(&conn, &[pair("Hello", "Salut")], "english", "french").unwrap();
        remember(&conn, &[pair("Hello", "Bonjour")], "english", "french").unwrap();
        let found = lookup(&conn, &texts(&["Hello"]), "english", "french").unwrap();
        assert_eq!(found["Hello"], "Bonjour");
    }

    #[test]
    fn empty_sides_are_skipped() {
        let conn = open(&temp_path()).unwrap();
        remember(&conn, &[pair("", "x"), pair("y", "")], "english", "french").unwrap();
        assert!(stats(&conn).unwrap().is_empty());
    }

    #[test]
    fn lookup_is_sliced_past_sqlite_s_parameter_cap() {
        let conn = open(&temp_path()).unwrap();
        let entries: Vec<(String, String)> = (0..1200)
            .map(|i| (format!("Line number {i}"), format!("Ligne {i}")))
            .collect();
        remember(&conn, &entries, "english", "french").unwrap();
        let asked: Vec<String> = entries.iter().map(|(s, _)| s.clone()).collect();
        let found = lookup(&conn, &asked, "english", "french").unwrap();
        assert_eq!(found.len(), 1200);
    }

    #[test]
    fn stats_and_forget_work_per_language_pair() {
        let conn = open(&temp_path()).unwrap();
        remember(
            &conn,
            &[pair("a", "A"), pair("b", "B")],
            "english",
            "french",
        )
        .unwrap();
        remember(&conn, &[pair("a", "A")], "english", "german").unwrap();

        let s = stats(&conn).unwrap();
        assert_eq!(s[0], ("english".into(), "french".into(), 2));
        assert_eq!(forget(&conn, "english", "french").unwrap(), 2);
        assert_eq!(stats(&conn).unwrap().len(), 1);
    }

    #[test]
    fn a_memory_that_predates_the_normalized_column_is_upgraded_in_place() {
        let path = temp_path();
        {
            let old = Connection::open(&path).unwrap();
            old.execute_batch(CREATE_TABLE).unwrap();
            old.execute(
                "INSERT INTO memory (source_language, target_language, source_text, translated_text) \
                 VALUES ('english', 'french', 'Hello.', 'Bonjour.')",
                [],
            )
            .unwrap();
        }
        let conn = open(&path).unwrap();
        let found = lookup(&conn, &texts(&["HELLO!"]), "english", "french").unwrap();
        assert_eq!(found["HELLO!"], "Bonjour.");
    }
}
