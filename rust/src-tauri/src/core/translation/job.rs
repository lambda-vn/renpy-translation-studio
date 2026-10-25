//! Runs a translation batch to completion, in chunks, with retries.
//! Port of `core/translation/job.py`.
//!
//! Python's `TranslationJob` starts a background `threading.Thread` and
//! calls synchronous callbacks (`on_chunk`, `on_progress`, `on_complete`,
//! `on_event`) from it. [`run_job`] is `async` instead and pushes one
//! [`JobEvent`] per callback onto an unbounded channel — the caller
//! decides whether to `tokio::spawn` it, await it inline, or forward
//! events to a Tauri window; nothing here knows about a UI.
//!
//! **Not ported**: `on_batch_start` and the fine-grained `is_cancelled`
//! Python threads into every provider's own internal sub-batching, so a
//! cancellation there takes effect after the request currently in
//! flight rather than after the whole job chunk. `translation::providers`
//! doesn't carry those hooks (see its `base` module docs), so
//! cancellation here is checked at job-chunk boundaries
//! ([`CHUNK_SIZE`], and the smaller retry chunk sizes) — coarser than
//! Python, but bounded: a job chunk is at most 50 units, and a slow
//! provider (Ollama) splits that into at most a handful of its own
//! requests internally. Revisit if real use shows this matters.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use tokio::sync::mpsc::UnboundedSender;

use super::providers::base::{
    ProviderError, TranslateBatchResult, TranslatedUnit, TranslationProvider,
    TranslationUnitPayload,
};
use super::quality::{check as quality_check, strip_tags, QualityIssue};

const CHUNK_SIZE: usize = 50;
const BLOCKING_QUALITY_KINDS: [&str; 2] = ["missing_var", "unexpected_html"];
const RETRY_CHUNK_SIZES: [usize; 2] = [8, 1];

/// Cooperative cancellation flag, cheap to clone and share with the
/// caller that started the job.
#[derive(Clone, Default)]
pub struct CancelToken(Arc<AtomicBool>);

impl CancelToken {
    pub fn new() -> Self {
        Self(Arc::new(AtomicBool::new(false)))
    }

    /// Request cancellation. Already-translated units are preserved —
    /// the job finishes its current chunk and stops before the next.
    pub fn cancel(&self) {
        self.0.store(true, Ordering::SeqCst);
    }

    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
}

/// Snapshot of a translation job's progress.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct JobProgress {
    pub total: usize,
    pub done: usize,
    pub failed: usize,
    pub running: bool,
    pub finished: bool,
    pub error: Option<ProviderError>,
}

/// One occurrence of what Python's four callbacks would have reported.
#[derive(Debug, Clone)]
pub enum JobEvent {
    /// A chunk's translations/failures, already spread to every unit
    /// that shared a source text — persist these as they arrive.
    Chunk(TranslateBatchResult),
    Progress(JobProgress),
    /// The job has stopped, successfully or not.
    Complete(JobProgress),
    /// A notable event: a rejected suggestion (with reason), units
    /// skipped as untranslatable, a retry starting.
    Event(JobMessage),
}

/// What a job has to say along the way, as a message key and its
/// parameters rather than a sentence, so the interface can show it in
/// its own language. [`Display`](std::fmt::Display) renders the English
/// text, for logs and tests.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JobMessage {
    RejectedIdentical {
        block_id: String,
    },
    Rejected {
        block_id: String,
        issues: Vec<QualityIssue>,
    },
    AcceptedWithWarning {
        block_id: String,
        issues: Vec<QualityIssue>,
    },
    Retrying {
        n: usize,
    },
    SharedSource {
        n: usize,
    },
    NothingToTranslate {
        n: usize,
    },
    ProviderFailed {
        n: usize,
    },
}

