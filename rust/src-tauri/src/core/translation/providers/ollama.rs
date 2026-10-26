//! Ollama LLM provider for context-aware translation. Port of
//! `core/translation/providers/ollama.py`.
//!
//! CLAUDE.md is explicit and this file exists to honor it: the
//! JSON-schema-constrained request format, the loose response parsing,
//! and the duplicate-content guard below are hard-won workarounds for
//! bugs in small quantized models (premature stopping, padding by
//! duplication, wrong key names, echoing the system prompt). None of it
//! is simplified from the Python original, and none of it should be
//! without a real test against a small model first.

use std::collections::{HashMap, HashSet};
use std::time::Duration;

use serde_json::{json, Value};

use crate::core::translation::job::JobMessage;

use super::base::{
    ProviderError, TranslateBatchResult, TranslatedUnit, TranslationProvider,
    TranslationUnitPayload,
};
use crate::core::storage::repositories::Character;
use crate::core::translation::context_builder::{
    build_batch_prompt, build_system_prompt, split_into_batches, ContextualUnit,
    MAX_UNITS_PER_BATCH,
};

pub const DEFAULT_ENDPOINT: &str = "http://localhost:11434";
const REQUEST_TIMEOUT: Duration = Duration::from_secs(300);
const DEFAULT_CONTEXT_LENGTH: i64 = 4096;
pub const MAX_NUM_CTX: i64 = 8192;
const TRANSLATION_TEMPERATURE: f64 = 0.2;
const COMPLETION_TEMPERATURE: f64 = 0.2;
const COMPLETION_MAX_TOKENS: i64 = 1024;
const MIN_DUPLICATE_TEXT_LENGTH: usize = 4;
const PS_TIMEOUT: Duration = Duration::from_secs(5);
const CPU_OFFLOAD_WARNING_THRESHOLD: f64 = 0.95;
const CLOUD_SUFFIX: &str = "-cloud";

/// Whether a model runs on Ollama's servers rather than here.
///
/// Cloud models carry a `-cloud` suffix and reach the same local
/// endpoint — the daemon authenticates and forwards the request. Nothing
/// of the model is loaded into this machine's memory, which is why the
/// guards written for local hardware do not apply to them.
pub fn is_cloud_model(model: &str) -> bool {
    model.ends_with(CLOUD_SUFFIX)
}

/// A JSON schema requiring exactly `count` translation entries.
///
/// Without `minItems`/`maxItems`, a model can legally satisfy the schema
/// after emitting a single entry — and small quantized models reliably
/// do exactly that on longer batches. Pinning the array length turns
/// "the model stopped early" into a grammar violation the constrained
/// decoder can't produce, rather than a silent, valid-but-incomplete
/// response.
fn build_response_schema(count: usize) -> Value {
    json!({
        "type": "array",
        "minItems": count,
        "maxItems": count,
        "items": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string"},
                "translation": {"type": "string"},
            },
            "required": ["block_id", "translation"],
        },
    })
}

fn value_to_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        other => other.to_string(),
    }
}

/// Pull `(block_id, translated_text)` out of one loosely-shaped response
/// item.
///
/// Small models don't reliably use the exact key names asked for in the
/// system prompt — `id` instead of `block_id` is common. Accepting both
/// avoids failing an entire batch over one non-compliant item.
fn extract_entry(item: &Value) -> Option<(String, String)> {
    let obj = item.as_object()?;
    let block_id = obj.get("block_id").or_else(|| obj.get("id"))?;
    let translation = obj.get("translation")?;
    if block_id.is_null() || translation.is_null() {
        return None;
    }
    Some((value_to_string(block_id), value_to_string(translation)))
}

