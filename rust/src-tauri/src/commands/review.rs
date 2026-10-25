//! The review screen's data commands: the file list, a filtered page of
//! units, editing, validating, clearing and the small readings the panel
//! needs. Port of the non-job slice of `app/views/review_view.py`.

use std::collections::HashMap;

use tauri::State;

use crate::app_state::AppState;
use crate::core::review_actions::{self, UnitFilter};
use crate::core::storage::{repositories, translation_memory};
use crate::core::translation::quality;
use crate::mcp_server::session::ProjectSession;

use super::dto::{
    ClearArgs, DuplicatePayload, FileEntry, ListUnitsArgs, ListUnitsResult, ProgressPayload,
    PropagateResult, QualityIssuePayload, SpeakerEntry, UnitPayload, ValidateResult,
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
            path: f.source_file,
            total: f.total,
            validated: f.validated,
            ai_suggested: f.ai_suggested,
            draft: f.draft,
            imported: f.imported,
        })
        .collect())
}

/// One page of a file's lines under the review filters. `errorsOnly` is
/// the "In error" filter; the other filters page in SQL. `duplicates`
/// carries the occurrence counts of the page's repeated source texts.
#[tauri::command]
pub async fn list_units(
    state: State<'_, AppState>,
    args: ListUnitsArgs,
) -> Result<ListUnitsResult, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let source_file = session.absolute(&args.source_file);
    let filter = UnitFilter {
        status: args.status.clone(),
        search: args.search.clone(),
        speaker: args.speaker.clone(),
        needs_review: args.needs_review,
        errors_only: args.errors_only,
    };
    let (units, total) = review_actions::page_of_units(
        session.conn(),
        &source_file,
        &filter,
        args.page,
        args.page_size,
    )
    .map_err(|e| e.to_string())?;
    let texts: Vec<String> = units.iter().map(|u| u.source_text.clone()).collect();
    let counts = repositories::count_duplicates(session.conn(), &texts, &source_file)
        .map_err(|e| e.to_string())?;
    let duplicates: HashMap<String, DuplicatePayload> = units
        .iter()
        .filter_map(|u| {
            counts.get(&u.source_text).map(|d| {
                (
                    u.block_id.clone(),
                    DuplicatePayload {
                        total: d.total,
                        other_files: d.other_files,
                    },
                )
            })
        })
        .collect();
    Ok(ListUnitsResult {
        units: units
            .iter()
            .map(|u| UnitPayload::from_unit(session, u))
            .collect(),
        duplicates,
        total,
        page: args.page,
        page_size: args.page_size,
    })
}

/// How many lines of each file match a search, a speaker and/or the
/// review flag (under the status filter), keyed by relative path, files
/// without a match omitted. Empty when nothing narrows the project down.
/// Turns the file panel into the map of a question the open page can only
/// answer for its own file.
#[tauri::command]
pub async fn count_matches(
    state: State<'_, AppState>,
    search: String,
    status: Option<String>,
    speaker: Option<String>,
    needs_review: bool,
) -> Result<HashMap<String, i64>, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    Ok(repositories::count_matches_by_file(
        session.conn(),
        &search,
        status.as_deref(),
        speaker.as_deref(),
        needs_review,
    )
    .map_err(|e| e.to_string())?
    .into_iter()
    .map(|(file, n)| (session.relative(&file), n))
    .collect())
}

/// The speakers of the whole project for the speaker filter, labelled by
/// the glossary's display name when there is one. Project-wide and not
/// per file, so a speaker silent in the open file is not mistaken for one
/// who says nothing at all; empty when no line has a speaker.
#[tauri::command]
pub async fn list_speakers(state: State<'_, AppState>) -> Result<Vec<SpeakerEntry>, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let names: HashMap<String, String> = repositories::get_all_characters(session.conn())
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(|c| (c.variable, c.display_name))
        .collect();
    Ok(repositories::character_variables(session.conn())
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(|variable| SpeakerEntry {
            label: names
                .get(&variable)
                .filter(|n| !n.is_empty())
                .cloned()
                .unwrap_or_else(|| variable.clone()),
            variable,
        })
        .collect())
}