impl JobMessage {
    /// The `job_events.*` catalog key of this message.
    pub fn key(&self) -> &'static str {
        match self {
            Self::RejectedIdentical { .. } => "job_events.translation_rejected_identical",
            Self::Rejected { .. } => "job_events.translation_rejected_reason",
            Self::AcceptedWithWarning { .. } => "job_events.translation_accepted_with_warning",
            Self::Retrying { .. } => "job_events.retry_in_progress",
            Self::SharedSource { .. } => "job_events.duplicates_shared",
            Self::NothingToTranslate { .. } => "job_events.skipped_copied",
            Self::ProviderFailed { .. } => "job_events.provider_failed",
        }
    }

    /// The placeholders of the catalog string. `issues` is a list of
    /// `{kind, detail}` the interface turns into the `reason` text.
    pub fn params(&self) -> serde_json::Value {
        use serde_json::json;
        match self {
            Self::RejectedIdentical { block_id } => json!({ "block_id": block_id }),
            Self::Rejected { block_id, issues }
            | Self::AcceptedWithWarning { block_id, issues } => {
                let issues: Vec<_> = issues
                    .iter()
                    .map(|i| json!({ "kind": i.kind, "detail": i.detail }))
                    .collect();
                json!({ "block_id": block_id, "issues": issues })
            }
            Self::Retrying { n }
            | Self::SharedSource { n }
            | Self::NothingToTranslate { n }
            | Self::ProviderFailed { n } => json!({ "n": n }),
        }
    }
}

fn join_details(issues: &[QualityIssue]) -> String {
    issues
        .iter()
        .map(|i| i.detail.as_str())
        .collect::<Vec<_>>()
        .join("; ")
}

impl std::fmt::Display for JobMessage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::RejectedIdentical { block_id } => write!(
                f,
                "Rejected the AI suggestion for {block_id}: identical to the source text."
            ),
            Self::Rejected { block_id, issues } => write!(
                f,
                "Rejected the AI suggestion for {block_id}: {}",
                join_details(issues)
            ),
            Self::AcceptedWithWarning { block_id, issues } => write!(
                f,
                "Accepted the AI suggestion for {block_id} with a warning: {}",
                join_details(issues)
            ),
            Self::Retrying { n } => write!(f, "Retrying {n} unit(s)..."),
            Self::SharedSource { n } => {
                write!(f, "{n} unit(s) share a source text and were not sent.")
            }
            Self::NothingToTranslate { n } => write!(f, "{n} unit(s) had nothing to translate."),
            Self::ProviderFailed { n } => write!(f, "The provider failed on {n} unit(s)."),
        }
    }
}

impl serde::Serialize for JobMessage {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut state = serializer.serialize_struct("JobMessage", 2)?;
        state.serialize_field("key", self.key())?;
        state.serialize_field("params", &self.params())?;
        state.end()
    }
}

fn emit(tx: &UnboundedSender<JobEvent>, event: JobEvent) {
    if let JobEvent::Event(message) = &event {
        match message {
            JobMessage::RejectedIdentical { .. } | JobMessage::Rejected { .. } => {
                log::warn!("{message}");
            }
            _ => log::info!("{message}"),
        }
    }
    // A closed receiver (caller dropped it) means nobody is listening
    // any more, not a reason to stop translating — the job still
    // reports through progress.done/failed and its final Complete.
    let _ = tx.send(event);
}

/// `false` if `source_text` has no letters and translating it is
/// pointless.
///
/// Ren'Py text tags (`{w=0.5}`, `{i}`, `{cps=20}`, ...) are stripped
/// first, since their tag names are letters but never player-visible
/// text — a tag-wrapped ellipsis like `"...{w=0.5}"` has nothing to
/// translate either.
pub fn needs_translation(source_text: &str) -> bool {
    strip_tags(source_text).chars().any(char::is_alphabetic)
}

/// Keep one unit per distinct source text, and note who shares it.
///
/// A game repeats itself, and sending each occurrence separately is a
/// request (and, on a paid provider, a bill) for the same question
/// asked over and over — worse, one that can come back with answers
/// that disagree with each other. The first occurrence is the one
/// sent; its answer is handed to every unit waiting on it.
///
/// Returns `(units to actually send, block_ids waiting on each one)`. A
/// text occurring once has an empty follower list.
pub fn group_by_source(
    units: &[TranslationUnitPayload],
) -> (Vec<TranslationUnitPayload>, HashMap<String, Vec<String>>) {
    let mut representatives = Vec::new();
    let mut followers: HashMap<String, Vec<String>> = HashMap::new();
    let mut leader_of: HashMap<&str, &str> = HashMap::new();

    for unit in units {
        match leader_of.get(unit.source_text.as_str()) {
            None => {
                leader_of.insert(&unit.source_text, &unit.block_id);
                followers.insert(unit.block_id.clone(), Vec::new());
                representatives.push(unit.clone());
            }
            Some(&leader) => {
                followers
                    .get_mut(leader)
                    .unwrap()
                    .push(unit.block_id.clone());
            }
        }
    }
    (representatives, followers)
}

