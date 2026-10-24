//! The character glossary screen. Port of the CRUD slice of
//! `app/views/character_glossary_view.py` — `Character()` source
//! scanning (`detect_and_store_characters`) is not ported (see
//! `rust/README.md`); characters are added and edited by hand.

use tauri::State;

use crate::app_state::AppState;
use crate::core::storage::repositories;

use super::dto::CharacterEntry;

fn characters(
    session: &crate::mcp_server::session::ProjectSession,
) -> Result<Vec<CharacterEntry>, String> {
    Ok(repositories::get_all_characters(session.conn())
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(CharacterEntry::from)
        .collect())
}

#[tauri::command]
pub async fn list_characters(state: State<'_, AppState>) -> Result<Vec<CharacterEntry>, String> {
    let guard = state.current.lock().await;
    characters(super::require_session(&guard)?)
}

#[tauri::command]
pub async fn upsert_character(
    state: State<'_, AppState>,
    variable: String,
    display_name: String,
    notes: Option<String>,
) -> Result<Vec<CharacterEntry>, String> {
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
) -> Result<Vec<CharacterEntry>, String> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    repositories::delete_character(session.conn(), &variable).map_err(|e| e.to_string())?;
    characters(session)
}
