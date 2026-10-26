//! Starting, monitoring and cancelling a translation job, and translating
//! one line. Port of the job-lifecycle slice of `app/views/review_view.py`.
//!
//! Three scopes: the whole project, one file (both send the
//! `not_translated` lines, plus the drafts when `includeDrafts` is set),
//! and `filter`, the lines the review filters currently select. The
//! filter scope is the only one that reaches an already translated line,
//! which is what makes a bad suggestion fixable in bulk; it never touches
//! a `human_validated` line, however the filter got there.
//!
//! Each translated chunk is persisted as `ai_suggested`, except the units
//! whose source has nothing to translate (pure symbols/punctuation), which
//! the job copies verbatim and which are written `human_validated` since
//! there is nothing to review.

use std::collections::HashSet;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};
use tokio::sync::Mutex;

use crate::app_state::AppState;
use crate::core::review_actions::{self, UnitFilter};
use crate::core::storage::repositories;
use crate::core::translation::job::{self, CancelToken, JobEvent, JobMessage, JobProgress};
use crate::core::translation::providers::base::{
    ProviderError, TranslateBatchResult, TranslationUnitPayload,
};
use crate::core::translation::providers::registry;
use crate::core::validators::is_recognized_language;
use crate::mcp_server::session::ProjectSession;

use super::dto::{ListUnitsArgs, UnitPayload};
use super::CommandError;

const JOB_EVENT_NAME: &str = "translation-job";

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartJobArgs {
    pub provider_id: String,
    /// "project" translates every `not_translated` unit in the project;
    /// "file" limits that to one source file (`source_file`, relative,
    /// as returned by `list_files`); "filter" translates the lines the
    /// review filters in `filter` select, minus the validated ones.
    pub scope: String,
    pub source_file: Option<String>,
    /// Also retranslate (and overwrite) existing drafts in a "project" or
    /// "file" scope. The caller asks the user first when the scope holds
    /// any (`FileEntry.draft`). Ignored by "filter".
    #[serde(default)]
    pub include_drafts: bool,
    /// The review filters, required by scope "filter".
    #[serde(default)]
    pub filter: Option<ListUnitsArgs>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
enum JobEventPayload {
    Progress {
        total: usize,
        done: usize,
        failed: usize,
        running: bool,
        finished: bool,
        error: Option<ProviderError>,
    },
    ChunkPersisted,
    Event {
        message: JobMessage,
    },
}

impl From<&JobProgress> for JobEventPayload {
    fn from(p: &JobProgress) -> Self {
        JobEventPayload::Progress {
            total: p.total,
            done: p.done,
            failed: p.failed,
            running: p.running,
            finished: p.finished,
            error: p.error.clone(),
        }
    }
}

#[tauri::command]
pub async fn start_translation_job(
    app: AppHandle,
    state: State<'_, AppState>,
    args: StartJobArgs,
) -> Result<(), CommandError> {
    if state.job.lock().await.is_some() {
        return Err(CommandError::message("translation.job_running"));
    }

    let (units, symbol_only, source_lang, target_lang, universe_summary, characters) = {
        let guard = state.current.lock().await;
        let session = super::require_session(&guard)?;
        let selected = select_units(session, &args)?;
        let symbol_only: HashSet<String> = selected
            .iter()
            .filter(|u| !job::needs_translation(&u.source_text))
            .map(|u| u.block_id.clone())
            .collect();
        let units: Vec<TranslationUnitPayload> = selected
            .into_iter()
            .map(|u| TranslationUnitPayload {
                block_id: u.block_id,
                source_text: u.source_text,
                character_variable: u.character_variable,
            })
            .collect();
        let universe_summary = repositories::get_project_meta(session.conn(), "universe_summary")
            .map_err(|e| e.to_string())?;
        let characters =
            repositories::get_all_characters(session.conn()).map_err(|e| e.to_string())?;
        (
            units,
            symbol_only,
            session.source_language(),
            session.target_language(),
            universe_summary,
            characters,
        )
    };

    if units.is_empty() {
        return Err(CommandError::message("errors.nothing_to_translate"));
    }

    let mut provider = {
        let mut settings = state.settings.lock().await;
        registry::get(
            &mut settings,
            &args.provider_id,
            universe_summary,
            characters,
        )?
    };

    let cancel = CancelToken::new();
    *state.job.lock().await = Some(cancel.clone());

    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
    let current = state.current.clone();
    let job_slot = state.job.clone();
    let symbol_only = Arc::new(symbol_only);

    tauri::async_runtime::spawn(async move {
        let app_for_events = app.clone();
        let receiver = tokio::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    JobEvent::Chunk(result) => {
                        persist_chunk(&current, &result, &symbol_only).await;
                        let _ =
                            app_for_events.emit(JOB_EVENT_NAME, JobEventPayload::ChunkPersisted);
                    }
                    JobEvent::Progress(progress) | JobEvent::Complete(progress) => {
                        let _ =
                            app_for_events.emit(JOB_EVENT_NAME, JobEventPayload::from(&progress));
                    }
                    JobEvent::Event(message) => {
                        let _ =
                            app_for_events.emit(JOB_EVENT_NAME, JobEventPayload::Event { message });
                    }
                }
            }
        });

        job::run_job(
            &units,
            provider.as_mut(),
            &source_lang,
            &target_lang,
            cancel,
            tx,
        )
        .await;
        let _ = receiver.await;
        *job_slot.lock().await = None;
    });

    Ok(())
}

