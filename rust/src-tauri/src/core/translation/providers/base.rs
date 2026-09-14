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

#[async_trait::async_trait]
pub trait TranslationProvider: Send {
    fn id(&self) -> &'static str;

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

#[derive(Debug, thiserror::Error)]
pub enum ProviderError {
    #[error("network error: {0}")]
    Network(#[from] reqwest::Error),
    #[error("{0}")]
    Message(String),
}
