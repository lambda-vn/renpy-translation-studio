//! LibreTranslate machine translation provider. Port of
//! `core/translation/providers/libretranslate.py`.

use std::time::Duration;

use serde::{Deserialize, Serialize};

use super::base::{
    ProviderError, TranslateBatchResult, TranslatedUnit, TranslationProvider,
    TranslationUnitPayload,
};
use crate::core::languages::get_language;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

/// Strip whitespace the API added at edges the source doesn't have.
///
/// LibreTranslate sometimes appends line breaks to its translations.
/// Each edge is only stripped when the matching edge of the source text
/// carries no whitespace itself, so intentional leading/trailing
/// spacing in the source is never lost.
pub fn strip_added_whitespace(source: &str, translated: &str) -> String {
    let mut translated = translated;
    let source_starts_with_space = source.chars().next().is_some_and(char::is_whitespace);
    let source_ends_with_space = source.chars().last().is_some_and(char::is_whitespace);

    let trimmed_start = if !source_starts_with_space {
        translated.trim_start()
    } else {
        translated
    };
    translated = trimmed_start;
    let trimmed_end = if !source_ends_with_space {
        translated.trim_end()
    } else {
        translated
    };
    trimmed_end.to_string()
}

/// Map a Ren'Py language identifier to a LibreTranslate language code.
pub fn resolve_libretranslate_lang(code: &str) -> String {
    match get_language(code) {
        Some(lang) => lang.iso.to_string(),
        None => code.to_lowercase(),
    }
}

#[derive(Deserialize)]
struct TranslateResponse {
    #[serde(default)]
    #[serde(rename = "translatedText")]
    translated_text: String,
}

#[derive(Serialize)]
struct TranslatePayload<'a> {
    q: &'a str,
    source: &'a str,
    target: &'a str,
    format: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    api_key: Option<&'a str>,
}

/// Translates text using any LibreTranslate-compatible instance.
///
/// The endpoint URL is mandatory, with no hardcoded default — the user
/// must provide one explicitly. Public instances have unpredictable
/// rate limits; self-hosting is recommended.
pub struct LibreTranslateProvider {
    endpoint: String,
    api_key: Option<String>,
    client: reqwest::Client,
}

impl LibreTranslateProvider {
    pub const ID: &'static str = "libretranslate";

    /// # Errors
    /// Returns an error message if `endpoint` is empty.
    pub fn new(endpoint: &str, api_key: Option<String>) -> Result<Self, String> {
        if endpoint.is_empty() {
            return Err("LibreTranslate endpoint URL is required.".to_string());
        }
        Ok(Self {
            endpoint: endpoint.trim_end_matches('/').to_string(),
            api_key,
            client: reqwest::Client::builder()
                .timeout(REQUEST_TIMEOUT)
                .build()
                .unwrap(),
        })
    }

    pub async fn test_connection(&self) -> bool {
        self.client
            .get(format!("{}/languages", self.endpoint))
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .is_ok_and(|resp| resp.status().is_success())
    }

    /// Translate texts one API call per unit (a LibreTranslate
    /// limitation). A unit that fails reports its own block_id as
    /// failed; the rest of the batch still proceeds.
    pub async fn translate_batch(
        &self,
        units: &[TranslationUnitPayload],
        source_lang: &str,
        target_lang: &str,
    ) -> TranslateBatchResult {
        let source = resolve_libretranslate_lang(source_lang);
        let target = resolve_libretranslate_lang(target_lang);
        let mut result = TranslateBatchResult::default();

        for unit in units {
            let payload = TranslatePayload {
                q: &unit.source_text,
                source: &source,
                target: &target,
                format: "text",
                api_key: self.api_key.as_deref().filter(|k| !k.is_empty()),
            };
            let outcome = self
                .client
                .post(format!("{}/translate", self.endpoint))
                .json(&payload)
                .send()
                .await
                .and_then(reqwest::Response::error_for_status);

            match outcome {
                Ok(resp) => match resp.json::<TranslateResponse>().await {
                    Ok(parsed) => {
                        let translated =
                            strip_added_whitespace(&unit.source_text, &parsed.translated_text);
                        result.translations.push(TranslatedUnit {
                            block_id: unit.block_id.clone(),
                            translated_text: translated,
                        });
                    }
                    Err(_) => result.failed_ids.push(unit.block_id.clone()),
                },
                Err(_) => result.failed_ids.push(unit.block_id.clone()),
            }
        }

        result
    }
}

#[async_trait::async_trait]
impl TranslationProvider for LibreTranslateProvider {
    fn id(&self) -> &'static str {
        Self::ID
    }

    async fn translate_batch(
        &mut self,
        units: &[TranslationUnitPayload],
        source_lang: &str,
        target_lang: &str,
    ) -> Result<TranslateBatchResult, ProviderError> {
        Ok(LibreTranslateProvider::translate_batch(self, units, source_lang, target_lang).await)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[test]
    fn empty_endpoint_is_rejected() {
        assert!(LibreTranslateProvider::new("", None).is_err());
    }

    #[test]
    fn trailing_slash_is_stripped() {
        let provider = LibreTranslateProvider::new("http://localhost:5000/", None).unwrap();
        assert_eq!(provider.endpoint, "http://localhost:5000");
    }

    #[test]
    fn resolve_lang_falls_back_to_lowercase_code() {
        assert_eq!(resolve_libretranslate_lang("french"), "fr");
        assert_eq!(resolve_libretranslate_lang("KLINGON"), "klingon");
    }

    #[test]
    fn strips_only_edges_the_source_lacks() {
        assert_eq!(strip_added_whitespace("Hello", "  Bonjour  "), "Bonjour");
        assert_eq!(strip_added_whitespace(" Hello", "  Bonjour  "), "  Bonjour");
        assert_eq!(strip_added_whitespace("Hello ", "  Bonjour  "), "Bonjour  ");
        assert_eq!(strip_added_whitespace("", "  x  "), "x");
    }

    fn unit(block_id: &str, text: &str) -> TranslationUnitPayload {
        TranslationUnitPayload {
            block_id: block_id.to_string(),
            source_text: text.to_string(),
            character_variable: None,
        }
    }

    #[tokio::test]
    async fn translate_batch_sends_one_request_per_unit() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/translate"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "translatedText": "Bonjour.\n"
            })))
            .expect(2)
            .mount(&server)
            .await;

        let provider = LibreTranslateProvider::new(&server.uri(), None).unwrap();
        let units = vec![unit("a", "Hello."), unit("b", "Hi.")];
        let result = provider.translate_batch(&units, "english", "french").await;

        assert_eq!(result.translations.len(), 2);
        assert_eq!(result.translations[0].translated_text, "Bonjour.");
        assert!(result.failed_ids.is_empty());
    }

    #[tokio::test]
    async fn failed_unit_is_reported_without_aborting_batch() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/translate"))
            .respond_with(ResponseTemplate::new(500))
            .mount(&server)
            .await;

        let provider = LibreTranslateProvider::new(&server.uri(), None).unwrap();
        let units = vec![unit("a", "Hello.")];
        let result = provider.translate_batch(&units, "english", "french").await;

        assert!(result.translations.is_empty());
        assert_eq!(result.failed_ids, vec!["a".to_string()]);
    }

    #[tokio::test]
    async fn test_connection_checks_languages_endpoint() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/languages"))
            .respond_with(ResponseTemplate::new(200))
            .mount(&server)
            .await;

        let provider = LibreTranslateProvider::new(&server.uri(), None).unwrap();
        assert!(provider.test_connection().await);
    }
}