/// Drop translations that are byte-for-byte copies across unrelated
/// units.
///
/// When a heavily quantized model is required to fill every array slot
/// (see [`build_response_schema`]) but runs out of anything genuine to
/// say, it tends to pad the response by repeating a neighboring entry's
/// translation verbatim — e.g. the translation for "Load" ends up
/// copied onto an unrelated credits paragraph. A short, incidental match
/// (a common word like "Oui") is normal and left alone; only longer
/// repeats shared across units with different source text are treated
/// as padding.
///
/// Returns `(kept, dropped_block_ids)`.
fn drop_duplicate_content(
    translations: Vec<TranslatedUnit>,
    source_by_id: &HashMap<String, String>,
) -> (Vec<TranslatedUnit>, Vec<String>) {
    let mut ids_by_text: HashMap<&str, Vec<&str>> = HashMap::new();
    for t in &translations {
        ids_by_text
            .entry(t.translated_text.as_str())
            .or_default()
            .push(t.block_id.as_str());
    }

    let mut duplicate_ids: HashSet<String> = HashSet::new();
    for (text, ids) in &ids_by_text {
        if ids.len() < 2 || text.chars().count() < MIN_DUPLICATE_TEXT_LENGTH {
            continue;
        }
        let distinct_sources: HashSet<&str> = ids
            .iter()
            .map(|id| source_by_id.get(*id).map_or("", String::as_str))
            .collect();
        if distinct_sources.len() > 1 {
            duplicate_ids.extend(ids.iter().map(|s| s.to_string()));
        }
    }

    if duplicate_ids.is_empty() {
        return (translations, Vec::new());
    }
    let kept: Vec<TranslatedUnit> = translations
        .into_iter()
        .filter(|t| !duplicate_ids.contains(&t.block_id))
        .collect();
    let mut dropped: Vec<String> = duplicate_ids.into_iter().collect();
    dropped.sort();
    (kept, dropped)
}

/// Turn each unit into a [`ContextualUnit`], without its neighbors' text.
///
/// The preceding and following source lines used to go along as
/// `context_before` / `context_after`, and small models translate them
/// into the line itself. Measured on gemma3:4b (The Question, 50 lines,
/// English to German, batches of 5): with them, 28 to 32 translations of
/// 44 carried a neighbor's sentence and 6 lines failed; without them, 0
/// of 50 in three runs and no failure. Labelling them "do not translate"
/// changed nothing (26 and 27). Do not send them again without a real
/// test on a small model.
fn add_context(units: &[TranslationUnitPayload]) -> Vec<ContextualUnit> {
    units
        .iter()
        .map(|unit| ContextualUnit {
            block_id: unit.block_id.clone(),
            source_text: unit.source_text.clone(),
            character_variable: unit.character_variable.clone(),
            prev_text: None,
            next_text: None,
        })
        .collect()
}

/// Translates using a locally running (or Ollama-cloud) model.
pub struct OllamaProvider {
    endpoint: String,
    model: String,
    universe_summary: Option<String>,
    characters: Vec<Character>,
    batch_size: Option<usize>,
    num_ctx: Option<i64>,
    client: reqwest::Client,
}

impl OllamaProvider {
    pub const ID: &'static str = "ollama";

    pub fn new(
        endpoint: &str,
        model: String,
        universe_summary: Option<String>,
        characters: Vec<Character>,
        batch_size: Option<usize>,
    ) -> Self {
        Self {
            endpoint: endpoint.trim_end_matches('/').to_string(),
            model,
            universe_summary,
            characters,
            batch_size,
            num_ctx: None,
            client: reqwest::Client::builder()
                .timeout(REQUEST_TIMEOUT)
                .build()
                .unwrap(),
        }
    }

    pub async fn test_connection(&self) -> bool {
        self.client
            .get(format!("{}/api/tags", self.endpoint))
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .is_ok_and(|resp| resp.status().is_success())
    }