/// Hand each answer (or failure) to every unit that was waiting on it.
pub fn spread_to_followers(
    result: TranslateBatchResult,
    followers: &HashMap<String, Vec<String>>,
) -> TranslateBatchResult {
    let mut translations = Vec::new();
    for t in &result.translations {
        translations.push(t.clone());
        if let Some(ids) = followers.get(&t.block_id) {
            translations.extend(ids.iter().map(|id| TranslatedUnit {
                block_id: id.clone(),
                translated_text: t.translated_text.clone(),
            }));
        }
    }
    let mut failed_ids = Vec::new();
    for id in &result.failed_ids {
        failed_ids.push(id.clone());
        if let Some(ids) = followers.get(id) {
            failed_ids.extend(ids.iter().cloned());
        }
    }
    TranslateBatchResult {
        translations,
        failed_ids,
    }
}

/// Reject only the AI suggestions that are actually implausible.
///
/// A provider (especially a small local LLM) can return a translation
/// that has nothing to do with its source — a missing interpolated
/// variable would break the game, and unexpected HTML markup is a
/// reliable sign the model hallucinated instead of translating
/// ([`BLOCKING_QUALITY_KINDS`]). Those are rejected outright, as is a
/// translation that's simply the source text echoed back unchanged.
///
/// Everything else `quality::check()` flags is real but cosmetic —
/// small models reliably drop tags they don't recognize even when told
/// to keep them, and length ratios swing wildly on short strings.
/// Rejecting the whole suggestion over that would throw away
/// translations that are largely correct and quick for a human to
/// touch up, so these are kept, with a warning event instead.
///
/// Only the units of `chunk` are answered, each once: a small model
/// pads its output by repeating an entry or inventing an identifier, and
/// counting those would push the progress past the total, while writing
/// a stray one would put text on a line nobody sent.
///
/// Returns the result with implausible translations moved from
/// `translations` to `failed_ids`, plus one message per rejection or
/// warning.
fn verify_quality(
    chunk: &[TranslationUnitPayload],
    result: TranslateBatchResult,
) -> (TranslateBatchResult, Vec<JobMessage>) {
    let source_by_id: HashMap<&str, &str> = chunk
        .iter()
        .map(|u| (u.block_id.as_str(), u.source_text.as_str()))
        .collect();
    let mut verified = Vec::new();
    let mut rejected = Vec::new();
    let mut events = Vec::new();
    let mut answered: HashSet<String> = HashSet::new();

    for translation in result.translations {
        let Some(&source) = source_by_id.get(translation.block_id.as_str()) else {
            continue;
        };
        if !answered.insert(translation.block_id.clone()) {
            continue;
        }

        if !source.is_empty() && translation.translated_text.trim() == source.trim() {
            events.push(JobMessage::RejectedIdentical {
                block_id: translation.block_id.clone(),
            });
            rejected.push(translation.block_id);
            continue;
        }

        let issues = quality_check(source, &translation.translated_text);
        let (blocking, warnings): (Vec<QualityIssue>, Vec<QualityIssue>) = issues
            .into_iter()
            .partition(|i| BLOCKING_QUALITY_KINDS.contains(&i.kind));
        if !blocking.is_empty() {
            events.push(JobMessage::Rejected {
                block_id: translation.block_id.clone(),
                issues: blocking,
            });
            rejected.push(translation.block_id);
            continue;
        }

        if !warnings.is_empty() {
            events.push(JobMessage::AcceptedWithWarning {
                block_id: translation.block_id.clone(),
                issues: warnings,
            });
        }
        verified.push(translation);
    }

    let mut failed_ids: Vec<String> = result
        .failed_ids
        .into_iter()
        .filter(|id| source_by_id.contains_key(id.as_str()) && answered.insert(id.clone()))
        .collect();
    failed_ids.extend(rejected);
    (
        TranslateBatchResult {
            translations: verified,
            failed_ids,
        },
        events,
    )
}

