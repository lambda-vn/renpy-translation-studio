//! Bilingual files and the translation memory, from the review toolbar.
//! Port of the interchange and memory handlers of
//! `app/views/review_view.py`; the rules live in `core::interchange` and
//! `core::project_actions`.
//!
//! Importing is two calls on purpose: [`plan_interchange_import`] reads the
//! file and says what it would do, [`apply_interchange_import`] does it.
//! The file is read again at the second call rather than held between the
//! two, so nothing stale can be applied and the application keeps no state
//! about a file it was shown.

use std::path::Path;

use serde::Serialize;
use tauri::State;

use crate::app_state::AppState;
use crate::core::interchange::{self, ImportPlan};
use crate::core::project_actions;
use crate::core::storage::{repositories, translation_memory};

use super::{require_session, CommandError};

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportPreview {
    pub applicable: usize,
    pub unknown: usize,
    pub stale: usize,
    pub empty: usize,
    pub protected: usize,
    pub flagged: usize,
}

impl From<&ImportPlan> for ImportPreview {
    fn from(plan: &ImportPlan) -> Self {
        Self {
            applicable: plan.applicable(),
            unknown: plan.unknown,
            stale: plan.stale,
            empty: plan.empty,
            protected: plan.protected,
            flagged: plan.flagged,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportOutcome {
    pub applied: usize,
    pub plan: ImportPreview,
}

/// Write the chosen scope to a bilingual file whose extension names the
/// format. The whole scope goes out, untranslated lines included: sending
/// the file to a translator is precisely what it is for.
///
/// Source files leave as paths relative to the game, unlike 1.x which
/// wrote the absolute ones: a file sent to someone else has no business
/// carrying the layout of this disk, and pairing is by block id anyway.
///
/// Returns the number of units written.
#[tauri::command]
pub async fn export_interchange(
    state: State<'_, AppState>,
    path: String,
    source_file: Option<String>,
) -> Result<usize, CommandError> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let absolute = source_file.as_deref().map(|file| session.absolute(file));
    let mut units = repositories::get_all(session.conn(), None, absolute.as_deref())
        .map_err(|e| e.to_string())?;
    for unit in &mut units {
        unit.source_file = session.relative(&unit.source_file);
    }
    interchange::write_interchange(
        Path::new(&path),
        &units,
        &session.source_language(),
        &session.target_language(),
    )
    .map_err(|e| e.to_string())?;
    Ok(units.len())
}

fn plan_for(
    session: &crate::mcp_server::session::ProjectSession,
    path: &str,
) -> Result<ImportPlan, String> {
    let units = interchange::read_interchange(Path::new(path)).map_err(|e| e.to_string())?;
    interchange::plan_import(&units, session.conn()).map_err(|e| e.to_string())
}

/// Read a file and report what importing it would change, writing nothing.
#[tauri::command]
pub async fn plan_interchange_import(
    state: State<'_, AppState>,
    path: String,
) -> Result<ImportPreview, CommandError> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    Ok(ImportPreview::from(&plan_for(session, &path)?))
}

/// Import a file, as [`plan_interchange_import`] described it.
#[tauri::command]
pub async fn apply_interchange_import(
    state: State<'_, AppState>,
    path: String,
) -> Result<ImportOutcome, CommandError> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let plan = plan_for(session, &path)?;
    let applied = interchange::apply_plan(&plan, session.conn()).map_err(|e| e.to_string())?;
    Ok(ImportOutcome {
        applied,
        plan: ImportPreview::from(&plan),
    })
}

/// Fill untranslated lines from the translation memory shared by every
/// project on this machine. Returns the number of lines filled.
#[tauri::command]
pub async fn fill_from_memory(state: State<'_, AppState>) -> Result<usize, CommandError> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    project_actions::fill_from_memory(
        session.conn(),
        &translation_memory::default_path(),
        &session.source_language(),
        &session.target_language(),
    )
    .map_err(|e| e.to_string().into())
}
