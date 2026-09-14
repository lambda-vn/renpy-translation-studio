//! Types shared by all translation providers. Port of the data half of
//! `core/translation/providers/base.py`.
//!
//! The Python `TranslateBatchRequest` also carries `on_batch_start`,
//! `is_cancelled` and `on_event` callbacks — progress reporting and
//! cooperative cancellation around a *sequence* of provider requests.
//! That belongs to the job engine driving these providers (chunking,
//! retries, cancellation), which is `2.0.0-alpha.3`, not to the
//! providers themselves. A provider here just answers one batch.

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

#[derive(Debug, thiserror::Error)]
pub enum ProviderError {
    #[error("network error: {0}")]
    Network(#[from] reqwest::Error),
    #[error("{0}")]
    Message(String),
}
