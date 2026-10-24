//! Starting, monitoring and cancelling a translation job. Port of the
//! job-lifecycle slice of `app/views/review_view.py`, simplified for a
//! first UI pass: only the "whole project" and "one file" scopes exist
//! (Python's third scope, "the currently filtered selection", and its
//! prompt to include existing drafts, are deferred), and only
//! `not_translated` units are ever sent — a draft is left as a draft
//! until a human edits or clears it.
//!
//! Each translated chunk is persisted as `ai_suggested`, including the
//! units `core::translation::job` decided needed no translation at all
//! (pure symbols/punctuation): Python writes those straight to
//! `human_validated` since nothing there needs a second look, a
//! distinction `JobEvent::Chunk` does not carry and this first pass does
//! not attempt to recover — one extra validate click for a line that
//! never had anything to translate.

use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};
use tokio::sync::Mutex;

use crate::app_state::AppState;
use crate::core::storage::repositories;
use crate::core::translation::job::{self, CancelToken, JobEvent, JobProgress};
use crate::core::translation::providers::base::{TranslateBatchResult, TranslationUnitPayload};
use crate::core::translation::providers::registry;
use crate::mcp_server::session::ProjectSession;

const JOB_EVENT_NAME: &str = "translation-job";

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartJobArgs {
    pub provider_id: String,
    /// "project" translates every `not_translated` unit in the project;
    /// "file" limits that to one source file (`source_file`, relative,
    /// as returned by `list_files`).
    pub scope: String,
    pub source_file: Option<String>,
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
        error: Option<String>,
    },
    ChunkPersisted,
    Event {
        message: String,
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
) -> Result<(), String> {
    if state.job.lock().await.is_some() {
        return Err("A translation job is already running.".to_string());
    }

    let (units, source_lang, target_lang, universe_summary, characters) = {
        let guard = state.current.lock().await;
        let session = super::require_session(&guard)?;
        let source_file = match args.scope.as_str() {
            "file" => Some(
                args.source_file
                    .as_deref()
                    .map(|f| session.absolute(f))
                    .ok_or_else(|| "source_file is required for scope \"file\".".to_string())?,
            ),
            "project" => None,
            other => return Err(format!("Unknown scope: {other}")),
        };
        let units: Vec<TranslationUnitPayload> = repositories::get_all(
            session.conn(),
            Some(repositories::STATUS_NOT_TRANSLATED),
            source_file.as_deref(),
        )
        .map_err(|e| e.to_string())?
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
            session.source_language(),
            session.target_language(),
            universe_summary,
            characters,
        )
    };

    if units.is_empty() {
        return Err("Nothing to translate in this scope.".to_string());
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

    tauri::async_runtime::spawn(async move {
        let app_for_events = app.clone();
        let receiver = tokio::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    JobEvent::Chunk(result) => {
                        persist_chunk(&current, &result).await;
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

async fn persist_chunk(
    current: &Arc<Mutex<Option<ProjectSession>>>,
    result: &TranslateBatchResult,
) {
    let guard = current.lock().await;
    let Some(session) = guard.as_ref() else {
        return;
    };
    let entries: Vec<(String, String, String)> = result
        .translations
        .iter()
        .map(|t| {
            (
                t.block_id.clone(),
                t.translated_text.clone(),
                "ai_suggested".to_string(),
            )
        })
        .collect();
    let _ = repositories::update_translations(session.conn(), &entries);
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
