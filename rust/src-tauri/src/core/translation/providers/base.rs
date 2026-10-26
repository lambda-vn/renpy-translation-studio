//! Types shared by all translation providers. Port of the data half of
//! `core/translation/providers/base.py`.
//!
//! The Python `TranslateBatchRequest` also carries `on_batch_start`,
//! `is_cancelled` and `on_event` callbacks threaded into each provider's
//! *own* internal sub-batching (Ollama's context-window splitting,
//! DeepL's 50-text chunks) — so cancellation takes effect after the
//! request currently in flight rather than waiting for the whole job
//! chunk. `translation::job`, added in `2.0.0-alpha.3`, drives
//! cancellation and progress at its own chunk boundary (`CHUNK_SIZE`)
//! instead; a provider here still just answers one batch, uninterrupted
//! once started. Finer-grained mid-provider cancellation is deferred —
//! see `translation::job`'s module docs.

use crate::core::translation::job::JobMessage;

#[async_trait::async_trait]
pub trait TranslationProvider: Send {
    fn id(&self) -> &'static str;

    /// Get ready before the first batch of a job, saying what is going on
    /// through `notify` (a local model loading can take half a minute).
    /// Most providers have nothing to do.
    async fn warm_up(
        &mut self,
        _notify: &mut (dyn FnMut(JobMessage) + Send),
    ) -> Result<(), ProviderError> {
        Ok(())
    }

    async fn translate_batch(
        &mut self,
        units: &[TranslationUnitPayload],
        source_lang: &str,
        target_lang: &str,
    ) -> Result<TranslateBatchResult, ProviderError>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TranslationUnitPayload {
    pub block_id: String,
    pub source_text: String,
    /// Present only for context-aware providers (Ollama); DeepL and
    /// LibreTranslate ignore it.
    pub character_variable: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TranslatedUnit {
    pub block_id: String,
    pub translated_text: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TranslateBatchResult {
    pub translations: Vec<TranslatedUnit>,
    pub failed_ids: Vec<String>,
}

/// What can stop a provider, as a message key and its parameters rather
/// than a sentence, so the interface can show it in its own language (the
/// same contract as `job::JobMessage`). [`Display`](std::fmt::Display)
/// renders the English text, for logs and tests.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ProviderError {
    /// A transport or HTTP failure; `status` is set when the server answered.
    #[error("network error: {detail}")]
    Network { status: Option<u16>, detail: String },
    #[error("The Ollama model {model} is not installed on {endpoint} (ollama pull {model})")]
    OllamaModelMissing { model: String, endpoint: String },
    #[error("Cannot reach the Ollama server ({endpoint})")]
    OllamaUnreachable { endpoint: String },
    #[error("The request to the Ollama server ({endpoint}) failed.")]
    OllamaRequestFailed { endpoint: String },
    /// `provider` is a provider id: `deepl`, `ollama` or `libretranslate`.
    #[error("{provider} is not configured.")]
    NotConfigured { provider: &'static str },
    #[error("Unknown provider: {id}")]
    UnknownProvider { id: String },
}

impl From<reqwest::Error> for ProviderError {
    fn from(error: reqwest::Error) -> Self {
        Self::Network {
            status: error.status().map(|s| s.as_u16()),
            detail: error.to_string(),
        }
    }
}

impl ProviderError {
    /// The `providers.*` catalog key of this error.
    pub fn key(&self) -> String {
        match self {
            Self::Network { .. } => "providers.network_error".to_string(),
            Self::OllamaModelMissing { .. } => "providers.ollama_model_missing".to_string(),
            Self::OllamaUnreachable { .. } => "providers.ollama_unreachable".to_string(),
            Self::OllamaRequestFailed { .. } => "providers.ollama_request_failed".to_string(),
            Self::NotConfigured { provider } => format!("providers.{provider}_not_configured"),
            Self::UnknownProvider { .. } => "providers.unknown_provider".to_string(),
        }
    }

    /// The placeholders of the catalog string.
    pub fn params(&self) -> serde_json::Value {
        use serde_json::json;
        match self {
            Self::Network { detail, .. } => json!({ "detail": detail }),
            Self::OllamaModelMissing { model, endpoint } => {
                json!({ "model": model, "endpoint": endpoint })
            }
            Self::OllamaUnreachable { endpoint } | Self::OllamaRequestFailed { endpoint } => {
                json!({ "endpoint": endpoint })
            }
            Self::NotConfigured { .. } => json!({}),
            Self::UnknownProvider { id } => json!({ "id": id }),
        }
    }
}

impl serde::Serialize for ProviderError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut state = serializer.serialize_struct("ProviderError", 2)?;
        state.serialize_field("key", &self.key())?;
        state.serialize_field("params", &self.params())?;
        state.end()
    }
}
