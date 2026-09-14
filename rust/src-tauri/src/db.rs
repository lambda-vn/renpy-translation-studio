//! Tauri commands bridging the frontend to `core::storage`.

use serde::Serialize;

use crate::core::storage::{repositories, Database};

#[derive(Serialize)]
pub struct TranslationUnit {
    block_id: String,
    source_file: String,
    source_line: i64,
    source_text: String,
    translated_text: String,
    status: String,
}

impl From<repositories::TranslationUnit> for TranslationUnit {
    fn from(u: repositories::TranslationUnit) -> Self {
        Self {
            block_id: u.block_id,
            source_file: u.source_file,
            source_line: u.source_line,
            source_text: u.source_text,
            translated_text: u.translated_text,
            status: u.status,
        }
    }
}

#[derive(Serialize)]
pub struct ProjectSummary {
    total: i64,
    human_validated: i64,
    units: Vec<TranslationUnit>,
}

#[tauri::command]
pub fn open_project(db_path: String, limit: i64) -> Result<ProjectSummary, String> {
    let db = Database::open_readonly(db_path.as_ref()).map_err(|e| e.to_string())?;
    let progress = repositories::project_progress(db.conn()).map_err(|e| e.to_string())?;
    let mut units = repositories::get_all(db.conn(), None, None).map_err(|e| e.to_string())?;
    units.truncate(limit.max(0) as usize);

    Ok(ProjectSummary {
        total: progress.lines,
        human_validated: progress.validated_lines,
        units: units.into_iter().map(Into::into).collect(),
    })
}
