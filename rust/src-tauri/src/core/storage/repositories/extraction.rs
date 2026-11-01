//! The three extraction-pipeline steps: re-sync sources, transfer orphans, delete stale.

use rusqlite::{params, Connection, Transaction, TransactionBehavior};

use super::commit;
use super::units::{
    get_all, update_translations_unvalidated, NewUnit, Status, TranslationUnit,
    STATUS_HUMAN_VALIDATED, STATUS_NOT_TRANSLATED,
};

/// What [`resync_sources`] changed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct SourceResync {
    /// Units whose stored source text was replaced.
    pub repaired: usize,
    /// Of those, the suggestions and drafts discarded with the old text.
    pub dropped: usize,
    /// Of those, the `human_validated` ones kept despite the new text.
    pub kept: usize,
}

/// Replace a stored source text the parser now reads differently.
///
/// [`bulk_insert`] ignores a `block_id` it already knows, which is what
/// keeps a re-extraction from wiping the work. The cost is that a unit
/// inserted by an older, wronger parse keeps that text forever.
///
/// A translation answering the old text answers a question that was
/// never asked, so it goes with it, except a `human_validated` one: it may
/// have been typed by someone reading past the noise, and throwing away
/// reviewed work to fix a display bug is the worse trade. Those are
/// counted instead, so the caller can say how many lines deserve a
/// second look.
///
/// Must run before [`transfer_orphan_translations`], which pairs orphans
/// by source text and would otherwise pair them on the text being
/// corrected here.
pub fn resync_sources(conn: &Connection, units: &[NewUnit]) -> rusqlite::Result<SourceResync> {
    if units.is_empty() {
        return Ok(SourceResync::default());
    }
    let parsed: std::collections::HashMap<&str, &NewUnit> =
        units.iter().map(|unit| (unit.block_id, unit)).collect();

    let tx = begin_immediate(conn)?;
    let mut repairs: Vec<(&NewUnit, String)> = Vec::new();
    let mut drops: Vec<String> = Vec::new();
    let mut kept = 0;
    {
        let mut stmt = conn.prepare(
            "SELECT block_id, source_text, translated_text, status FROM translation_units",
        )?;
        let rows = stmt.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
            ))
        })?;
        for row in rows {
            let (block_id, source_text, translated_text, status) = row?;
            let Some(unit) = parsed.get(block_id.as_str()) else {
                continue;
            };
            if unit.source_text == source_text {
                continue;
            }
            repairs.push((unit, block_id.clone()));
            if status == STATUS_HUMAN_VALIDATED {
                kept += 1;
            } else if !translated_text.is_empty() {
                drops.push(block_id);
            }
        }
    }
    if repairs.is_empty() {
        return Ok(SourceResync::default());
    }

    for (unit, block_id) in &repairs {
        conn.execute(
            "UPDATE translation_units SET source_text = ?1, character_variable = ?2 \
             WHERE block_id = ?3",
            params![unit.source_text, unit.character_variable, block_id],
        )?;
    }
    for block_id in &drops {
        conn.execute(
            "UPDATE translation_units SET translated_text = '', status = 'not_translated' \
             WHERE block_id = ?1 AND status != 'human_validated'",
            params![block_id],
        )?;
    }
    commit(tx)?;
    Ok(SourceResync {
        repaired: repairs.len(),
        dropped: drops.len(),
        kept,
    })
}

/// Move translations off vanished block ids onto the lines that remain.
///
/// Ren'Py rebuilds block ids from the script, so an id can disappear while
/// its line is still in the game under a new one. The source text is what
/// identifies a line across versions: every unit still awaiting a
/// translation inherits the text of an orphan sharing its source text. A
/// line the game really dropped has no such match anywhere, and its
/// translation simply dies with it.
///
/// Only `not_translated` units are filled, so no reviewed work is ever
/// replaced. Should several orphans share one source text with different
/// translations, the first in file order wins.
///
/// The orphan keeps its status only when a single line inherits from it,
/// the signature of a line whose id was merely rebuilt. As soon as several
/// lines share the text the translation is spread by similarity, not
/// identity: they become `imported`. Propagating `human_validated` there
/// would mark as reviewed lines nobody ever saw.
///
/// Must run before [`delete_stale`], which removes the drained orphans.
pub fn transfer_orphan_translations(
    conn: &Connection,
    current_block_ids: &std::collections::HashSet<String>,
) -> rusqlite::Result<usize> {
    let tx = begin_immediate(conn)?;
    let units = get_all(conn, None, None)?;
    let mut by_text: std::collections::HashMap<&str, &TranslationUnit> =
        std::collections::HashMap::new();
    for unit in &units {
        if !current_block_ids.contains(&unit.block_id) && unit.status != STATUS_NOT_TRANSLATED {
            by_text.entry(unit.source_text.as_str()).or_insert(unit);
        }
    }
    if by_text.is_empty() {
        return Ok(0);
    }

    let mut heirs: std::collections::HashMap<&str, Vec<&str>> = std::collections::HashMap::new();
    for unit in &units {
        if unit.status == STATUS_NOT_TRANSLATED
            && current_block_ids.contains(&unit.block_id)
            && by_text.contains_key(unit.source_text.as_str())
        {
            heirs
                .entry(unit.source_text.as_str())
                .or_default()
                .push(unit.block_id.as_str());
        }
    }

    let mut entries: Vec<(String, String, Status)> = Vec::new();
    for (source_text, block_ids) in heirs {
        let orphan = by_text[source_text];
        let status = match Status::from_stored(&orphan.status) {
            Some(status) if block_ids.len() == 1 => status,
            _ => Status::Imported,
        };
        for block_id in block_ids {
            entries.push((block_id.to_string(), orphan.translated_text.clone(), status));
        }
    }
    let moved = update_translations_unvalidated(conn, &entries)?;
    commit(tx)?;
    Ok(moved)
}