/// Whole-project progress in lines and words (the bar and its tooltip).
#[tauri::command]
pub async fn project_progress(state: State<'_, AppState>) -> Result<ProgressPayload, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let p = repositories::project_progress(session.conn()).map_err(|e| e.to_string())?;
    Ok(ProgressPayload {
        lines: p.lines,
        validated_lines: p.validated_lines,
        words: p.words,
        validated_words: p.validated_words,
    })
}

/// The lines around one line, itself included, in file order: what the
/// row's context toggle shows. Ignores the page and the filter.
#[tauri::command]
pub async fn get_context(
    state: State<'_, AppState>,
    block_id: String,
    radius: Option<i64>,
) -> Result<Vec<UnitPayload>, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let unit = super::require_unit(session, &block_id)?;
    let window = repositories::get_neighbours(
        session.conn(),
        &unit.source_file,
        unit.source_line,
        radius.unwrap_or(2).clamp(0, 20),
    )
    .map_err(|e| e.to_string())?;
    Ok(window
        .iter()
        .map(|u| UnitPayload::from_unit(session, u))
        .collect())
}

/// The units carrying these identifiers, as the review screen shows them.
/// Unknown ids are skipped. Answers the live-refresh channel, which says
/// which lines another process just wrote and nothing about their content.
#[tauri::command]
pub async fn get_units(
    state: State<'_, AppState>,
    block_ids: Vec<String>,
) -> Result<Vec<UnitPayload>, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let units = repositories::get_many(session.conn(), &block_ids).map_err(|e| e.to_string())?;
    Ok(units
        .iter()
        .map(|unit| UnitPayload::from_unit(session, unit))
        .collect())
}

/// Store a unit's live text as a draft while the user is still typing.
///
/// Unlike [`validate_unit`], this applies unconditionally, un-validating
/// a previously `ai_suggested` or `human_validated` line on purpose —
/// the field's stored value must track what is on screen so an edit
/// survives navigating away before the user presses validate. An empty
/// text resets the line to `not_translated`, which is also what the row's
/// "erase" action does (flag and note untouched).
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
/// the MCP server and `review_view.py`'s own validate action. `duplicates`
/// tells how many other lines share the source text and could receive the
/// translation (1.0.0 offers that in a toast after every validation).
#[tauri::command]
pub async fn validate_unit(
    state: State<'_, AppState>,
    block_id: String,
    translated_text: String,
) -> Result<ValidateResult, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let unit = super::require_unit(session, &block_id)?;
    let outcome = review_actions::validate_translation(session.conn(), &unit, &translated_text)?;

    let Some(stored) = outcome.stored else {
        return Ok(ValidateResult {
            unit: None,
            blocking_issues: issues_payload(outcome.blocking),
            warnings: issues_payload(outcome.warnings),
            duplicates: 0,
        });
    };
    remember(session, &unit.source_text, &stored);
    let duplicates =
        repositories::find_duplicate_block_ids(session.conn(), &unit.source_text, &block_id)
            .map_err(|e| e.to_string())?
            .len();
    Ok(ValidateResult {
        unit: Some(refetch(session, &block_id)?),
        blocking_issues: Vec::new(),
        warnings: issues_payload(outcome.warnings),
        duplicates,
    })
}

/// Validate a line, then hand its translation to every other line with an
/// identical source text that is not already validated (Ctrl+Shift+Enter).
///
/// Validating first is what makes it safe: a line the quality checks
/// refuse spreads nothing. Validated lines are never overwritten, whatever
/// their text. Only the clicked line goes to the translation memory, as in
/// 1.0.0. `propagated` lists the other lines written, possibly none.
#[tauri::command]
pub async fn validate_and_propagate(
    state: State<'_, AppState>,
    block_id: String,
    translated_text: String,
) -> Result<PropagateResult, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let unit = super::require_unit(session, &block_id)?;
    let outcome = review_actions::validate_translation(session.conn(), &unit, &translated_text)?;

    let Some(stored) = outcome.stored else {
        return Ok(PropagateResult {
            unit: None,
            blocking_issues: issues_payload(outcome.blocking),
            warnings: issues_payload(outcome.warnings),
            propagated: Vec::new(),
        });
    };
    remember(session, &unit.source_text, &stored);
    let propagated =
        review_actions::spread_to_duplicates(session.conn(), &unit.source_text, &block_id, &stored)
            .map_err(|e| e.to_string())?;
    Ok(PropagateResult {
        unit: Some(refetch(session, &block_id)?),
        blocking_issues: Vec::new(),
        warnings: issues_payload(outcome.warnings),
        propagated,
    })
}

