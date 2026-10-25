//! The universe-summary screen. Port of `app/views/universe_summary_view.py`:
//! the field is edited and saved by hand, or drafted from a sample of the
//! game's dialogue by an LLM.

use tauri::State;

use crate::app_state::AppState;
use crate::core::storage::repositories;
use crate::core::translation::providers::registry;
use crate::core::translation::universe_generator;

use super::CommandError;

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

/// Draft a summary from a sample of the game's dialogue.
///
/// The text is returned, never stored: it replaces the field in the
/// interface and nothing is saved until the user says so. Sending game text
/// to the provider is the user's call, confirmed by the interface every
/// time; this command only runs when asked.
///
/// The project and settings locks are released before the request, which
/// can take a while on a small local model, so that the rest of the
/// application stays usable meanwhile.
#[tauri::command]
pub async fn generate_universe_summary(state: State<'_, AppState>) -> Result<String, CommandError> {
    let (units, target_language) = {
        let guard = state.current.lock().await;
        let session = super::require_session(&guard)?;
        (
            repositories::get_all(session.conn(), None, None).map_err(|e| e.to_string())?,
            session.target_language(),
        )
    };
    if units.is_empty() {
        return Err("No extracted text to analyze: extract the game first."
            .to_string()
            .into());
    }
    let mut provider = {
        let mut settings = state.settings.lock().await;
        registry::ollama(&mut settings, None, Vec::new())?
    };
    Ok(universe_generator::generate(&units, &mut provider, &target_language).await?)
}
