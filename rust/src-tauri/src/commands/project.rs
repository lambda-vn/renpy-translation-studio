//! Opening a project and listing the ones the application already knows
//! about. Port of the relevant slice of `app/views/project_setup.py` —
//! resuming an already-extracted project only; running the Ren'Py
//! extraction itself is not ported on this branch (see `rust/README.md`).

use tauri::State;

use crate::app_state::AppState;
use crate::core::storage::{recent_projects, repositories, Database};
use crate::mcp_server::session::{self, ProjectSession};

use super::dto::{ProjectEntry, ProjectInfo};

fn project_info(session: &ProjectSession) -> Result<ProjectInfo, String> {
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
            }
        })
        .collect())
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
