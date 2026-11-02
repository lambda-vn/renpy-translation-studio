//! Bilingual files and the translation memory, from the review toolbar;
//! the rules live in `core::interchange` and `core::project_actions`.
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

/// What importing a file would do, as counts: the fields mirror
/// [`ImportPlan`], `applicable` being the number of translations written.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportPreview {
    pub applicable: usize,
    pub unknown: usize,
    pub stale: usize,
    pub empty: usize,
    pub protected: usize,
    pub flagged: usize,
    pub refused: usize,
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
            refused: plan.refused,
        }
    }
}

/// The result of an import: how many translations were written, and the
/// plan that was followed.
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
///
/// # Errors
///
/// Fails when no project is open, when the database cannot be read, or
/// when the file at `path` cannot be written.
#[tauri::command]
pub async fn export_interchange(
    state: State<'_, AppState>,
    path: String,
    source_file: Option<String>,
) -> Result<usize, CommandError> {
    let (units, source_language, target_language) = {
        let guard = state.current.lock().await;
        let session = require_session(&guard)?;
        let absolute = source_file.as_deref().map(|file| session.absolute(file));
        let mut units = repositories::get_all(session.conn(), None, absolute.as_deref())
            .map_err(|e| e.to_string())?;
        for unit in &mut units {
            unit.source_file = session.relative(&unit.source_file);
        }
        (units, session.source_language(), session.target_language())
    };
    tokio::task::spawn_blocking(move || {
        interchange::write_interchange(
            Path::new(&path),
            &units,
            &source_language,
            &target_language,
        )
        .map_err(|e| e.to_string())?;
        Ok(units.len())
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Read and parse a bilingual file without holding the project, so a
/// large file does not stall a translation job's chunks.
async fn read_units(path: String) -> Result<Vec<interchange::InterchangeUnit>, CommandError> {
    tokio::task::spawn_blocking(move || interchange::read_interchange(Path::new(&path)))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| CommandError::from(e.to_string()))
}

/// Read a file and report what importing it would change, writing nothing.
///
/// # Errors
///
/// Fails when the file at `path` cannot be read or parsed, when no project
/// is open, or when the database cannot be read.
#[tauri::command]
pub async fn plan_interchange_import(
    state: State<'_, AppState>,
    path: String,
) -> Result<ImportPreview, CommandError> {
    let units = read_units(path).await?;
    let guard = state.current.clone().lock_owned().await;
    tokio::task::spawn_blocking(move || {
        let session = require_session(&guard)?;
        let plan = interchange::plan_import(&units, session.conn()).map_err(|e| e.to_string())?;
        Ok(ImportPreview::from(&plan))
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Import a file, as [`plan_interchange_import`] described it.
///
/// # Errors
///
/// Fails when the file at `path` cannot be read or parsed, when no project
/// is open, or when reading or writing the database fails.
#[tauri::command]
pub async fn apply_interchange_import(
    state: State<'_, AppState>,
    path: String,
) -> Result<ImportOutcome, CommandError> {
    let units = read_units(path).await?;
    let guard = state.current.clone().lock_owned().await;
    tokio::task::spawn_blocking(move || {
        let session = require_session(&guard)?;
        let plan = interchange::plan_import(&units, session.conn()).map_err(|e| e.to_string())?;
        let applied = interchange::apply_plan(&plan, session.conn()).map_err(|e| e.to_string())?;
        Ok(ImportOutcome {
            applied,
            plan: ImportPreview::from(&plan),
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Fill untranslated lines from the translation memory shared by every
/// project on this machine. Returns the number of lines filled.
///
/// # Errors
///
/// Fails when no project is open or when the memory or the project
/// database cannot be read or written.
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
