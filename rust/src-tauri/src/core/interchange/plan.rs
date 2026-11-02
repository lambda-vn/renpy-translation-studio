//! The import policy: what an interchange file would change in the project,
//! and the commit of that plan.

use std::collections::HashMap;

use rusqlite::Connection;
use serde::Serialize;

use super::InterchangeUnit;
use crate::core::storage::repositories::{self, Status, TranslationUnit};
use crate::core::translation::quality;

/// What an interchange file would do to the project, before it does it.
///
/// Nothing here has been written yet, so a plan can be shown, counted and
/// thrown away. [`apply_plan`] is what commits it.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct ImportPlan {
    /// The `(block_id, translated_text, status)` triples that would be
    /// written.
    #[serde(skip)]
    pub entries: Vec<(String, String, Status)>,
    /// Block ids the project does not hold, typically a file exported from
    /// another game.
    pub unknown: usize,
    /// Units whose source text no longer matches the project, so the
    /// translation would land on a line that has since changed.
    pub stale: usize,
    /// Units the file brought back without a translation, left alone
    /// rather than clearing what the project already holds.
    pub empty: usize,
    /// Units already validated by a human, which an import never replaces.
    pub protected: usize,
    /// Units left alone whatever their status, the translation adding an
    /// interpolation the source does not have: Ren'Py would run it.
    pub refused: usize,
}

impl ImportPlan {
    /// How many translations applying this plan would write.
    pub fn applicable(&self) -> usize {
        self.entries.len()
    }
}

/// Work out what an interchange file would change, without changing it.
///
/// Every unit is paired by block id, so a file may hold a subset of the
/// project, come back reordered, or carry rows the project never had. Five
/// cases are counted instead of applied, and reported rather than silently
/// dropped: unknown ids, a source text that has changed since the export,
/// an empty translation, a line a human already validated, and a
/// translation adding an interpolation the source does not have (Ren'Py
/// would run it).
///
/// What remains is written as `imported`, whatever status the file claims.
/// A file comes from outside and nobody reviewed it here: its status column
/// is not evidence, so it can neither validate a line nor replace one a
/// human validated. A translation identical to the project's is skipped,
/// so a file exported and imported back unchanged changes nothing.
///
/// # Errors
///
/// A SQLite error when the project's units cannot be read.
pub fn plan_import(units: &[InterchangeUnit], conn: &Connection) -> rusqlite::Result<ImportPlan> {
    let stored: HashMap<String, TranslationUnit> = repositories::get_all(conn, None, None)?
        .into_iter()
        .map(|unit| (unit.block_id.clone(), unit))
        .collect();
    let mut plan = ImportPlan::default();

    for unit in units {
        let Some(current) = stored.get(&unit.block_id) else {
            plan.unknown += 1;
            continue;
        };
        if unit.translated_text.trim().is_empty() {
            plan.empty += 1;
        } else if !unit.source_text.is_empty() && unit.source_text != current.source_text {
            plan.stale += 1;
        } else if unit.translated_text == current.translated_text {
            continue;
        } else if current.status == repositories::STATUS_HUMAN_VALIDATED {
            plan.protected += 1;
        } else if quality::has_extra_var(&current.source_text, &unit.translated_text) {
            plan.refused += 1;
        } else {
            plan.entries.push((
                unit.block_id.clone(),
                unit.translated_text.clone(),
                Status::Imported,
            ));
        }
    }
    Ok(plan)
}

/// Write the translations a plan holds; returns how many units were
/// actually updated.
///
/// The write itself skips any line validated since the plan was made, so
/// another process validating a line in between keeps its text.
///
/// # Errors
///
/// A SQLite error when the update fails.
pub fn apply_plan(plan: &ImportPlan, conn: &Connection) -> rusqlite::Result<usize> {
    repositories::update_translations_unvalidated(conn, &plan.entries)
}