/// Apply an already validated line's translation to the other lines
/// sharing its source text (the toast action after a plain validation).
/// Refuses a line that is not `human_validated`, so what spreads has been
/// through the quality gate. Returns the lines written.
#[tauri::command]
pub async fn spread_to_duplicates(
    state: State<'_, AppState>,
    block_id: String,
) -> Result<Vec<String>, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let unit = super::require_unit(session, &block_id)?;
    if unit.status != repositories::STATUS_HUMAN_VALIDATED {
        return Err("Validate the line first.".to_string());
    }
    review_actions::spread_to_duplicates(
        session.conn(),
        &unit.source_text,
        &block_id,
        &unit.translated_text,
    )
    .map_err(|e| e.to_string())
}

/// Reset translations to `not_translated` and empty their text, for the
/// whole project or one file. `scope` picks what is reachable:
/// `unvalidated` (suggestions, drafts, imports), `ai_suggested`, or `all`
/// (validated lines too). Flags and notes are never touched. Returns how
/// many lines were cleared. The confirmation belongs to the caller.
#[tauri::command]
pub async fn clear_translations(
    state: State<'_, AppState>,
    args: ClearArgs,
) -> Result<usize, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    let statuses = review_actions::clear_statuses(args.scope.as_deref())?;
    let source_file = args.source_file.as_deref().map(|f| session.absolute(f));
    repositories::clear_translations(session.conn(), source_file.as_deref(), statuses.as_deref())
        .map_err(|e| e.to_string())
}

/// Lines edited since the last save to the `.rpy` files (every line
/// carrying work when never saved): the "N lines not written" counter.
#[tauri::command]
pub async fn unwritten_count(state: State<'_, AppState>) -> Result<i64, String> {
    let guard = state.current.lock().await;
    let session = require_session(&guard)?;
    crate::core::export_sync::count_unwritten(session.conn()).map_err(|e| e.to_string())
}

/// Show a file in the desktop file manager, selected. Runs on the Rust
/// side and only for a file the project knows, so the frontend needs no
/// opener permission over arbitrary paths. Copying the path is the
/// frontend's (`FileEntry.path`), and "open" in 1.0.0 only selects the
/// file in the panel.
#[tauri::command]
pub async fn reveal_file(state: State<'_, AppState>, source_file: String) -> Result<(), String> {
    let path = {
        let guard = state.current.lock().await;
        let session = require_session(&guard)?;
        let stored = session.absolute(&source_file);
        let known = repositories::get_files(session.conn())
            .map_err(|e| e.to_string())?
            .iter()
            .any(|f| f.source_file == stored);
        if !known {
            return Err(format!("Unknown file: {source_file}"));
        }
        std::path::PathBuf::from(stored)
    };
    if !path.is_file() {
        return Err(format!("No such file: {}", path.display()));
    }
    tauri_plugin_opener::reveal_item_in_dir(&path).map_err(|e| e.to_string())
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

fn issues_payload(issues: Vec<quality::QualityIssue>) -> Vec<QualityIssuePayload> {
    issues
        .into_iter()
        .map(|i| QualityIssuePayload {
            kind: i.kind,
            detail: i.detail,
        })
        .collect()
}

/// The shared memory is a convenience, never a reason to refuse a
/// validation: a machine where it cannot be written still translates.
fn remember(session: &ProjectSession, source_text: &str, translated: &str) {
    let _ = translation_memory::open(&translation_memory::default_path()).and_then(|memory| {
        translation_memory::remember(
            &memory,
            &[(source_text.to_string(), translated.to_string())],
            &session.source_language(),
            &session.target_language(),
        )
    });
}

fn refetch(session: &ProjectSession, block_id: &str) -> Result<UnitPayload, String> {
    let unit = super::require_unit(session, block_id)?;
    Ok(UnitPayload::from_unit(session, &unit))
}
