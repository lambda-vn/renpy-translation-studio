//! Writing translations to disk and zipping them up. Port of the save
//! action in `app/views/review_view.py` and of `app/views/export_view.py`.
//! Save is unconditional over every unit regardless of status, matching
//! Python: an unvalidated suggestion is still strictly better than the
//! untouched source text the SDK generated, and a cleared unit is written
//! back as its source text so it does not stay alive in the file.
//!
//! The pre-export warning of 1.0.0 (files out of sync, untranslated lines,
//! lines a quality check refuses) is `export_info`; the dialog showing it
//! belongs to the frontend.

use std::collections::HashMap;

use tauri::State;

use crate::app_state::AppState;
use crate::core::export_sync;
use crate::core::exporter;
use crate::core::renpy::writer::TranslateBlockWriter;
use crate::core::review_actions;
use crate::core::storage::repositories;
use crate::core::translation::quality;

use super::dto::{ExportInfo, FailingFile, SyncPayload};
use super::CommandError;

fn tl_dir(
    session: &crate::mcp_server::session::ProjectSession,
    language: &str,
) -> std::path::PathBuf {
    session.path.join("game").join("tl").join(language)
}

/// Write every stored translation back to the `.rpy` files and record the
/// save, which is what resets the "not written" counter and the export
/// warning. Returns how many lines hold a translation.
#[tauri::command]
pub async fn save_project(state: State<'_, AppState>) -> Result<usize, CommandError> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    let target_language = session.target_language();
    if target_language.is_empty() {
        return Err(CommandError::message("errors.no_target_language"));
    }

    let units = repositories::get_all(session.conn(), None, None).map_err(|e| e.to_string())?;
    let (translations, old_to_new) = review_actions::save_maps(&units);
    if translations.is_empty() && old_to_new.is_empty() {
        return Err(CommandError::message("errors.nothing_to_save"));
    }

    let lang_dir = tl_dir(session, &target_language);
    let writer =
        TranslateBlockWriter::new(lang_dir.clone(), session.path.join(".rts").join("backups"));
    writer
        .write_all(&translations, &old_to_new)
        .map_err(|e| e.to_string())?;
    export_sync::record_save(session.conn(), &lang_dir).map_err(|e| e.to_string())?;
    Ok(units
        .iter()
        .filter(|u| !u.translated_text.is_empty())
        .count())
}

/// What the export screen shows before writing the zip: the proposed game
/// name and file name, how many lines would ship untranslated, which files
/// hold lines a quality check refuses (worst first), and the gap between
/// the database and the `tl/` files.
#[tauri::command]
pub async fn export_info(state: State<'_, AppState>) -> Result<ExportInfo, CommandError> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    let target_language = session.target_language();
    let game_name = exporter::resolve_game_name(&session.path);

    let by_status = repositories::count_by_status(session.conn()).map_err(|e| e.to_string())?;

    let mut per_file: HashMap<String, i64> = HashMap::new();
    for unit in repositories::get_translated(session.conn()).map_err(|e| e.to_string())? {
        if quality::has_blocking_issue(&unit.source_text, &unit.translated_text) {
            *per_file
                .entry(session.relative(&unit.source_file))
                .or_insert(0) += 1;
        }
    }
    let mut failing: Vec<FailingFile> = per_file
        .into_iter()
        .map(|(source_file, count)| FailingFile { source_file, count })
        .collect();
    failing.sort_by(|a, b| {
        b.count
            .cmp(&a.count)
            .then_with(|| a.source_file.cmp(&b.source_file))
    });

    let sync = if target_language.is_empty() {
        None
    } else {
        let state = export_sync::check_sync(session.conn(), &tl_dir(session, &target_language))
            .map_err(|e| e.to_string())?;
        Some(SyncPayload {
            never_saved: state.never_saved,
            unsaved_units: state.unsaved_units,
            externally_modified: state.externally_modified,
            in_sync: state.in_sync(),
        })
    };

    Ok(ExportInfo {
        zip_file_name: exporter::zip_file_name(&game_name, &target_language),
        game_name,
        total: by_status.values().sum(),
        untranslated: by_status.get("not_translated").copied().unwrap_or(0),
        failing,
        sync,
    })
}

/// The zip file name proposed for an edited game name, so the preview
/// under the field follows the typing with the same rules as the export.
#[tauri::command]
pub async fn zip_file_name(
    state: State<'_, AppState>,
    game_name: String,
) -> Result<String, CommandError> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    Ok(exporter::zip_file_name(
        &game_name,
        &session.target_language(),
    ))
}

/// Zip `game/tl/<language>/`. `gameName` is the archive's top folder, as
/// edited on the export screen (blank falls back to `game`, as in 1.0.0);
/// left out, the name resolved from the project is used.
#[tauri::command]
pub async fn export_project(
    state: State<'_, AppState>,
    output_path: String,
    game_name: Option<String>,
) -> Result<(), CommandError> {
    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    let target_language = session.target_language();
    if target_language.is_empty() {
        return Err(CommandError::message("errors.no_target_language"));
    }

    let by_status = repositories::count_by_status(session.conn()).map_err(|e| e.to_string())?;
    if by_status.values().sum::<i64>() == 0 {
        return Err(CommandError::message("errors.nothing_extracted"));
    }

    let game_name = match game_name {
        Some(name) if !name.trim().is_empty() => name.trim().to_string(),
        Some(_) => "game".to_string(),
        None => exporter::resolve_game_name(&session.path),
    };
    exporter::export(
        &tl_dir(session, &target_language),
        &game_name,
        &target_language,
        std::path::Path::new(&output_path),
    )
    .map_err(|e| e.to_string())?;

    // Best effort: the export is done, and a source the game or an editor
    // still has open must not turn it into a reported failure.
    let _ = crate::core::renpy::unpacker::remove_unpacked_sources(&session.path);
    Ok(())
}
