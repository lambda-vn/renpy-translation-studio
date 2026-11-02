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
    /// Units already validated by a human, which only an incoming
    /// validated status may replace.
    pub protected: usize,
    /// Units written as drafts instead of validated, a quality check
    /// having refused the text. They are part of `entries`.
    pub flagged: usize,
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
/// project, come back reordered, or carry rows the project never had. Four
/// cases are counted instead of applied, and reported rather than silently
/// dropped: unknown ids, a source text that has changed since the export,
/// an empty translation, and a line a human already validated.
///
/// A fifth is counted and applied: a rewritten translation a quality check
/// refuses comes in as a draft rather than validated. The same text typed
/// into the review screen behaves exactly that way, so an import is no
/// longer a way to reach `human_validated` with a dropped `[player_name]`.
/// Dropping the text outright would be worse than keeping it: the project
/// would hold on to whatever broken translation it already had, and saving
/// writes that one to the `.rpy` just the same.
///
/// The exception is a translation adding an interpolation, refused under
/// any status: a draft is written to the `.rpy` as surely as a validated
/// line, and what it adds is code.
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
        } else if current.status == "human_validated" && unit.status != "human_validated" {
            plan.protected += 1;
        } else if quality::has_extra_var(&current.source_text, &unit.translated_text) {
            plan.refused += 1;
        } else {
            let incoming = incoming_status(unit, current);
            let status = if must_be_drafted(unit, current, &incoming) {
                plan.flagged += 1;
                Status::Draft
            } else {
                Status::from_stored(&incoming).unwrap_or(Status::Imported)
            };
            plan.entries
                .push((unit.block_id.clone(), unit.translated_text.clone(), status));
        }
    }
    Ok(plan)
}

/// Write the translations a plan holds; returns how many units were
/// actually updated.
///
/// # Errors
///
/// A SQLite error when the update fails.
pub fn apply_plan(plan: &ImportPlan, conn: &Connection) -> rusqlite::Result<usize> {
    repositories::update_translations(conn, &plan.entries)
}

/// Whether a translation may not come in as validated.
///
/// Only a rewritten text is weighed. One that matches what the project
/// already holds changes nothing, and re-judging it would have a file
/// exported and imported back unchanged report refusals it did not cause.
///
/// The rule itself is the review screen's: everything the quality check
/// reports bars validation, except the length warning, which flags an
/// unusual ratio rather than something broken.
fn must_be_drafted(unit: &InterchangeUnit, current: &TranslationUnit, status: &str) -> bool {
    if status != "human_validated" || unit.translated_text == current.translated_text {
        return false;
    }
    quality::check(&current.source_text, &unit.translated_text)
        .iter()
        .any(|issue| issue.kind.blocks_validation())
}

/// What status a translation coming back deserves.
///
/// A file edited outside the studio keeps the status column it left with,
/// so text a proofreader rewrote in a spreadsheet still reads
/// `ai_suggested` on the way back. Storing it as such would hand human work
/// to "clear the AI suggestions", which erases it without a word. Text that
/// differs from what the project holds is therefore taken as `imported`.
///
/// A file that went out and came back untouched keeps its status, so the
/// round-trip through the studio's own formats stays lossless.
fn incoming_status(unit: &InterchangeUnit, current: &TranslationUnit) -> String {
    let rewritten = unit.translated_text != current.translated_text;
    if unit.status == "ai_suggested" && rewritten {
        "imported".to_string()
    } else {
        unit.status.clone()
    }
}
