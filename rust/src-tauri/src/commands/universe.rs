//! The universe-summary screen. Port of the manual edit/save slice of
//! `app/views/universe_summary_view.py` — AI generation
//! (`universe_generator.py`) is not ported yet, so the field is
//! filled and saved by hand.

use tauri::State;

use crate::app_state::AppState;
use crate::core::storage::repositories;

const UNIVERSE_SUMMARY_KEY: &str = "universe_summary";

#[tauri::command]
pub async fn get_universe_summary(state: State<'_, AppState>) -> Result<Option<String>, String> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    repositories::get_project_meta(session.conn(), UNIVERSE_SUMMARY_KEY).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn set_universe_summary(
    state: State<'_, AppState>,
    summary: String,
) -> Result<(), String> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    repositories::set_project_meta(session.conn(), UNIVERSE_SUMMARY_KEY, &summary)
        .map_err(|e| e.to_string())
}
