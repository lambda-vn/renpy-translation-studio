//! The review screen's data commands: the file list, a filtered page of
//! units, editing and validating a line. Port of the non-job slice of
//! `app/views/review_view.py`.

use tauri::State;

use crate::app_state::AppState;
use crate::core::storage::{repositories, translation_memory};
use crate::core::translation::quality;

use super::dto::{
    FileEntry, ListUnitsArgs, ListUnitsResult, QualityIssuePayload, UnitPayload, ValidateResult,
};
use super::require_session;

#[tauri::command]
pub async fn list_files(state: State<'_, AppState>) -> Result<Vec<FileEntry>, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    Ok(repositories::get_files(session.conn())
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(|f| FileEntry {
            source_file: session.relative(&f.source_file),
            total: f.total,
            validated: f.validated,
            ai_suggested: f.ai_suggested,
            draft: f.draft,
            imported: f.imported,
        })
        .collect())
}

#[tauri::command]
pub async fn list_units(
    state: State<'_, AppState>,
    args: ListUnitsArgs,
) -> Result<ListUnitsResult, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let source_file = session.absolute(&args.source_file);
    let (units, total) = repositories::get_page(
        session.conn(),
        &source_file,
        args.page,
        args.page_size,
        args.status.as_deref(),
        &args.search,
        args.speaker.as_deref(),
        args.needs_review,
    )
    .map_err(|e| e.to_string())?;
    Ok(ListUnitsResult {
        units: units
            .iter()
            .map(|u| UnitPayload::from_unit(session, u))
            .collect(),
        total,
        page: args.page,
        page_size: args.page_size,
    })
}

/// Store a unit's live text as a draft while the user is still typing.
///
/// Unlike [`validate_unit`], this applies unconditionally, un-validating
/// a previously `ai_suggested` or `human_validated` line on purpose —
/// the field's stored value must track what is on screen so an edit
/// survives navigating away before the user presses validate.
#[tauri::command]
pub async fn save_draft(
    state: State<'_, AppState>,
    block_id: String,
    translated_text: String,
) -> Result<UnitPayload, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    repositories::mark_as_draft(session.conn(), &block_id, &translated_text)
        .map_err(|e| e.to_string())?;
    refetch(session, &block_id)
}

/// Validate a unit: reject on a blocking quality issue, otherwise write
/// `human_validated`. Mirrors the checks `submit_translations` runs for
/// the MCP server and `review_view.py`'s own validate action.
#[tauri::command]
pub async fn validate_unit(
    state: State<'_, AppState>,
    block_id: String,
    translated_text: String,
) -> Result<ValidateResult, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let unit = super::require_unit(session, &block_id)?;

    let translated_text = translated_text.trim().to_string();
    if translated_text.is_empty() {
        return Err("Empty translation.".to_string());
    }

    let issues = quality::check(&unit.source_text, &translated_text);
    let (blocking, warnings): (Vec<_>, Vec<_>) = issues
        .into_iter()
        .partition(|i| i.kind != quality::LENGTH_WARNING_KIND);
    let to_payload = |issues: Vec<quality::QualityIssue>| {
        issues
            .into_iter()
            .map(|i| QualityIssuePayload {
                kind: i.kind,
                detail: i.detail,
            })
            .collect::<Vec<_>>()
    };

    if !blocking.is_empty() {
        return Ok(ValidateResult {
            unit: None,
            blocking_issues: to_payload(blocking),
            warnings: to_payload(warnings),
        });
    }

    repositories::update_translation(
        session.conn(),
        &block_id,
        &translated_text,
        repositories::STATUS_HUMAN_VALIDATED,
    )
    .map_err(|e| e.to_string())?;

    // The shared memory is a convenience, never a reason to refuse a
    // validation: a machine where it cannot be written still translates.
    let _ = translation_memory::open(&translation_memory::default_path()).and_then(|memory| {
        translation_memory::remember(
            &memory,
            &[(unit.source_text.clone(), translated_text.clone())],
            &session.source_language(),
            &session.target_language(),
        )
    });

    Ok(ValidateResult {
        unit: Some(refetch(session, &block_id)?),
        blocking_issues: Vec::new(),
        warnings: to_payload(warnings),
    })
}

#[tauri::command]
pub async fn set_needs_review(
    state: State<'_, AppState>,
    block_id: String,
    needs_review: bool,
) -> Result<UnitPayload, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    super::require_unit(session, &block_id)?;
    repositories::set_needs_review(session.conn(), &block_id, needs_review)
        .map_err(|e| e.to_string())?;
    refetch(session, &block_id)
}

#[tauri::command]
pub async fn set_note(
    state: State<'_, AppState>,
    block_id: String,
    note: String,
) -> Result<UnitPayload, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    super::require_unit(session, &block_id)?;
    repositories::set_note(session.conn(), &block_id, &note).map_err(|e| e.to_string())?;
    repositories::set_needs_review(session.conn(), &block_id, !note.trim().is_empty())
        .map_err(|e| e.to_string())?;
    refetch(session, &block_id)
}

fn refetch(
    session: &crate::mcp_server::session::ProjectSession,
    block_id: &str,
) -> Result<UnitPayload, String> {
    let unit = super::require_unit(session, block_id)?;
    Ok(UnitPayload::from_unit(session, &unit))
}
