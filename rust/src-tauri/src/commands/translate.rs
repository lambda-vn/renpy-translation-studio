//! Starting, monitoring and cancelling a translation job, and translating
//! one line.
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
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};
use tokio::sync::Mutex;

use crate::app_state::AppState;
use crate::core::project_session::ProjectSession;
use crate::core::review_actions::{self, JobScope};
use crate::core::storage::repositories;
use crate::core::translation::job::{self, CancelToken, JobEvent, JobMessage, JobProgress};
use crate::core::translation::providers::base::{
    ProviderError, TranslateBatchResult, TranslationProvider, TranslationUnitPayload,
};
use crate::core::translation::providers::registry;
use crate::core::validators::is_recognized_language;

use super::dto::{ListUnitsArgs, UnitPayload};
use super::CommandError;

/// Name of the event carrying the job's progress to the frontend.
const JOB_EVENT_NAME: &str = "translation-job";

/// Arguments of `start_translation_job`.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartJobArgs {
    /// Identifier of the provider that translates.
    pub provider_id: String,
    /// `Project` translates every `not_translated` unit in the project;
    /// `File` limits that to one source file (`source_file`, relative,
    /// as returned by `list_files`); `Filter` translates the lines the
    /// review filters in `filter` select, minus the validated ones.
    pub scope: JobScope,
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
    /// The job's counters, sent when they change and at the end.
    Progress {
        total: usize,
        done: usize,
        failed: usize,
        running: bool,
        finished: bool,
        error: Option<ProviderError>,
    },
    /// A translated chunk was stored; the review screen may refresh.
    ChunkPersisted,
    /// A message from the job for the status line.
    Event { message: JobMessage },
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

/// Everything a job needs, read once from the open project and the
/// settings. Shared by the batch job and the one-line translation so the
/// two cannot drift on what they check.
struct JobContext {
    project: PathBuf,
    units: Vec<TranslationUnitPayload>,
    symbol_only: HashSet<String>,
    source_lang: String,
    target_lang: String,
    provider: Box<dyn TranslationProvider>,
}

impl JobContext {
    /// Read the units `select` picks from the open project, then build the
    /// provider. The `current` lock is released before `settings` is taken.
    ///
    /// Refuses a target language the app does not recognise, since the
    /// provider could not be asked for it.
    async fn load(
        state: &AppState,
        provider_id: &str,
        select: impl FnOnce(&ProjectSession) -> Result<Vec<repositories::TranslationUnit>, CommandError>,
    ) -> Result<JobContext, CommandError> {
        let (project, units, symbol_only, source_lang, target_lang, universe_summary, characters) = {
            let guard = state.current.lock().await;
            let session = super::require_session(&guard)?;
            let selected = select(session)?;
            let target_lang = session.target_language();
            if !is_recognized_language(&target_lang) {
                return Err(CommandError::Message {
                    key: "errors.unsupported_target_language",
                    params: serde_json::json!({ "language": target_lang }),
                });
            }
            let (units, symbol_only) = to_payloads(selected);
            let universe_summary =
                repositories::get_project_meta(session.conn(), repositories::UNIVERSE_SUMMARY_KEY)
                    .map_err(|e| e.to_string())?;
            let characters =
                repositories::get_all_characters(session.conn()).map_err(|e| e.to_string())?;
            (
                session.path.clone(),
                units,
                symbol_only,
                session.source_language(),
                target_lang,
                universe_summary,
                characters,
            )
        };
        let provider = {
            let mut settings = state.settings.lock().await;
            registry::get(&mut settings, provider_id, universe_summary, characters)?
        };
        Ok(JobContext {
            project,
            units,
            symbol_only,
            source_lang,
            target_lang,
            provider,
        })
    }
}

/// The payloads a provider receives, and the block ids whose source has
/// nothing to translate (the job copies those verbatim).
fn to_payloads(
    selected: Vec<repositories::TranslationUnit>,
) -> (Vec<TranslationUnitPayload>, HashSet<String>) {
    let symbol_only = selected
        .iter()
        .filter(|u| !job::needs_translation(&u.source_text))
        .map(|u| u.block_id.clone())
        .collect();
    let units = selected
        .into_iter()
        .map(|u| TranslationUnitPayload {
            block_id: u.block_id,
            source_text: u.source_text,
            character_variable: u.character_variable,
        })
        .collect();
    (units, symbol_only)
}

