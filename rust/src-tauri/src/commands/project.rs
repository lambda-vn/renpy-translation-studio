//! Opening a project and listing the ones the application already knows
//! about. Port of the relevant slice of `app/views/project_setup.py` —
//! resuming an already-extracted project only; running the Ren'Py
//! extraction itself is not ported on this branch (see `rust/README.md`).

use tauri::State;

use crate::app_state::AppState;
use crate::core::project_actions;
use crate::core::storage::{recent_projects, repositories, Database};
use crate::mcp_server::session::{self, ProjectSession};

use super::dto::{ProjectEntry, ProjectInfo};
use super::CommandError;

pub(super) fn project_info(session: &ProjectSession) -> Result<ProjectInfo, String> {
    let by_status = repositories::count_by_status(session.conn()).map_err(|e| e.to_string())?;
    Ok(ProjectInfo {
        path: session.path.display().to_string(),
        game_name: crate::core::exporter::resolve_game_name(&session.path),
        source_language: session.source_language(),
        target_language: session.target_language(),
        by_status,
    })
}

/// Games the application has opened before, most recent first.
#[tauri::command]
pub async fn list_recent_projects() -> Result<Vec<ProjectEntry>, String> {
    let registry = recent_projects::default_path();
    Ok(recent_projects::all(&registry)
        .into_iter()
        .map(|path| {
            let ready = Database::path_for(&path).is_file();
            let name = path
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default();
            ProjectEntry {
                name,
                path: path.display().to_string(),
                ready,
                resume: project_actions::read_resume_info(&path).map(Into::into),
            }
        })
        .collect())
}

/// Drop a game from the recent list without touching it: no file of the
/// game and nothing under its `.rts/` is deleted.
#[tauri::command]
pub async fn forget_project(path: String) -> Result<(), String> {
    recent_projects::remove(
        &recent_projects::default_path(),
        std::path::Path::new(&path),
    );
    Ok(())
}

/// What the cross on a recent-project card does in 1.0.0, after its
/// confirmation: delete the project's `.rts/` folder (saved translations,
/// backups) and forget the entry. The game's own files are not touched.
/// Closes the project first when it is the one open. Irreversible; the
/// caller owns the confirmation.
#[tauri::command]
pub async fn delete_project_data(
    state: State<'_, AppState>,
    path: String,
) -> Result<(), CommandError> {
    let target = std::path::Path::new(&path);
    {
        let mut current = state.current.lock().await;
        if current
            .as_ref()
            .is_some_and(|s| recent_projects::resolve(&s.path) == recent_projects::resolve(target))
        {
            *current = None;
        }
    }
    project_actions::delete_project_data(&recent_projects::default_path(), target).map_err(|e| {
        CommandError::Message {
            key: "errors.delete_data_failed",
            params: serde_json::json!({ "detail": e.to_string() }),
        }
    })
}

/// Open a project already extracted (by this app or another 1.x/2.x
/// install), registering it in the recent-projects list.
#[tauri::command]
pub async fn open_project(state: State<'_, AppState>, path: String) -> Result<ProjectInfo, String> {
    let target = std::path::Path::new(&path);
    let opened = session::open_project(target).map_err(|e| e.to_string())?;
    let info = project_info(&opened)?;
    recent_projects::add(&recent_projects::default_path(), target);
    *state.current.lock().await = Some(opened);
    Ok(info)
}

/// The project currently open, if any — lets a route re-entered without
/// a fresh `open_project` call (navigating back from another screen)
/// recover its context.
#[tauri::command]
pub async fn current_project(state: State<'_, AppState>) -> Result<Option<ProjectInfo>, String> {
    match state.current.lock().await.as_ref() {
        Some(session) => Ok(Some(project_info(session)?)),
        None => Ok(None),
    }
}