/// The share of stored units a parse must cover before [`delete_stale`]
/// trusts it.
const MIN_PARSE_COVERAGE: f64 = 0.5;

/// Remove every unit whose block id is absent from the latest parse.
///
/// A row is keyed by its block id: once no file carries that id, nothing
/// can ever be written back to it, whatever its status. Validated units are
/// no exception. What protects the work is [`transfer_orphan_translations`],
/// which must run first to hand each translation over to the line that
/// survived it.
///
/// Nothing is deleted when the parse covers less than half the stored
/// units. A truncated `tl/` folder is a real possibility (the engine
/// hitting its timeout leaves one behind) and it is indistinguishable from
/// a game that legitimately lost that many lines. Keeping obsolete rows
/// costs a few unwritable rows until the next full extraction; deleting
/// live ones destroys reviewed work.
///
/// Returns the number of units deleted, zero when the parse was too small
/// to be trusted.
pub fn delete_stale(
    conn: &Connection,
    current_block_ids: &std::collections::HashSet<String>,
) -> rusqlite::Result<usize> {
    let tx = begin_immediate(conn)?;
    let stored: i64 = conn.query_row("SELECT COUNT(*) FROM translation_units", [], |row| {
        row.get(0)
    })?;
    if (current_block_ids.len() as f64) < stored as f64 * MIN_PARSE_COVERAGE {
        return Ok(0);
    }
    let stale: Vec<String> = {
        let mut stmt = conn.prepare("SELECT block_id FROM translation_units")?;
        let ids = stmt.query_map([], |row| row.get::<_, String>(0))?;
        let mut stale = Vec::new();
        for id in ids {
            let id = id?;
            if !current_block_ids.contains(&id) {
                stale.push(id);
            }
        }
        stale
    };
    {
        let mut stmt = conn.prepare("DELETE FROM translation_units WHERE block_id = ?1")?;
        for id in &stale {
            stmt.execute(params![id])?;
        }
    }
    commit(tx)?;
    Ok(stale.len())
}

/// Like [`begin`], but takes the write lock at once, so that a read made
/// before a write sees the data the write is then applied to.
fn begin_immediate(conn: &Connection) -> rusqlite::Result<Option<Transaction<'_>>> {
    conn.is_autocommit()
        .then(|| Transaction::new_unchecked(conn, TransactionBehavior::Immediate))
        .transpose()
}

#[cfg(test)]
mod tests {
    use super::super::test_support::{open_temp, unit};
    use super::super::units::{bulk_insert, get_many, update_translation};
    use super::*;

    fn ids(block_ids: &[&str]) -> std::collections::HashSet<String> {
        block_ids.iter().map(|id| id.to_string()).collect()
    }

    #[test]
    fn resync_drops_suggestions_but_keeps_validated_work() {
        let db = open_temp();
        bulk_insert(
            db.conn(),
            &[unit("a", "old a"), unit("b", "old b"), unit("c", "same")],
        )
        .unwrap();
        update_translation(db.conn(), "a", "vieux a", Status::AiSuggested).unwrap();
        update_translation(db.conn(), "b", "vieux b", Status::HumanValidated).unwrap();

        let outcome = resync_sources(
            db.conn(),
            &[unit("a", "new a"), unit("b", "new b"), unit("c", "same")],
        )
        .unwrap();

        assert_eq!(
            outcome,
            SourceResync {
                repaired: 2,
                dropped: 1,
                kept: 1
            }
        );
        let a = get_many(db.conn(), &["a".to_string()]).unwrap();
        assert_eq!(a[0].source_text, "new a");
        assert_eq!(a[0].status, STATUS_NOT_TRANSLATED);
        assert_eq!(a[0].translated_text, "");
        let b = get_many(db.conn(), &["b".to_string()]).unwrap();
        assert_eq!(b[0].source_text, "new b");
        assert_eq!(b[0].status, STATUS_HUMAN_VALIDATED);
        assert_eq!(b[0].translated_text, "vieux b");
    }