/// Start translating the lines of `args.scope` in the background and
/// return once the job is running; progress comes as `translation-job`
/// events.
///
/// # Errors
///
/// Fails with `translation.job_running` when a job already runs, when no
/// project is open, when its target language is not recognised
/// (`errors.unsupported_target_language`), when the scope selects nothing
/// (`errors.nothing_to_translate`) or cannot be resolved, or when the
/// provider cannot be built from the settings.
#[tauri::command]
pub async fn start_translation_job(
    app: AppHandle,
    state: State<'_, AppState>,
    args: StartJobArgs,
) -> Result<(), CommandError> {
    let cancel = CancelToken::new();
    let slot = JobSlot::acquire(&state.job, cancel.clone()).await?;

    let prepared = JobContext::load(&state, &args.provider_id, |session| {
        let selected = select_for_job(session, &args)?;
        if selected.is_empty() {
            return Err(CommandError::message("errors.nothing_to_translate"));
        }
        Ok(selected)
    })
    .await;
    let JobContext {
        project,
        units,
        symbol_only,
        source_lang,
        target_lang,
        mut provider,
    } = match prepared {
        Ok(ready) => ready,
        Err(e) => {
            slot.release().await;
            return Err(e);
        }
    };

    let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
    let current = state.current.clone();
    let stop = cancel.clone();

    tauri::async_runtime::spawn(async move {
        let receiver = spawn_event_pump(app, rx, current, project, Arc::new(symbol_only), stop);

        // The job runs in its own task so that a panic in it or in a
        // provider ends up in the join result instead of skipping the
        // release of the job slot below.
        let worker = tokio::spawn(async move {
            job::run_job(
                &units,
                provider.as_mut(),
                &source_lang,
                &target_lang,
                cancel,
                tx,
            )
            .await;
        });
        if let Err(error) = worker.await {
            log::error!("the translation job stopped abnormally: {error}");
        }
        let _ = receiver.await;
        slot.release().await;
    });

    Ok(())
}

/// Persist each translated chunk and forward the job's events to the UI.
/// Cancels the job through `stop` when the project it runs on is gone.
fn spawn_event_pump(
    app: AppHandle,
    mut rx: tokio::sync::mpsc::UnboundedReceiver<JobEvent>,
    current: Arc<Mutex<Option<ProjectSession>>>,
    project: PathBuf,
    symbol_only: Arc<HashSet<String>>,
    stop: CancelToken,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                JobEvent::Chunk(result) => {
                    match persist_chunk(&current, &project, &result, &symbol_only).await {
                        Persisted::Stored => {
                            let _ = app.emit(JOB_EVENT_NAME, JobEventPayload::ChunkPersisted);
                        }
                        Persisted::Failed => {}
                        Persisted::ProjectGone => stop.cancel(),
                    }
                }
                JobEvent::Progress(progress) | JobEvent::Complete(progress) => {
                    let _ = app.emit(JOB_EVENT_NAME, JobEventPayload::from(&progress));
                }
                JobEvent::Event(message) => {
                    let _ = app.emit(JOB_EVENT_NAME, JobEventPayload::Event { message });
                }
            }
        }
    })
}

/// What became of a translated chunk.
enum Persisted {
    /// The chunk is in the database.
    Stored,
    /// The database write failed; the job goes on.
    Failed,
    /// The project the job was started on is no longer the open one.
    ProjectGone,
}