    /// Names of all locally available models.
    pub async fn list_models(&self) -> Result<Vec<String>, ProviderError> {
        let resp: Value = self
            .client
            .get(format!("{}/api/tags", self.endpoint))
            .timeout(Duration::from_secs(10))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        let models = resp["models"]
            .as_array()
            .map(|list| {
                list.iter()
                    .filter_map(|m| m.get("name").and_then(Value::as_str).map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        log::debug!("list_models on {} -> {models:?}", self.endpoint);
        Ok(models)
    }

    /// The maximum context length for the given model, via `/api/show`,
    /// or [`DEFAULT_CONTEXT_LENGTH`] if it could not be determined.
    pub async fn get_context_length(&self, model: &str) -> Result<i64, ProviderError> {
        let resp: Value = self
            .client
            .post(format!("{}/api/show", self.endpoint))
            .timeout(Duration::from_secs(30))
            .json(&json!({"name": model}))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        let model_info = &resp["model_info"];
        let architecture = model_info["general.architecture"].as_str().unwrap_or("");
        let key = format!("{architecture}.context_length");
        let length = model_info
            .get(&key)
            .and_then(Value::as_i64)
            .unwrap_or(DEFAULT_CONTEXT_LENGTH);
        Ok(length)
    }

    /// Decide how much context to ask the model for.
    ///
    /// [`MAX_NUM_CTX`] protects this machine's VRAM: past it the KV
    /// cache spills and generation collapses. A cloud model is not
    /// loaded here at all, so the cap protects nothing and only costs —
    /// [`split_into_batches`] subtracts `num_ctx` (plus the output
    /// margin) from the budget, and a rich universe summary or a long
    /// character glossary can otherwise shrink batches to one or two
    /// units instead of eight.
    async fn resolve_num_ctx(&self) -> Result<i64, ProviderError> {
        let length = self.get_context_length(&self.model).await?;
        if is_cloud_model(&self.model) {
            return Ok(length);
        }
        Ok(length.min(MAX_NUM_CTX))
    }

    async fn ensure_num_ctx(&mut self) -> Result<i64, ProviderError> {
        if let Some(num_ctx) = self.num_ctx {
            return Ok(num_ctx);
        }
        // A 404 on /api/show means the server answered but has no such
        // model: saying it is unreachable would send the user looking at
        // the wrong thing.
        let num_ctx = self
            .resolve_num_ctx()
            .await
            .inspect_err(|error| {
                log::warn!("Cannot use {} on {}: {error}", self.model, self.endpoint);
            })
            .map_err(|error| match error {
                ProviderError::Network {
                    status: Some(404), ..
                } => ProviderError::OllamaModelMissing {
                    model: self.model.clone(),
                    endpoint: self.endpoint.clone(),
                },
                _ => ProviderError::OllamaUnreachable {
                    endpoint: self.endpoint.clone(),
                },
            })?;
        log::debug!("num_ctx for {} on {}: {num_ctx}", self.model, self.endpoint);
        self.num_ctx = Some(num_ctx);
        Ok(num_ctx)
    }

    /// Load the model into memory and report if it spills onto CPU.
    ///
    /// Ollama unloads a model after ~5 minutes of inactivity, so the
    /// first request of a job would otherwise pay for a full cold load
    /// with no visible feedback. Sending a chat request with an empty
    /// `messages` array is the documented way to make Ollama load a
    /// model without generating anything. Immediately after, `/api/ps`
    /// reports how much of the loaded model sits in VRAM versus CPU.
    ///
    /// Neither step can fail the caller: any error (unreachable server,
    /// unexpected response shape) is swallowed, since a genuinely
    /// unreachable server was already caught by [`Self::ensure_num_ctx`]
    /// just before this runs. Returns the CPU-offload percentage when
    /// it crosses [`CPU_OFFLOAD_WARNING_THRESHOLD`], for a caller to
    /// surface however it likes.
    async fn preload_and_warn(&self) -> Option<i64> {
        let num_ctx = self.num_ctx?;
        let preload = self
            .client
            .post(format!("{}/api/chat", self.endpoint))
            .json(&json!({
                "model": self.model,
                "messages": [],
                "options": {"num_ctx": num_ctx},
            }))
            .send()
            .await
            .and_then(reqwest::Response::error_for_status);
        if preload.is_err() {
            return None;
        }

        let ps: Value = self
            .client
            .get(format!("{}/api/ps", self.endpoint))
            .timeout(PS_TIMEOUT)
            .send()
            .await
            .ok()?
            .error_for_status()
            .ok()?
            .json()
            .await
            .ok()?;
        let entry = ps["models"].as_array()?.iter().find(|m| {
            m.get("name").and_then(Value::as_str) == Some(self.model.as_str())
                || m.get("model").and_then(Value::as_str) == Some(self.model.as_str())
        })?;
        let size = entry["size"].as_f64().unwrap_or(0.0);
        if size == 0.0 {
            return None;
        }
        let size_vram = entry["size_vram"].as_f64().unwrap_or(0.0);
        let ratio = size_vram / size;

        if ratio < CPU_OFFLOAD_WARNING_THRESHOLD {
            Some(((1.0 - ratio) * 100.0).round() as i64)
        } else {
            None
        }
    }

    /// Send a single free-form prompt and return the model's text reply.
    ///
    /// Pins the temperature and caps the reply length for the same
    /// reason [`Self::translate_single_batch`] pins its own: left to the
    /// model's default, one fixed prompt becomes a lottery, and an
    /// unbounded reply here is carried into every later batch prompt.
    pub async fn complete(&mut self, prompt: &str) -> Result<String, ProviderError> {
        let num_ctx = self.ensure_num_ctx().await?;
        let resp = self
            .client
            .post(format!("{}/api/chat", self.endpoint))
            .json(&json!({
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": false,
                "options": {
                    "num_ctx": num_ctx,
                    "temperature": COMPLETION_TEMPERATURE,
                    "num_predict": COMPLETION_MAX_TOKENS,
                },
            }))
            .send()
            .await
            .and_then(reqwest::Response::error_for_status)
            .map_err(|error| {
                log::warn!("Ollama completion failed: {error}");
                self.request_failed()
            })?;
        let body: Value = resp.json().await.map_err(|_| self.request_failed())?;
        body["message"]["content"]
            .as_str()
            .map(String::from)
            .ok_or_else(|| self.request_failed())
    }

    fn request_failed(&self) -> ProviderError {
        ProviderError::OllamaRequestFailed {
            endpoint: self.endpoint.clone(),
        }
    }

    /// Translate all units using dynamic batching.
    ///
    /// Errs only when the server cannot be reached to determine the
    /// model's context length — a hard precondition, checked once. A
    /// batch that fails once context is resolved reports its own
    /// block_ids as failed instead of aborting the rest.
    pub async fn translate_batch(
        &mut self,
        units: &[TranslationUnitPayload],
        source_lang: &str,
        target_lang: &str,
    ) -> Result<TranslateBatchResult, ProviderError> {
        let num_ctx = self.ensure_num_ctx().await?;

        let system_prompt = build_system_prompt(
            self.universe_summary.as_deref(),
            &self.characters,
            source_lang,
            target_lang,
        );

        let contextual_units = add_context(units);
        let batches = split_into_batches(
            &contextual_units,
            &system_prompt,
            num_ctx,
            self.batch_size.unwrap_or(MAX_UNITS_PER_BATCH),
        );

        log::debug!(
            "{} unit(s) in {} request(s) to {} (num_ctx {num_ctx})",
            units.len(),
            batches.len(),
            self.model
        );
        let mut result = TranslateBatchResult::default();
        for batch in batches {
            let (translations, failed) = self.translate_single_batch(&batch, &system_prompt).await;
            result.translations.extend(translations);
            result.failed_ids.extend(failed);
        }
        Ok(result)
    }

    /// Send one batch to Ollama and parse the JSON response.
    ///
    /// Uses a low, pinned temperature rather than the model's default —
    /// at default temperature a weak or heavily quantized model can
    /// drift into echoing the system prompt instead of translating,
    /// especially on longer batches. Passes a JSON schema
    /// ([`build_response_schema`]) as `format` instead of the plain
    /// `"json"` string, constraining the model's output via
    /// grammar-based sampling to an array of exactly `batch.len()`
    /// `{block_id, translation}` objects — this can't stop a model from
    /// putting nonsense inside a translation field, but it can no
    /// longer wrap the array in an object, return a single bare object,
    /// stop after one entry, or use the wrong key names.
    /// [`extract_entry`] and the `requested_ids` check remain a second
    /// line of defense regardless, and [`drop_duplicate_content`]
    /// catches the padding a model resorts to when it runs out of
    /// genuine content but still has to fill every slot.
    ///
    /// On any failure the whole batch is reported as failed rather than
    /// partially parsed.
    async fn translate_single_batch(
        &self,
        batch: &[ContextualUnit],
        system_prompt: &str,
    ) -> (Vec<TranslatedUnit>, Vec<String>) {
        let requested_ids: HashSet<&str> = batch.iter().map(|u| u.block_id.as_str()).collect();
        let source_by_id: HashMap<String, String> = batch
            .iter()
            .map(|u| (u.block_id.clone(), u.source_text.clone()))
            .collect();
        let user_prompt = build_batch_prompt(batch);
        let fail_all = |reason: &str| {
            log::warn!("Batch of {} unit(s) failed: {reason}", batch.len());
            (
                Vec::new(),
                batch.iter().map(|u| u.block_id.clone()).collect(),
            )
        };
        log::debug!(
            "Batch request ({} unit(s)):
{user_prompt}",
            batch.len()
        );

        let response = self
            .client
            .post(format!("{}/api/chat", self.endpoint))
            .json(&json!({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": false,
                "format": build_response_schema(batch.len()),
                "options": {
                    "num_ctx": self.num_ctx,
                    "truncate": false,
                    "temperature": TRANSLATION_TEMPERATURE,
                },
            }))
            .send()
            .await
            .and_then(reqwest::Response::error_for_status);

        let response = match response {
            Ok(response) => response,
            Err(error) => return fail_all(&error.to_string()),
        };
        let Ok(body) = response.json::<Value>().await else {
            return fail_all("unreadable response body");
        };
        let Some(content) = body["message"]["content"].as_str() else {
            return fail_all("no message content in the response");
        };
        log::debug!("Batch raw response: {content}");
        let Ok(parsed) = serde_json::from_str::<Value>(content) else {
            return fail_all("the response is not JSON");
        };

        let array_value = match &parsed {
            Value::Object(map) => {
                if extract_entry(&parsed).is_some() {
                    Value::Array(vec![parsed.clone()])
                } else {
                    map.values()
                        .find(|v| v.is_array())
                        .cloned()
                        .unwrap_or_else(|| parsed.clone())
                }
            }
            other => other.clone(),
        };
        let Some(items) = array_value.as_array() else {
            return fail_all("no array in the response");
        };

        let mut translations: Vec<TranslatedUnit> = Vec::new();
        for item in items {
            if let Some((block_id, translated_text)) = extract_entry(item) {
                if requested_ids.contains(block_id.as_str()) {
                    translations.push(TranslatedUnit {
                        block_id,
                        translated_text,
                    });
                }
            }
        }

        let (translations, duplicate_ids) = drop_duplicate_content(translations, &source_by_id);
        if !duplicate_ids.is_empty() {
            log::warn!("Dropped padding duplicated across the batch: {duplicate_ids:?}");
        }

        let present: HashSet<&str> = translations.iter().map(|t| t.block_id.as_str()).collect();
        let mut missing_ids: Vec<String> = requested_ids
            .into_iter()
            .filter(|id| !present.contains(id))
            .map(String::from)
            .collect();
        missing_ids.sort();
        if !missing_ids.is_empty() {
            log::warn!(
                "{} of {} unit(s) missing from the response: {missing_ids:?}",
                missing_ids.len(),
                batch.len()
            );
        }

        (translations, missing_ids)
    }
}

#[async_trait::async_trait]
impl TranslationProvider for OllamaProvider {
    fn id(&self) -> &'static str {
        Self::ID
    }

    /// Resolve the context window, then load the model, announcing it:
    /// without this the first batch of a cold model waits silently.
    async fn warm_up(
        &mut self,
        notify: &mut (dyn FnMut(JobMessage) + Send),
    ) -> Result<(), ProviderError> {
        self.ensure_num_ctx().await?;
        notify(JobMessage::ModelLoading);
        if let Some(percent) = self.preload_and_warn().await {
            notify(JobMessage::CpuOffload { percent });
        }
        Ok(())
    }

    async fn translate_batch(
        &mut self,
        units: &[TranslationUnitPayload],
        source_lang: &str,
        target_lang: &str,
    ) -> Result<TranslateBatchResult, ProviderError> {
        OllamaProvider::translate_batch(self, units, source_lang, target_lang).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn unit(block_id: &str, text: &str) -> TranslationUnitPayload {
        TranslationUnitPayload {
            block_id: block_id.to_string(),
            source_text: text.to_string(),
            character_variable: None,
        }
    }

    #[test]
    fn is_cloud_model_checks_suffix() {
        assert!(is_cloud_model("gpt-oss:120b-cloud"));
        assert!(!is_cloud_model("gemma3:1b"));
    }

    #[test]
    fn response_schema_pins_exact_array_length() {
        let schema = build_response_schema(3);
        assert_eq!(schema["minItems"], 3);
        assert_eq!(schema["maxItems"], 3);
        assert_eq!(
            schema["items"]["required"],
            json!(["block_id", "translation"])
        );
    }

    #[test]
    fn extract_entry_accepts_id_as_fallback_key() {
        let item = json!({"id": "a", "translation": "Bonjour"});
        assert_eq!(
            extract_entry(&item),
            Some(("a".to_string(), "Bonjour".to_string()))
        );
    }

    #[test]
    fn extract_entry_prefers_block_id_over_id() {
        let item = json!({"block_id": "real", "id": "wrong", "translation": "x"});
        assert_eq!(extract_entry(&item).unwrap().0, "real");
    }

    #[test]
    fn extract_entry_rejects_missing_translation() {
        assert_eq!(extract_entry(&json!({"block_id": "a"})), None);
    }

    #[test]
    fn extract_entry_rejects_non_object_item() {
        assert_eq!(extract_entry(&json!("just a string")), None);
    }

    #[test]
    fn extract_entry_coerces_non_string_block_id() {
        let item = json!({"block_id": 42, "translation": "x"});
        assert_eq!(extract_entry(&item).unwrap().0, "42");
    }

    #[test]
    fn drop_duplicate_content_catches_padding_across_unrelated_units() {
        let translations = vec![
            TranslatedUnit {
                block_id: "load".to_string(),
                translated_text: "Charger".to_string(),
            },
            TranslatedUnit {
                block_id: "credits_para".to_string(),
                translated_text: "Charger".to_string(),
            },
        ];
        let mut source_by_id = HashMap::new();
        source_by_id.insert("load".to_string(), "Load".to_string());
        source_by_id.insert(
            "credits_para".to_string(),
            "Thanks to our backers...".to_string(),
        );

        let (kept, dropped) = drop_duplicate_content(translations, &source_by_id);
        assert!(kept.is_empty());
        assert_eq!(
            dropped,
            vec!["credits_para".to_string(), "load".to_string()]
        );
    }

    #[test]
    fn drop_duplicate_content_keeps_short_incidental_matches() {
        let translations = vec![
            TranslatedUnit {
                block_id: "a".to_string(),
                translated_text: "Oui".to_string(),
            },
            TranslatedUnit {
                block_id: "b".to_string(),
                translated_text: "Oui".to_string(),
            },
        ];
        let mut source_by_id = HashMap::new();
        source_by_id.insert("a".to_string(), "Yes".to_string());
        source_by_id.insert("b".to_string(), "Yeah".to_string());

        let (kept, dropped) = drop_duplicate_content(translations, &source_by_id);
        assert_eq!(kept.len(), 2);
        assert!(dropped.is_empty());
    }

    #[test]
    fn drop_duplicate_content_keeps_a_genuinely_repeated_source() {
        // Same translated text is fine when it's really the same source
        // repeated (e.g. two identical menu labels) — only a mismatch
        // across DIFFERENT source texts marks padding.
        let translations = vec![
            TranslatedUnit {
                block_id: "a".to_string(),
                translated_text: "Continuer".to_string(),
            },
            TranslatedUnit {
                block_id: "b".to_string(),
                translated_text: "Continuer".to_string(),
            },
        ];
        let mut source_by_id = HashMap::new();
        source_by_id.insert("a".to_string(), "Continue".to_string());
        source_by_id.insert("b".to_string(), "Continue".to_string());

        let (kept, dropped) = drop_duplicate_content(translations, &source_by_id);
        assert_eq!(kept.len(), 2);
        assert!(dropped.is_empty());
    }

    #[test]
    fn add_context_sends_no_neighbor_text() {
        let units = vec![
            unit("a", "First."),
            unit("b", "Second."),
            unit("c", "Third."),
        ];
        let contextual = add_context(&units);
        assert!(contextual
            .iter()
            .all(|u| u.prev_text.is_none() && u.next_text.is_none()));
        let prompt = build_batch_prompt(&contextual);
        assert!(!prompt.contains("context_"), "{prompt}");
        assert_eq!(
            prompt,
            "block_id: a\nsource: First.\n\n---\n\nblock_id: b\nsource: Second.\n\n---\n\nblock_id: c\nsource: Third."
        );
    }

    #[tokio::test]
    async fn get_context_length_reads_architecture_prefixed_key() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/show"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "model_info": {
                    "general.architecture": "gemma3",
                    "gemma3.context_length": 32768
                }
            })))
            .mount(&server)
            .await;

        let provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        let length = provider.get_context_length("gemma3:1b").await.unwrap();
        assert_eq!(length, 32768);
    }

    #[tokio::test]
    async fn get_context_length_falls_back_to_default_when_key_is_absent() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/show"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"model_info": {}})))
            .mount(&server)
            .await;

        let provider =
            OllamaProvider::new(&server.uri(), "mystery:1b".to_string(), None, vec![], None);
        let length = provider.get_context_length("mystery:1b").await.unwrap();
        assert_eq!(length, DEFAULT_CONTEXT_LENGTH);
    }

    #[tokio::test]
    async fn resolve_num_ctx_caps_local_models_but_not_cloud_models() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/show"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "model_info": {"general.architecture": "x", "x.context_length": 131072}
            })))
            .mount(&server)
            .await;

        let local = OllamaProvider::new(
            &server.uri(),
            "big-model:70b".to_string(),
            None,
            vec![],
            None,
        );
        assert_eq!(local.resolve_num_ctx().await.unwrap(), MAX_NUM_CTX);

        let cloud = OllamaProvider::new(
            &server.uri(),
            "big-model:70b-cloud".to_string(),
            None,
            vec![],
            None,
        );
        assert_eq!(cloud.resolve_num_ctx().await.unwrap(), 131072);
    }

    #[tokio::test]
    async fn translate_batch_sends_a_length_pinned_schema_and_maps_results() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/show"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"model_info": {}})))
            .mount(&server)
            .await;
        // Preload (empty messages) and the real batch both hit /api/chat;
        // distinguish by response shape isn't needed since wiremock
        // matches in registration order and the preload's response body
        // is never parsed as the batch's.
        Mock::given(method("POST"))
            .and(path("/api/chat"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "message": {"content": "[{\"block_id\": \"a\", \"translation\": \"Bonjour.\"}]"}
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/api/ps"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"models": []})))
            .mount(&server)
            .await;

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        let units = vec![unit("a", "Hello.")];
        let result = provider
            .translate_batch(&units, "english", "french")
            .await
            .unwrap();

        assert!(result.failed_ids.is_empty());
        assert_eq!(result.translations[0].block_id, "a");
        assert_eq!(result.translations[0].translated_text, "Bonjour.");
    }

    #[tokio::test]
    async fn translate_batch_unwraps_a_response_object_keyed_differently() {
        // A model that wraps the array in an object under some other
        // key (JSON-object output mode forcing a top-level object on
        // some providers) is still recovered.
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/show"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"model_info": {}})))
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path("/api/chat"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "message": {
                    "content": "{\"results\": [{\"block_id\": \"a\", \"translation\": \"Bonjour.\"}]}"
                }
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/api/ps"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"models": []})))
            .mount(&server)
            .await;

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        let result = provider
            .translate_batch(&[unit("a", "Hello.")], "english", "french")
            .await
            .unwrap();

        assert_eq!(result.translations[0].translated_text, "Bonjour.");
    }

    #[tokio::test]
    async fn translate_batch_reports_missing_block_ids_as_failed() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/show"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"model_info": {}})))
            .mount(&server)
            .await;
        // Model answers only one of two requested units.
        Mock::given(method("POST"))
            .and(path("/api/chat"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "message": {"content": "[{\"block_id\": \"a\", \"translation\": \"Bonjour.\"}]"}
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/api/ps"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"models": []})))
            .mount(&server)
            .await;

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        let units = vec![unit("a", "Hello."), unit("b", "Goodbye.")];
        let result = provider
            .translate_batch(&units, "english", "french")
            .await
            .unwrap();

        assert_eq!(result.translations.len(), 1);
        assert_eq!(result.failed_ids, vec!["b".to_string()]);
    }

    #[tokio::test]
    async fn translate_batch_errs_when_context_length_is_unreachable() {
        let server = MockServer::start().await;
        // No mock registered for /api/show: any request 404s.

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        let result = provider
            .translate_batch(&[unit("a", "Hi.")], "english", "french")
            .await;

        assert_eq!(
            result.err(),
            Some(ProviderError::OllamaModelMissing {
                model: "gemma3:1b".to_string(),
                endpoint: server.uri(),
            })
        );
    }

    #[tokio::test]
    async fn translate_batch_says_unreachable_when_nothing_listens() {
        // A port just released: wiremock pools its servers, so dropping
        // a MockServer would leave something answering 404 there.
        let port = std::net::TcpListener::bind("127.0.0.1:0")
            .and_then(|listener| listener.local_addr())
            .map(|address| address.port())
            .unwrap();
        let endpoint = format!("http://127.0.0.1:{port}");

        let mut provider =
            OllamaProvider::new(&endpoint, "gemma3:1b".to_string(), None, vec![], None);
        let result = provider
            .translate_batch(&[unit("a", "Hi.")], "english", "french")
            .await;

        assert_eq!(
            result.err(),
            Some(ProviderError::OllamaUnreachable { endpoint })
        );
    }

    #[tokio::test]
    async fn preload_and_warn_reports_high_cpu_offload() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/chat"))
            .respond_with(
                ResponseTemplate::new(200).set_body_json(json!({"message": {"content": ""}})),
            )
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/api/ps"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "models": [{"name": "gemma3:1b", "size": 1000, "size_vram": 100}]
            })))
            .mount(&server)
            .await;

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        provider.num_ctx = Some(4096);
        let warning = provider.preload_and_warn().await;
        assert_eq!(warning, Some(90));
    }

    #[tokio::test]
    async fn preload_and_warn_is_silent_when_mostly_in_vram() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/chat"))
            .respond_with(
                ResponseTemplate::new(200).set_body_json(json!({"message": {"content": ""}})),
            )
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/api/ps"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "models": [{"name": "gemma3:1b", "size": 1000, "size_vram": 990}]
            })))
            .mount(&server)
            .await;

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        provider.num_ctx = Some(4096);
        assert_eq!(provider.preload_and_warn().await, None);
    }

    #[tokio::test]
    async fn warm_up_announces_the_load_then_the_cpu_offload() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/api/show"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "model_info": {"general.architecture": "gemma3", "gemma3.context_length": 8192}
            })))
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path("/api/chat"))
            .respond_with(
                ResponseTemplate::new(200).set_body_json(json!({"message": {"content": ""}})),
            )
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/api/ps"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "models": [{"name": "gemma3:1b", "size": 1000, "size_vram": 100}]
            })))
            .mount(&server)
            .await;

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        let mut notices = Vec::new();
        TranslationProvider::warm_up(&mut provider, &mut |m| notices.push(m))
            .await
            .unwrap();

        assert_eq!(
            notices,
            vec![
                JobMessage::ModelLoading,
                JobMessage::CpuOffload { percent: 90 }
            ]
        );
    }

    #[tokio::test]
    async fn warm_up_says_nothing_when_the_model_is_missing() {
        let server = MockServer::start().await;
        // No mock for /api/show: the model is unknown (404).

        let mut provider =
            OllamaProvider::new(&server.uri(), "gemma3:1b".to_string(), None, vec![], None);
        let mut notices = Vec::new();
        let result = TranslationProvider::warm_up(&mut provider, &mut |m| notices.push(m)).await;

        assert!(matches!(
            result,
            Err(ProviderError::OllamaModelMissing { .. })
        ));
        assert!(notices.is_empty());
    }
}