/// Retry failed units in progressively smaller chunks
/// ([`RETRY_CHUNK_SIZES`]), so the provider has fewer units to juggle at
/// once. A unit that succeeds moves from `progress.failed` to
/// `progress.done`; one still failing after the last pass stays failed.
///
/// What is retried is the unit that was actually sent, never the ones
/// waiting on its answer — retrying those would mean sending the same
/// text again, which `group_by_source` exists to avoid.
#[allow(clippy::too_many_arguments)]
async fn retry_failed_units(
    failed_ids: Vec<String>,
    units_by_id: &HashMap<String, TranslationUnitPayload>,
    followers: &HashMap<String, Vec<String>>,
    provider: &mut dyn TranslationProvider,
    source_lang: &str,
    target_lang: &str,
    cancel: &CancelToken,
    tx: &UnboundedSender<JobEvent>,
    progress: &mut JobProgress,
) {
    let mut remaining = failed_ids;

    for &chunk_size in &RETRY_CHUNK_SIZES {
        if remaining.is_empty() || cancel.is_cancelled() {
            break;
        }
        emit(
            tx,
            JobEvent::Event(JobMessage::Retrying { n: remaining.len() }),
        );

        let retry_units: Vec<TranslationUnitPayload> =
            remaining.iter().map(|id| units_by_id[id].clone()).collect();
        remaining = Vec::new();

        for chunk in retry_units.chunks(chunk_size) {
            if cancel.is_cancelled() {
                break;
            }
            let result = match provider
                .translate_batch(chunk, source_lang, target_lang)
                .await
            {
                Ok(result) => result,
                Err(err) => {
                    log::warn!("Retry of {} unit(s) failed: {err}", chunk.len());
                    TranslateBatchResult {
                        translations: Vec::new(),
                        failed_ids: chunk.iter().map(|u| u.block_id.clone()).collect(),
                    }
                }
            };
            let (result, events) = verify_quality(chunk, result);
            for event in events {
                emit(tx, JobEvent::Event(event));
            }
            let spread = spread_to_followers(result, followers);
            let recovered = spread.translations.len();
            progress.done += recovered;
            progress.failed -= recovered;
            remaining.extend(spread.failed_ids.iter().cloned());
            emit(tx, JobEvent::Chunk(spread));
            emit(tx, JobEvent::Progress(progress.clone()));
        }
    }
}