/// Write a translated chunk to the database of `project`, the project the
/// job was started on.
///
/// The open project is read again for every chunk, and nothing stops the
/// user from opening another one while a job runs. Block ids are hashes
/// of the dialogue, so two versions of a game share most of them: writing
/// into whatever is open would land one game's suggestions on the other.
async fn persist_chunk(
    current: &Arc<Mutex<Option<ProjectSession>>>,
    project: &Path,
    result: &TranslateBatchResult,
    symbol_only: &HashSet<String>,
) -> Persisted {
    let guard = current.lock().await;
    let Some(session) = guard.as_ref().filter(|session| session.path == project) else {
        log::warn!("project closed during a translation job, dropping its chunk");
        return Persisted::ProjectGone;
    };
    let entries = review_actions::chunk_entries(result, symbol_only);
    match repositories::update_translations(session.conn(), &entries) {
        Ok(_) => Persisted::Stored,
        Err(e) => {
            log::error!("could not persist a chunk of {} units: {e}", entries.len());
            Persisted::Failed
        }
    }
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
///
/// A failure of the provider or of the quality gate is not an error: it
/// is reported in the returned `failed` and `error`.
///
/// # Errors
///
/// Fails when no project is open, when its target language is not
/// recognised, when `block_id` is unknown, or when the provider cannot be
/// built from the settings.
#[tauri::command]
pub async fn translate_unit(
    state: State<'_, AppState>,
    provider_id: String,
    block_id: String,
) -> Result<UnitTranslation, CommandError> {
    let JobContext {
        project,
        units,
        symbol_only,
        source_lang,
        target_lang,
        mut provider,
    } = JobContext::load(&state, &provider_id, |session| {
        Ok(vec![super::require_unit(session, &block_id)?])
    })
    .await?;

    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
    let current = state.current.clone();
    let collect_events = async {
        let mut messages = Vec::new();
        while let Some(event) = rx.recv().await {
            match event {
                JobEvent::Chunk(result) => {
                    persist_chunk(&current, &project, &result, &symbol_only).await;
                }
                JobEvent::Event(message) => messages.push(message),
                JobEvent::Progress(_) | JobEvent::Complete(_) => {}
            }
        }
        messages
    };
    let (progress, events) = tokio::join!(
        job::run_job(
            &units,
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

/// Ask the running job, if any, to stop.
///
/// # Errors
///
/// Never fails; the `Result` is the command signature.
#[tauri::command]
pub async fn cancel_translation_job(state: State<'_, AppState>) -> Result<(), String> {
    if let Some(cancel) = state.job.lock().await.as_ref() {
        cancel.cancel();
    }
    Ok(())
}

/// Whether a translation job holds the job slot.
///
/// # Errors
///
/// Never fails; the `Result` is the command signature.
#[tauri::command]
pub async fn is_translation_job_running(state: State<'_, AppState>) -> Result<bool, String> {
    Ok(state.job.lock().await.is_some())
}

/// The job slot of [`AppState`], held from the reservation until
/// [`JobSlot::release`].
///
/// There is no `Drop`: releasing needs to await a tokio mutex, which a
/// destructor cannot do. Each path out of a job therefore ends in an
/// explicit `release`.
struct JobSlot {
    slot: Arc<Mutex<Option<CancelToken>>>,
}

impl JobSlot {
    /// Reserve the slot for the job `cancel` stops.
    ///
    /// # Errors
    ///
    /// Returns `translation.job_running` when a job already holds it.
    async fn acquire(
        slot: &Arc<Mutex<Option<CancelToken>>>,
        cancel: CancelToken,
    ) -> Result<JobSlot, CommandError> {
        let mut held = slot.lock().await;
        if held.is_some() {
            return Err(CommandError::message("translation.job_running"));
        }
        *held = Some(cancel);
        Ok(JobSlot { slot: slot.clone() })
    }

    /// Free the slot for the next job.
    async fn release(self) {
        *self.slot.lock().await = None;
    }
}

/// Resolve the paths of `args` against the open project and pick the
/// lines of its scope.
fn select_for_job(
    session: &ProjectSession,
    args: &StartJobArgs,
) -> Result<Vec<repositories::TranslationUnit>, String> {
    let source_file = args.source_file.as_deref().map(|f| session.absolute(f));
    let filter = args
        .filter
        .as_ref()
        .map(|filter| (session.absolute(&filter.source_file), filter.unit_filter()));
    review_actions::select_units(
        session.conn(),
        args.scope,
        source_file.as_deref(),
        args.include_drafts,
        filter
            .as_ref()
            .map(|(file, filter)| (file.as_str(), filter)),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::core::project_session;
    use crate::core::storage::database::Database;
    use crate::core::storage::repositories::NewUnit;
    use crate::core::translation::providers::base::TranslatedUnit;

    fn extracted_project(name: &str) -> std::path::PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let project = std::env::temp_dir().join(format!("rts-translate-test-{name}-{nanos}"));
        let db_path = Database::path_for(&project);
        std::fs::create_dir_all(db_path.parent().unwrap()).unwrap();
        let db = Database::open(&db_path).unwrap();
        repositories::bulk_insert(
            db.conn(),
            &[NewUnit {
                block_id: "start_a1",
                source_file: "game/script.rpy",
                source_line: 1,
                character_variable: None,
                source_text: "Hello.",
            }],
        )
        .unwrap();
        project
    }

    #[tokio::test]
    async fn a_chunk_is_never_written_into_another_project() {
        let started_on = extracted_project("a");
        let opened = extracted_project("b");
        let current = Arc::new(Mutex::new(Some(
            project_session::open_project(&opened).unwrap(),
        )));
        let result = TranslateBatchResult {
            translations: vec![TranslatedUnit {
                block_id: "start_a1".into(),
                translated_text: "Bonjour.".into(),
            }],
            ..Default::default()
        };

        let outcome = persist_chunk(&current, &started_on, &result, &HashSet::new()).await;
        assert!(matches!(outcome, Persisted::ProjectGone));
        let guard = current.lock().await;
        let units =
            repositories::get_many(guard.as_ref().unwrap().conn(), &["start_a1".into()]).unwrap();
        assert_eq!(units[0].translated_text, "");
        drop(guard);

        let outcome = persist_chunk(&current, &opened, &result, &HashSet::new()).await;
        assert!(matches!(outcome, Persisted::Stored));
    }

    #[test]
    fn symbol_only_lines_are_flagged_and_payloads_keep_order() {
        let unit = |block_id: &str, source_text: &str| repositories::TranslationUnit {
            id: 0,
            block_id: block_id.into(),
            source_file: "game/script.rpy".into(),
            source_line: 1,
            character_variable: None,
            source_text: source_text.into(),
            translated_text: String::new(),
            status: repositories::STATUS_NOT_TRANSLATED.into(),
            needs_review: false,
            note: None,
        };

        let (payloads, symbol_only) = to_payloads(vec![unit("a", "..."), unit("b", "Hello.")]);

        let ids: Vec<&str> = payloads.iter().map(|p| p.block_id.as_str()).collect();
        assert_eq!(ids, ["a", "b"]);
        assert_eq!(symbol_only, HashSet::from(["a".to_string()]));
    }
}