/// The lines a job scope sends. The two simple scopes read the
/// `not_translated` lines (drafts appended on request); the filter scope
/// takes the lines the filter matches and drops the validated ones, a
/// suggestion never replacing work a human signed off on.
fn select_units(
    session: &ProjectSession,
    args: &StartJobArgs,
) -> Result<Vec<repositories::TranslationUnit>, String> {
    let conn = session.conn();
    let db = |e: rusqlite::Error| e.to_string();
    match args.scope.as_str() {
        "filter" => {
            let filter = args
                .filter
                .as_ref()
                .ok_or_else(|| "filter is required for scope \"filter\".".to_string())?;
            let source_file = session.absolute(&filter.source_file);
            let units = review_actions::filtered_units(
                conn,
                &source_file,
                &UnitFilter {
                    status: filter.status.clone(),
                    search: filter.search.clone(),
                    speaker: filter.speaker.clone(),
                    needs_review: filter.needs_review,
                    errors_only: filter.errors_only,
                },
            )
            .map_err(db)?;
            Ok(units
                .into_iter()
                .filter(|u| u.status != repositories::STATUS_HUMAN_VALIDATED)
                .collect())
        }
        scope @ ("file" | "project") => {
            let source_file = if scope == "file" {
                Some(
                    args.source_file
                        .as_deref()
                        .map(|f| session.absolute(f))
                        .ok_or_else(|| "source_file is required for scope \"file\".".to_string())?,
                )
            } else {
                None
            };
            let mut units = repositories::get_all(
                conn,
                Some(repositories::STATUS_NOT_TRANSLATED),
                source_file.as_deref(),
            )
            .map_err(db)?;
            if args.include_drafts {
                units.extend(
                    repositories::get_all(
                        conn,
                        Some(repositories::STATUS_DRAFT),
                        source_file.as_deref(),
                    )
                    .map_err(db)?,
                );
            }
            Ok(units)
        }
        other => Err(format!("Unknown scope: {other}")),
    }
}

async fn persist_chunk(
    current: &Arc<Mutex<Option<ProjectSession>>>,
    result: &TranslateBatchResult,
    symbol_only: &HashSet<String>,
) {
    let guard = current.lock().await;
    let Some(session) = guard.as_ref() else {
        return;
    };
    let entries = review_actions::chunk_entries(result, symbol_only);
    let _ = repositories::update_translations(session.conn(), &entries);
}

/// What translating one line produced.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UnitTranslation {
    /// The line as stored after the attempt.
    pub unit: UnitPayload,
    /// The provider or the quality gate gave nothing usable for the line;
    /// it is unchanged.
    pub failed: bool,
    /// A job-level error (provider unreachable...), if any.
    pub error: Option<ProviderError>,
    /// What the job had to say along the way (a rejected suggestion with
    /// its reason, a retry), for the status line.
    pub events: Vec<JobMessage>,
}

/// Translate one line with the chosen provider (the row's "Translate"
/// action). Runs the same job as a batch over a single unit, so the line
/// goes through the same quality gate and retries, and is persisted the
/// same way: `ai_suggested` (a `human_validated` line is never replaced,
/// and the call then leaves it unchanged). Whatever the line's status:
/// asking for one line is asking for that line. Resolves when the job
/// ends, which can be long for a cold local model; no lock is held
/// meanwhile.
#[tauri::command]
pub async fn translate_unit(
    state: State<'_, AppState>,
    provider_id: String,
    block_id: String,
) -> Result<UnitTranslation, CommandError> {
    let (payload, source_lang, target_lang, universe_summary, characters) = {
        let guard = state.current.lock().await;
        let session = super::require_session(&guard)?;
        let unit = super::require_unit(session, &block_id)?;
        let target_lang = session.target_language();
        if !is_recognized_language(&target_lang) {
            return Err(CommandError::Message {
                key: "errors.unsupported_target_language",
                params: serde_json::json!({ "language": target_lang }),
            });
        }
        let universe_summary = repositories::get_project_meta(session.conn(), "universe_summary")
            .map_err(|e| e.to_string())?;
        let characters =
            repositories::get_all_characters(session.conn()).map_err(|e| e.to_string())?;
        (
            TranslationUnitPayload {
                block_id: unit.block_id,
                source_text: unit.source_text,
                character_variable: unit.character_variable,
            },
            session.source_language(),
            target_lang,
            universe_summary,
            characters,
        )
    };
    let symbol_only: HashSet<String> = if job::needs_translation(&payload.source_text) {
        HashSet::new()
    } else {
        [payload.block_id.clone()].into()
    };

    let mut provider = {
        let mut settings = state.settings.lock().await;
        registry::get(&mut settings, &provider_id, universe_summary, characters)?
    };

    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
    let current = state.current.clone();
    let collect_events = async {
        let mut messages = Vec::new();
        while let Some(event) = rx.recv().await {
            match event {
                JobEvent::Chunk(result) => persist_chunk(&current, &result, &symbol_only).await,
                JobEvent::Event(message) => messages.push(message),
                JobEvent::Progress(_) | JobEvent::Complete(_) => {}
            }
        }
        messages
    };
    let (progress, events) = tokio::join!(
        job::run_job(
            std::slice::from_ref(&payload),
            provider.as_mut(),
            &source_lang,
            &target_lang,
            CancelToken::new(),
            tx,
        ),
        collect_events
    );

    let guard = state.current.lock().await;
    let session = super::require_session(&guard)?;
    let unit = super::require_unit(session, &block_id)?;
    Ok(UnitTranslation {
        unit: UnitPayload::from_unit(session, &unit),
        failed: progress.failed > 0,
        error: progress.error,
        events,
    })
}

#[tauri::command]
pub async fn cancel_translation_job(state: State<'_, AppState>) -> Result<(), String> {
    if let Some(cancel) = state.job.lock().await.as_ref() {
        cancel.cancel();
    }
    Ok(())
}

#[tauri::command]
pub async fn is_translation_job_running(state: State<'_, AppState>) -> Result<bool, String> {
    Ok(state.job.lock().await.is_some())
}
