//! The character glossary screen: the glossary is edited by hand or
//! filled by scanning the game's sources (`detect_characters`).

use tauri::State;

use crate::app_state::AppState;
use crate::core::project_actions;
use crate::core::renpy::character_detector;
use crate::core::storage::repositories;

use super::dto::CharacterEntry;
use super::CommandError;

/// The whole glossary as DTOs.
fn characters(
    session: &crate::core::project_session::ProjectSession,
) -> Result<Vec<CharacterEntry>, CommandError> {
    Ok(repositories::get_all_characters(session.conn())
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(CharacterEntry::from)
        .collect())
}

/// The glossary as it stands.
///
/// # Errors
///
/// Fails when no project is open or the database cannot be read.
#[tauri::command]
pub async fn list_characters(
    state: State<'_, AppState>,
) -> Result<Vec<CharacterEntry>, CommandError> {
    let guard = state.current.lock().await;
    characters(super::require_session(&guard)?)
}

/// Scan the game's sources for `Character()` definitions and store them.
/// Returns the glossary as it now stands.
///
/// The scan walks every source file without holding the project, so a
/// translation job's chunks keep landing meanwhile; storing then refuses a
/// project opened in between.
///
/// # Errors
///
/// Fails when no project is open, when another project was opened during
/// the scan (`errors.project_changed`), or when the scan task or the
/// database fails.
#[tauri::command]
pub async fn detect_characters(
    state: State<'_, AppState>,
) -> Result<Vec<CharacterEntry>, CommandError> {
    let project = super::require_session(&*state.current.lock().await)?
        .path
        .clone();
    let scanned = project.clone();
    let detected = tokio::task::spawn_blocking(move || character_detector::detect(&scanned))
        .await
        .map_err(|e| e.to_string())?;

    let guard = state.current.lock().await;
    let session = super::require_session_at(&guard, &project)?;
    project_actions::store_characters(session.conn(), &detected).map_err(|e| e.to_string())?;
    characters(session)
}

/// Create or rename the character `variable`, and set its `notes` when
/// given. Returns the glossary as it now stands.
///
/// # Errors
///
/// Fails when no project is open or the database write fails.
#[tauri::command]
pub async fn upsert_character(
    state: State<'_, AppState>,
    variable: String,
    display_name: String,
    notes: Option<String>,
) -> Result<Vec<CharacterEntry>, CommandError> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    repositories::upsert_character(session.conn(), &variable, &display_name)
        .map_err(|e| e.to_string())?;
    if let Some(notes) = &notes {
        repositories::update_character_notes(session.conn(), &variable, notes)
            .map_err(|e| e.to_string())?;
    }
    characters(session)
}

/// Remove the character `variable`. Returns the glossary as it now stands.
///
/// # Errors
///
/// Fails when no project is open or the database write fails.
#[tauri::command]
pub async fn delete_character(
    state: State<'_, AppState>,
    variable: String,
) -> Result<Vec<CharacterEntry>, CommandError> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    repositories::delete_character(session.conn(), &variable).map_err(|e| e.to_string())?;
    characters(session)
}

/// Empty the glossary in one statement, so a failure leaves it whole
/// rather than half deleted.
///
/// # Errors
///
/// Fails when no project is open or the database write fails.
#[tauri::command]
pub async fn delete_all_characters(
    state: State<'_, AppState>,
) -> Result<Vec<CharacterEntry>, CommandError> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    repositories::delete_all_characters(session.conn()).map_err(|e| e.to_string())?;
    characters(session)
}
