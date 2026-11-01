//! The character glossary screen. Port of the CRUD slice of
//! `app/views/character_glossary_view.py`: the glossary is edited by hand
//! or filled by scanning the game's sources (`detect_characters`).

use tauri::State;

use crate::app_state::AppState;
use crate::core::project_actions;
use crate::core::renpy::character_detector;
use crate::core::storage::repositories;

use super::dto::CharacterEntry;
use super::CommandError;

fn characters(
    session: &crate::mcp_server::session::ProjectSession,
) -> Result<Vec<CharacterEntry>, CommandError> {
    Ok(repositories::get_all_characters(session.conn())
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(CharacterEntry::from)
        .collect())
}

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
