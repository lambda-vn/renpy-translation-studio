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

use std::time::{Duration, SystemTime};

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
    /// Set when a fatal error stopped the provider partway through the
    /// batch: what it translated before is kept, the job then stops. The
    /// units it never sent are in neither list. An error before anything
    /// was translated is an `Err` instead.
    pub stopped: Option<ProviderError>,
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
            detail: error.without_url().to_string(),
        }
    }
}

/// HTTP statuses after which retrying cannot help: rejected credentials
/// (401, 403), DeepL's exhausted quota (456) and a rate limit (429) that
/// [`send_with_backoff`] already waited out without success. Anything else
/// (timeout, 5xx) may be transient.
const FATAL_STATUSES: [u16; 4] = [401, 403, 429, 456];

/// Retries after a 429 before giving up on the request.
const RATE_LIMIT_RETRIES: u32 = 3;

/// Longest single wait after a 429, whatever `Retry-After` asks: the job
/// cannot be cancelled during the wait.
const MAX_RATE_LIMIT_WAIT: Duration = Duration::from_secs(30);

/// Send `request`, waiting and trying again when the server answers 429:
/// as long as its `Retry-After` header says (seconds or HTTP date), else
/// 2, 4 then 8 seconds, never more than [`MAX_RATE_LIMIT_WAIT`]. Any other
/// status, or a 429 still there after [`RATE_LIMIT_RETRIES`], is returned
/// as `error_for_status` would.
///
/// # Errors
///
/// A transport failure, or the final HTTP error status.
pub async fn send_with_backoff(
    request: reqwest::RequestBuilder,
) -> reqwest::Result<reqwest::Response> {
    let mut attempt = 0;
    loop {
        let Some(this) = request.try_clone() else {
            return request.send().await?.error_for_status();
        };
        let response = this.send().await?;
        if response.status() != reqwest::StatusCode::TOO_MANY_REQUESTS
            || attempt == RATE_LIMIT_RETRIES
        {
            return response.error_for_status();
        }
        attempt += 1;
        let wait = retry_after(response.headers(), SystemTime::now())
            .unwrap_or(Duration::from_secs(1 << attempt))
            .min(MAX_RATE_LIMIT_WAIT);
        log::warn!(
            "Rate limited (429): retry {attempt} of {RATE_LIMIT_RETRIES} in {} s",
            wait.as_secs()
        );
        tokio::time::sleep(wait).await;
    }
}

/// The wait a `Retry-After` header asks for, as delay-seconds or as an
/// HTTP date relative to `now`; `None` when absent or unreadable.
fn retry_after(headers: &reqwest::header::HeaderMap, now: SystemTime) -> Option<Duration> {
    let value = headers
        .get(reqwest::header::RETRY_AFTER)?
        .to_str()
        .ok()?
        .trim();
    if let Ok(seconds) = value.parse::<u64>() {
        return Some(Duration::from_secs(seconds));
    }
    let date = httpdate::parse_http_date(value).ok()?;
    Some(date.duration_since(now).unwrap_or(Duration::ZERO))
}

/// The error that must stop a job when `error` carries a fatal HTTP
/// status, `None` for a failure that only concerns the unit(s) sent.
pub fn fatal_status_error(error: reqwest::Error) -> Option<ProviderError> {
    let status = error.status()?.as_u16();
    FATAL_STATUSES
        .contains(&status)
        .then(|| ProviderError::from(error))
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

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::header::{HeaderMap, HeaderValue, RETRY_AFTER};
    use wiremock::matchers::method;
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn headers(value: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(RETRY_AFTER, HeaderValue::from_str(value).unwrap());
        headers
    }

    #[test]
    fn retry_after_reads_seconds_and_http_dates() {
        let now = httpdate::parse_http_date("Sun, 01 Nov 2026 12:00:00 GMT").unwrap();
        assert_eq!(
            retry_after(&headers(" 7 "), now),
            Some(Duration::from_secs(7))
        );
        assert_eq!(
            retry_after(&headers("Sun, 01 Nov 2026 12:00:20 GMT"), now),
            Some(Duration::from_secs(20))
        );
        assert_eq!(
            retry_after(&headers("Sun, 01 Nov 2026 11:59:00 GMT"), now),
            Some(Duration::ZERO)
        );
        assert_eq!(retry_after(&headers("soon"), now), None);
        assert_eq!(retry_after(&HeaderMap::new(), now), None);
    }

    #[tokio::test]
    async fn a_passing_rate_limit_is_waited_out() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(429).insert_header("Retry-After", "0"))
            .up_to_n_times(2)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(200))
            .mount(&server)
            .await;

        let response = send_with_backoff(reqwest::Client::new().post(server.uri()).body("x"))
            .await
            .unwrap();

        assert_eq!(response.status(), 200);
        assert_eq!(server.received_requests().await.unwrap().len(), 3);
    }

    #[tokio::test]
    async fn a_lasting_rate_limit_ends_as_a_fatal_error() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(429).insert_header("Retry-After", "0"))
            .mount(&server)
            .await;

        let error = send_with_backoff(reqwest::Client::new().post(server.uri()).body("x"))
            .await
            .unwrap_err();

        assert_eq!(
            server.received_requests().await.unwrap().len(),
            1 + RATE_LIMIT_RETRIES as usize
        );
        assert!(matches!(
            fatal_status_error(error),
            Some(ProviderError::Network {
                status: Some(429),
                ..
            })
        ));
    }

    #[tokio::test]
    async fn other_statuses_are_not_retried() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(403))
            .mount(&server)
            .await;

        let error = send_with_backoff(reqwest::Client::new().post(server.uri()).body("x"))
            .await
            .unwrap_err();

        assert_eq!(error.status().map(|s| s.as_u16()), Some(403));
        assert_eq!(server.received_requests().await.unwrap().len(), 1);
    }
}