/// Translate `units` to completion: skip what needs no translation,
/// deduplicate by source text, send the rest in chunks of
/// [`CHUNK_SIZE`], verify quality, retry what failed, and report
/// throughout via `tx`. Returns the final [`JobProgress`] (also the
/// last thing sent through `tx`, as [`JobEvent::Complete`]).
pub async fn run_job(
    units: &[TranslationUnitPayload],
    provider: &mut dyn TranslationProvider,
    source_lang: &str,
    target_lang: &str,
    cancel: CancelToken,
    tx: UnboundedSender<JobEvent>,
) -> JobProgress {
    log::info!(
        "Starting translation job: provider={} units={} {source_lang}->{target_lang}",
        provider.id(),
        units.len()
    );
    let mut progress = JobProgress {
        total: units.len(),
        running: true,
        ..Default::default()
    };

    let (skipped, translatable_units): (Vec<_>, Vec<_>) = units
        .iter()
        .cloned()
        .partition(|u| !needs_translation(&u.source_text));
    let (translatable, followers) = group_by_source(&translatable_units);
    let units_by_id: HashMap<String, TranslationUnitPayload> = translatable
        .iter()
        .map(|u| (u.block_id.clone(), u.clone()))
        .collect();

    let shared: usize = followers.values().map(Vec::len).sum();
    if shared > 0 {
        emit(&tx, JobEvent::Event(JobMessage::SharedSource { n: shared }));
    }

    if !skipped.is_empty() {
        let spread = TranslateBatchResult {
            translations: skipped
                .iter()
                .map(|u| TranslatedUnit {
                    block_id: u.block_id.clone(),
                    translated_text: u.source_text.clone(),
                })
                .collect(),
            failed_ids: Vec::new(),
        };
        progress.done += skipped.len();
        emit(&tx, JobEvent::Chunk(spread));
        emit(
            &tx,
            JobEvent::Event(JobMessage::NothingToTranslate { n: skipped.len() }),
        );
        emit(&tx, JobEvent::Progress(progress.clone()));
    }

    let mut failed_ids: Vec<String> = Vec::new();
    let mut provider_error: Option<ProviderError> = None;

    'main: for chunk in translatable.chunks(CHUNK_SIZE) {
        if cancel.is_cancelled() {
            break;
        }
        let result = match provider
            .translate_batch(chunk, source_lang, target_lang)
            .await
        {
            Ok(result) => result,
            Err(err) => {
                log::warn!("Translation job stopped: {err}");
                provider_error = Some(err);
                break 'main;
            }
        };
        log::debug!(
            "Chunk of {} unit(s): {} translated, {} failed by the provider",
            chunk.len(),
            result.translations.len(),
            result.failed_ids.len()
        );
        let provider_failed = result.failed_ids.len();
        let (result, events) = verify_quality(chunk, result);
        if provider_failed > 0 {
            emit(
                &tx,
                JobEvent::Event(JobMessage::ProviderFailed { n: provider_failed }),
            );
        }
        for event in events {
            emit(&tx, JobEvent::Event(event));
        }
        let spread = spread_to_followers(result, &followers);
        progress.done += spread.translations.len();
        progress.failed += spread.failed_ids.len();
        failed_ids.extend(spread.failed_ids.iter().cloned());
        emit(&tx, JobEvent::Chunk(spread));
        emit(&tx, JobEvent::Progress(progress.clone()));
    }

    if provider_error.is_some() {
        progress.error = provider_error;
    } else if !failed_ids.is_empty() && !cancel.is_cancelled() {
        retry_failed_units(
            failed_ids,
            &units_by_id,
            &followers,
            provider,
            source_lang,
            target_lang,
            &cancel,
            &tx,
            &mut progress,
        )
        .await;
    }

    progress.running = false;
    progress.finished = true;
    log::info!(
        "Translation job finished: done={} failed={} cancelled={}",
        progress.done,
        progress.failed,
        cancel.is_cancelled()
    );
    emit(&tx, JobEvent::Complete(progress.clone()));
    progress
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::sync::mpsc::UnboundedReceiver;

    fn unit(block_id: &str, text: &str) -> TranslationUnitPayload {
        TranslationUnitPayload {
            block_id: block_id.to_string(),
            source_text: text.to_string(),
            character_variable: None,
        }
    }

    fn drain(rx: &mut UnboundedReceiver<JobEvent>) -> Vec<JobEvent> {
        let mut events = Vec::new();
        while let Ok(event) = rx.try_recv() {
            events.push(event);
        }
        events
    }

    // A scripted provider: each call consumes the next queued response,
    // so a test can simulate "fails once, succeeds on retry" without a
    // real network.
    struct ScriptedProvider {
        responses: std::collections::VecDeque<Result<TranslateBatchResult, ProviderError>>,
        calls: Vec<Vec<String>>,
    }

    impl ScriptedProvider {
        fn new(responses: Vec<Result<TranslateBatchResult, ProviderError>>) -> Self {
            Self {
                responses: responses.into(),
                calls: Vec::new(),
            }
        }
    }

    #[async_trait::async_trait]
    impl TranslationProvider for ScriptedProvider {
        fn id(&self) -> &'static str {
            "scripted"
        }

        async fn translate_batch(
            &mut self,
            units: &[TranslationUnitPayload],
            _source_lang: &str,
            _target_lang: &str,
        ) -> Result<TranslateBatchResult, ProviderError> {
            self.calls
                .push(units.iter().map(|u| u.block_id.clone()).collect());
            self.responses
                .pop_front()
                .unwrap_or_else(|| Ok(TranslateBatchResult::default()))
        }
    }

    fn ok(pairs: &[(&str, &str)]) -> Result<TranslateBatchResult, ProviderError> {
        Ok(TranslateBatchResult {
            translations: pairs
                .iter()
                .map(|(id, text)| TranslatedUnit {
                    block_id: id.to_string(),
                    translated_text: text.to_string(),
                })
                .collect(),
            failed_ids: Vec::new(),
        })
    }

    #[test]
    fn needs_translation_ignores_tag_only_text() {
        assert!(!needs_translation("...{w=0.5}"));
        assert!(!needs_translation("{fast}"));
        assert!(needs_translation("Hello {i}there{/i}"));
    }

    #[test]
    fn group_by_source_keeps_first_occurrence_and_tracks_followers() {
        let units = vec![unit("a", "..."), unit("b", "Hi."), unit("c", "...")];
        let (sent, followers) = group_by_source(&units);
        assert_eq!(
            sent.iter().map(|u| u.block_id.as_str()).collect::<Vec<_>>(),
            vec!["a", "b"]
        );
        assert_eq!(followers["a"], vec!["c".to_string()]);
        assert_eq!(followers["b"], Vec::<String>::new());
    }

    #[test]
    fn spread_to_followers_copies_translation_and_failure_alike() {
        let mut followers = HashMap::new();
        followers.insert("a".to_string(), vec!["c".to_string(), "d".to_string()]);
        followers.insert("b".to_string(), vec![]);

        let result = TranslateBatchResult {
            translations: vec![TranslatedUnit {
                block_id: "a".to_string(),
                translated_text: "...".to_string(),
            }],
            failed_ids: vec!["b".to_string()],
        };
        let spread = spread_to_followers(result, &followers);
        let ids: Vec<&str> = spread
            .translations
            .iter()
            .map(|t| t.block_id.as_str())
            .collect();
        assert_eq!(ids, vec!["a", "c", "d"]);
        assert_eq!(spread.failed_ids, vec!["b".to_string()]);
    }

    #[tokio::test]
    async fn stray_and_repeated_ids_from_the_provider_are_not_counted() {
        let units = vec![unit("a", "Hello."), unit("b", "Bye.")];
        let mut provider = ScriptedProvider::new(vec![ok(&[
            ("a", "Bonjour."),
            ("a", "Salut."),
            ("zzz", "Hors du lot."),
            ("b", "Au revoir."),
        ])]);
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 2);
        assert_eq!(progress.failed, 0);
        let written: Vec<String> = drain(&mut rx)
            .into_iter()
            .filter_map(|event| match event {
                JobEvent::Chunk(chunk) => Some(chunk.translations),
                _ => None,
            })
            .flatten()
            .map(|t| t.block_id)
            .collect();
        assert_eq!(written, vec!["a".to_string(), "b".to_string()]);
    }

    #[tokio::test]
    async fn full_job_reports_progress_and_completes() {
        let units = vec![unit("a", "Hello."), unit("b", "Bye.")];
        let mut provider =
            ScriptedProvider::new(vec![ok(&[("a", "Bonjour."), ("b", "Au revoir.")])]);
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 2);
        assert_eq!(progress.failed, 0);
        assert!(progress.finished && !progress.running);
        assert_eq!(progress.error, None);

        let events = drain(&mut rx);
        assert!(matches!(events.last(), Some(JobEvent::Complete(_))));
    }

    #[tokio::test]
    async fn units_with_nothing_to_translate_are_copied_verbatim() {
        let units = vec![unit("a", "...{w=0.5}"), unit("b", "Hello.")];
        let mut provider = ScriptedProvider::new(vec![ok(&[("b", "Bonjour.")])]);
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 2);
        assert_eq!(provider.calls, vec![vec!["b".to_string()]]);
    }

    #[tokio::test]
    async fn duplicate_source_text_is_sent_once_and_spread_back() {
        let units = vec![
            unit("a", "Continue"),
            unit("b", "Continue"),
            unit("c", "Quit"),
        ];
        let mut provider = ScriptedProvider::new(vec![ok(&[("a", "Continuer"), ("c", "Quitter")])]);
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 3);
        assert_eq!(provider.calls, vec![vec!["a".to_string(), "c".to_string()]]);
    }

    #[tokio::test]
    async fn a_translation_identical_to_source_is_rejected() {
        let units = vec![unit("a", "Hello.")];
        let mut provider = ScriptedProvider::new(vec![ok(&[("a", "Hello.")])]);
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 0);
        assert_eq!(progress.failed, 1);
        let events = drain(&mut rx);
        assert!(events.iter().any(
            |e| matches!(e, JobEvent::Event(msg) if msg.to_string().contains("identical to the source text"))
        ));
    }

    #[tokio::test]
    async fn missing_interpolation_is_rejected_but_missing_tag_is_kept_with_warning() {
        let units = vec![unit("a", "Hi [name]."), unit("b", "Click {b}here{/b}.")];
        let mut provider = ScriptedProvider::new(vec![ok(&[
            ("a", "Salut."),       // dropped the [name] interpolation: blocking
            ("b", "Cliquez ici."), // dropped the {b} tag: cosmetic warning only
        ])]);
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 1);
        assert_eq!(progress.failed, 1);
        let events = drain(&mut rx);
        assert!(events
            .iter()
            .any(|e| matches!(e, JobEvent::Event(msg) if msg.to_string().contains("Rejected") && msg.to_string().contains("[name]"))));
        assert!(events
            .iter()
            .any(|e| matches!(e, JobEvent::Event(msg) if msg.to_string().contains("warning"))));
    }

    #[tokio::test]
    async fn failed_units_are_recovered_on_retry() {
        let units = vec![unit("a", "Hello."), unit("b", "Bye.")];
        let mut provider = ScriptedProvider::new(vec![
            // Main pass: "b" fails outright.
            Ok(TranslateBatchResult {
                translations: vec![TranslatedUnit {
                    block_id: "a".to_string(),
                    translated_text: "Bonjour.".to_string(),
                }],
                failed_ids: vec!["b".to_string()],
            }),
            // Retry pass (chunk size 8): "b" succeeds this time.
            ok(&[("b", "Au revoir.")]),
        ]);
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 2);
        assert_eq!(progress.failed, 0);
    }

    #[tokio::test]
    async fn units_still_failing_after_every_retry_pass_stay_failed() {
        let units = vec![unit("a", "Hello.")];
        let always_fails = TranslateBatchResult {
            translations: Vec::new(),
            failed_ids: vec!["a".to_string()],
        };
        // Main pass + one retry pass per RETRY_CHUNK_SIZES entry.
        let mut provider = ScriptedProvider::new(vec![
            Ok(always_fails.clone()),
            Ok(always_fails.clone()),
            Ok(always_fails),
        ]);
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.done, 0);
        assert_eq!(progress.failed, 1);
        assert_eq!(progress.total, 1);
    }

    #[tokio::test]
    async fn cancellation_before_a_chunk_stops_the_job_and_preserves_progress() {
        // Distinct source text per unit: identical text would dedupe
        // through group_by_source down to a single representative,
        // leaving nothing here to exercise multi-chunk cancellation.
        let units: Vec<_> = (0..120)
            .map(|i| unit(&i.to_string(), &format!("Hello {i}.")))
            .collect();
        let cancel = CancelToken::new();
        // Cancel from inside the provider, as if a user clicked "stop"
        // while the first chunk (of 50) was in flight — takes effect
        // before the second chunk starts.
        struct CancelingProvider(CancelToken);
        #[async_trait::async_trait]
        impl TranslationProvider for CancelingProvider {
            fn id(&self) -> &'static str {
                "canceling"
            }
            async fn translate_batch(
                &mut self,
                units: &[TranslationUnitPayload],
                _s: &str,
                _t: &str,
            ) -> Result<TranslateBatchResult, ProviderError> {
                self.0.cancel();
                Ok(TranslateBatchResult {
                    translations: units
                        .iter()
                        .map(|u| TranslatedUnit {
                            block_id: u.block_id.clone(),
                            translated_text: "Bonjour.".to_string(),
                        })
                        .collect(),
                    failed_ids: Vec::new(),
                })
            }
        }
        let mut provider = CancelingProvider(cancel.clone());
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(&units, &mut provider, "english", "french", cancel, tx).await;

        assert_eq!(progress.total, 120);
        assert_eq!(progress.done, 50);
        assert!(progress.finished);
    }

    #[tokio::test]
    async fn unreachable_provider_surfaces_as_a_job_error() {
        let units = vec![unit("a", "Hello.")];
        let unreachable = ProviderError::OllamaUnreachable {
            endpoint: "http://localhost:11434".to_string(),
        };
        let mut provider = ScriptedProvider::new(vec![Err(unreachable.clone())]);
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

        let progress = run_job(
            &units,
            &mut provider,
            "english",
            "french",
            CancelToken::new(),
            tx,
        )
        .await;

        assert_eq!(progress.error, Some(unreachable));
    }
}