    #[test]
    fn a_translation_follows_its_line_when_the_block_id_is_rebuilt() {
        let db = open_temp();
        bulk_insert(db.conn(), &[unit("old_id", "Hello.")]).unwrap();
        update_translation(db.conn(), "old_id", "Bonjour.", Status::HumanValidated).unwrap();
        bulk_insert(db.conn(), &[unit("new_id", "Hello.")]).unwrap();

        let moved = transfer_orphan_translations(db.conn(), &ids(&["new_id"])).unwrap();

        assert_eq!(moved, 1);
        let heir = get_many(db.conn(), &["new_id".to_string()]).unwrap();
        assert_eq!(heir[0].translated_text, "Bonjour.");
        assert_eq!(heir[0].status, STATUS_HUMAN_VALIDATED);
    }

    #[test]
    fn a_translation_spread_over_several_lines_becomes_imported() {
        let db = open_temp();
        bulk_insert(db.conn(), &[unit("old_id", "Yes.")]).unwrap();
        update_translation(db.conn(), "old_id", "Oui.", Status::HumanValidated).unwrap();
        bulk_insert(db.conn(), &[unit("n1", "Yes."), unit("n2", "Yes.")]).unwrap();

        let moved = transfer_orphan_translations(db.conn(), &ids(&["n1", "n2"])).unwrap();

        assert_eq!(moved, 2);
        for heir in get_many(db.conn(), &["n1".to_string(), "n2".to_string()]).unwrap() {
            assert_eq!(heir.translated_text, "Oui.");
            assert_eq!(heir.status, "imported");
        }
    }

    #[test]
    fn a_validated_heir_is_never_overwritten_by_a_transfer() {
        let db = open_temp();
        bulk_insert(db.conn(), &[unit("old_id", "Hi."), unit("new_id", "Hi.")]).unwrap();
        update_translation(db.conn(), "old_id", "Salut.", Status::AiSuggested).unwrap();
        update_translation(db.conn(), "new_id", "Coucou.", Status::HumanValidated).unwrap();

        let moved = transfer_orphan_translations(db.conn(), &ids(&["new_id"])).unwrap();

        assert_eq!(moved, 0);
        let heir = get_many(db.conn(), &["new_id".to_string()]).unwrap();
        assert_eq!(heir[0].translated_text, "Coucou.");
    }

    #[test]
    fn delete_stale_removes_vanished_units() {
        let db = open_temp();
        bulk_insert(db.conn(), &[unit("a", "A"), unit("b", "B"), unit("c", "C")]).unwrap();

        let deleted = delete_stale(db.conn(), &ids(&["a", "b"])).unwrap();

        assert_eq!(deleted, 1);
        let left: Vec<String> = get_all(db.conn(), None, None)
            .unwrap()
            .into_iter()
            .map(|u| u.block_id)
            .collect();
        assert_eq!(left, ["a", "b"]);
    }

    #[test]
    fn delete_stale_refuses_to_trust_a_truncated_parse() {
        let db = open_temp();
        bulk_insert(
            db.conn(),
            &[
                unit("a", "A"),
                unit("b", "B"),
                unit("c", "C"),
                unit("d", "D"),
            ],
        )
        .unwrap();

        let deleted = delete_stale(db.conn(), &ids(&["a"])).unwrap();

        assert_eq!(deleted, 0);
        assert_eq!(get_all(db.conn(), None, None).unwrap().len(), 4);
    }

    #[test]
    fn resync_composes_with_a_transaction_the_caller_holds() {
        let db = open_temp();
        let conn = db.conn();
        bulk_insert(conn, &[unit("a", "old a")]).unwrap();
        update_translation(conn, "a", "vieux a", Status::AiSuggested).unwrap();

        conn.execute_batch("BEGIN").unwrap();
        let outcome = resync_sources(conn, &[unit("a", "new a")]).unwrap();
        conn.execute_batch("COMMIT").unwrap();

        assert_eq!(outcome.dropped, 1);
        let a = get_many(conn, &["a".to_string()]).unwrap();
        assert_eq!(a[0].status, STATUS_NOT_TRANSLATED);
    }
}
