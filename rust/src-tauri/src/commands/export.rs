//! Writing translations to disk and zipping them up. Port of the save
//! action in `app/views/review_view.py` and of `app/views/export_view.py`.
//! Save is unconditional over every translated unit regardless of
//! status, matching Python: an unvalidated suggestion is still strictly
//! better than the untouched source text the SDK generated. The
//! pre-export sync/quality-scan warning dialog Python shows is not
//! ported — this first pass exports whatever `tl/<language>/` holds.

use std::collections::HashMap;

use tauri::State;

use crate::app_state::AppState;
use crate::core::exporter;
use crate::core::renpy::writer::TranslateBlockWriter;
use crate::core::storage::repositories;

fn tl_dir(
    session: &crate::mcp_server::session::ProjectSession,
    language: &str,
) -> std::path::PathBuf {
    session.path.join("game").join("tl").join(language)
}

#[tauri::command]
pub async fn save_project(state: State<'_, AppState>) -> Result<(), String> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    let target_language = session.target_language();
    if target_language.is_empty() {
        return Err("This project has no target language set.".to_string());
    }

    let units = repositories::get_all(session.conn(), None, None).map_err(|e| e.to_string())?;

    let mut translations: HashMap<String, String> = HashMap::new();
    let mut old_to_new: HashMap<String, String> = HashMap::new();
    for unit in units {
        if unit.translated_text.is_empty() {
            continue;
        }
        if unit.block_id.starts_with("strings_") {
            old_to_new.insert(unit.source_text, unit.translated_text);
        } else {
            translations.insert(unit.block_id, unit.translated_text);
        }
    }

    let writer = TranslateBlockWriter::new(
        tl_dir(session, &target_language),
        session.path.join(".rts").join("backup"),
    );
    writer
        .write_all(&translations, &old_to_new)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn export_project(state: State<'_, AppState>, output_path: String) -> Result<(), String> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    let target_language = session.target_language();
    if target_language.is_empty() {
        return Err("This project has no target language set.".to_string());
    }

    let by_status = repositories::count_by_status(session.conn()).map_err(|e| e.to_string())?;
    if by_status.values().sum::<i64>() == 0 {
        return Err("Nothing extracted in this project yet.".to_string());
    }

    let game_name = exporter::resolve_game_name(&session.path);
    exporter::export(
        &tl_dir(session, &target_language),
        &game_name,
        &target_language,
        std::path::Path::new(&output_path),
    )
    .map_err(|e| e.to_string())
}
