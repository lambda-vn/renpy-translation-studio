//! DeepL machine translation provider. Port of
//! `core/translation/providers/deepl.py`, talking to the DeepL REST API
//! v2 directly over `reqwest` — there is no official DeepL Rust SDK to
//! wrap the way the Python provider wraps `deepl-python`.

use std::collections::HashMap;
use std::sync::LazyLock;

use regex::Regex;
use serde::{Deserialize, Serialize};

use super::base::{
    ProviderError, TranslateBatchResult, TranslatedUnit, TranslationProvider,
    TranslationUnitPayload,
};
use crate::core::languages::get_language;
use crate::core::storage::repositories::Character;

const DEEPL_BATCH_SIZE: usize = 50;

static TERM_PAIR_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\s*(.+?)\s*(?:->|→)\s*(.+?)\s*$").unwrap());

/// Map a Ren'Py language identifier to a DeepL language code.
///
/// Identifiers declared in `core::languages` are mapped to their DeepL
/// equivalent; anything else is passed through uppercased so the API can
/// accept or reject it explicitly.
pub fn resolve_deepl_lang(code: &str) -> String {
    match get_language(code) {
        Some(lang) => lang
            .deepl
            .map(str::to_string)
            .unwrap_or_else(|| lang.iso.to_uppercase()),
        None => code.to_uppercase(),
    }
}

/// Extract glossary term pairs from character notes.
///
/// A note line of the form "Eileen -> Aline" (or with the "→" arrow)
/// declares that the source term on the left must always be translated
/// as the term on the right. Lines that don't match are ignored
/// silently — the notes field is free-form.
pub fn build_term_pairs(characters: &[Character]) -> HashMap<String, String> {
    let mut pairs = HashMap::new();
    for character in characters {
        let Some(notes) = &character.notes else {
            continue;
        };
        for line in notes.lines() {
            if let Some(caps) = TERM_PAIR_PATTERN.captures(line) {
                pairs.insert(caps[1].to_string(), caps[2].to_string());
            }
        }
    }
    pairs
}

#[derive(Serialize)]
struct TranslateRequest<'a> {
    text: &'a [&'a str],
    source_lang: &'a str,
    target_lang: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    glossary_id: Option<&'a str>,
}

#[derive(Deserialize)]
struct TranslateResponse {
    translations: Vec<TranslatedText>,
}

#[derive(Deserialize)]
struct TranslatedText {
    text: String,
}

#[derive(Deserialize)]
struct UsageResponse {
    character_count: Option<i64>,
    character_limit: Option<i64>,
}

#[derive(Serialize)]
struct CreateGlossaryRequest<'a> {
    name: &'a str,
    source_lang: &'a str,
    target_lang: &'a str,
    entries: String,
    entries_format: &'static str,
}

#[derive(Deserialize)]
struct GlossaryInfo {
    glossary_id: String,
    name: String,
}

#[derive(Deserialize)]
struct ListGlossariesResponse {
    glossaries: Vec<GlossaryInfo>,
}

pub struct DeepLProvider {
    api_key: String,
    client: reqwest::Client,
    base_url: String,
    term_pairs: HashMap<String, String>,
    glossary_id: Option<String>,
    glossary_synced: bool,
}

impl DeepLProvider {
    pub const ID: &'static str = "deepl";

    pub fn new(api_key: String, characters: &[Character]) -> Self {
        let base_url = if api_key.ends_with(":fx") {
            "https://api-free.deepl.com"
        } else {
            "https://api.deepl.com"
        }
        .to_string();
        Self {
            term_pairs: build_term_pairs(characters),
            api_key,
            client: reqwest::Client::new(),
            base_url,
            glossary_id: None,
            glossary_synced: false,
        }
    }

    /// Override the API base URL — the mocked tests' only hook, since
    /// the real endpoint is chosen from the key's `:fx` suffix.
    #[cfg(test)]
    fn with_base_url(mut self, base_url: String) -> Self {
        self.base_url = base_url;
        self
    }

    fn auth_header(&self) -> String {
        format!("DeepL-Auth-Key {}", self.api_key)
    }

    /// Upload term pairs as a DeepL glossary and return its ID. Deletes
    /// any existing glossary with the same name first, so stale
    /// glossaries never accumulate in the account.
    pub async fn sync_glossary(
        &self,
        term_pairs: &HashMap<String, String>,
        source_lang: &str,
        target_lang: &str,
    ) -> Result<String, ProviderError> {
        let source = resolve_deepl_lang(source_lang);
        let target = resolve_deepl_lang(target_lang);
        let name = format!("rts-{}-{}", source.to_lowercase(), target.to_lowercase());

        let existing: ListGlossariesResponse = self
            .client
            .get(format!("{}/v2/glossaries", self.base_url))
            .header("Authorization", self.auth_header())
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        for glossary in existing.glossaries.iter().filter(|g| g.name == name) {
            self.client
                .delete(format!(
                    "{}/v2/glossaries/{}",
                    self.base_url, glossary.glossary_id
                ))
                .header("Authorization", self.auth_header())
                .send()
                .await?
                .error_for_status()?;
        }

        let entries = term_pairs
            .iter()
            .map(|(k, v)| format!("{k}\t{v}"))
            .collect::<Vec<_>>()
            .join("\n");
        let created: GlossaryInfo = self
            .client
            .post(format!("{}/v2/glossaries", self.base_url))
            .header("Authorization", self.auth_header())
            .json(&CreateGlossaryRequest {
                name: &name,
                source_lang: &source,
                target_lang: &target,
                entries,
                entries_format: "tsv",
            })
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        Ok(created.glossary_id)
    }

    /// Sync the character term pairs as a glossary, once. A failure
    /// (unsupported language pair, quota, network) is swallowed: the
    /// batch proceeds without a glossary rather than aborting.
    async fn ensure_glossary(&mut self, source_lang: &str, target_lang: &str) {
        if self.glossary_synced || self.term_pairs.is_empty() {
            return;
        }
        self.glossary_synced = true;
        let term_pairs = self.term_pairs.clone();
        match self
            .sync_glossary(&term_pairs, source_lang, target_lang)
            .await
        {
            Ok(id) => self.glossary_id = Some(id),
            Err(_) => self.glossary_id = None,
        }
    }

    pub async fn test_connection(&self) -> bool {
        self.client
            .get(format!("{}/v2/usage", self.base_url))
            .header("Authorization", self.auth_header())
            .send()
            .await
            .and_then(reqwest::Response::error_for_status)
            .is_ok()
    }

    /// Current character usage and monthly limit. Either may be `None`
    /// if the account has no applicable limit.
    pub async fn character_usage(&self) -> Result<(Option<i64>, Option<i64>), ProviderError> {
        let usage: UsageResponse = self
            .client
            .get(format!("{}/v2/usage", self.base_url))
            .header("Authorization", self.auth_header())
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        Ok((usage.character_count, usage.character_limit))
    }

    /// Send texts to DeepL in chunks of [`DEEPL_BATCH_SIZE`].
    ///
    /// A chunk that fails reports every one of its block_ids as failed
    /// rather than aborting the whole batch.
    pub async fn translate_batch(
        &mut self,
        units: &[TranslationUnitPayload],
        source_lang: &str,
        target_lang: &str,
    ) -> TranslateBatchResult {
        self.ensure_glossary(source_lang, target_lang).await;

        let source = resolve_deepl_lang(source_lang);
        let target = resolve_deepl_lang(target_lang);
        let mut result = TranslateBatchResult::default();

        for chunk in units.chunks(DEEPL_BATCH_SIZE) {
            let texts: Vec<&str> = chunk.iter().map(|u| u.source_text.as_str()).collect();
            let response = self
                .client
                .post(format!("{}/v2/translate", self.base_url))
                .header("Authorization", self.auth_header())
                .json(&TranslateRequest {
                    text: &texts,
                    source_lang: &source,
                    target_lang: &target,
                    glossary_id: self.glossary_id.as_deref(),
                })
                .send()
                .await
                .and_then(reqwest::Response::error_for_status);

            match response {
                Ok(resp) => match resp.json::<TranslateResponse>().await {
                    Ok(parsed) if parsed.translations.len() == chunk.len() => {
                        for (unit, translated) in chunk.iter().zip(parsed.translations) {
                            result.translations.push(TranslatedUnit {
                                block_id: unit.block_id.clone(),
                                translated_text: translated.text,
                            });
                        }
                    }
                    _ => result
                        .failed_ids
                        .extend(chunk.iter().map(|u| u.block_id.clone())),
                },
                Err(_) => result
                    .failed_ids
                    .extend(chunk.iter().map(|u| u.block_id.clone())),
            }
        }

        result
    }
}

#[async_trait::async_trait]
impl TranslationProvider for DeepLProvider {
    fn id(&self) -> &'static str {
        Self::ID
    }

    async fn translate_batch(
        &mut self,
        units: &[TranslationUnitPayload],
        source_lang: &str,
        target_lang: &str,
    ) -> Result<TranslateBatchResult, ProviderError> {
        Ok(self.translate_batch(units, source_lang, target_lang).await)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn character(notes: &str) -> Character {
        Character {
            id: 1,
            variable: "e".to_string(),
            display_name: "Eileen".to_string(),
            notes: Some(notes.to_string()),
        }
    }

    #[test]
    fn resolve_deepl_lang_uses_declared_override() {
        assert_eq!(resolve_deepl_lang("tchinese"), "ZH");
        assert_eq!(resolve_deepl_lang("french"), "FR");
        assert_eq!(resolve_deepl_lang("klingon"), "KLINGON");
    }

    #[test]
    fn build_term_pairs_reads_arrow_notation() {
        let characters = vec![
            character("Eileen -> Aline\nnot a pair\nRen → Kenji"),
            character(""),
        ];
        let pairs = build_term_pairs(&characters);
        assert_eq!(pairs.get("Eileen").map(String::as_str), Some("Aline"));
        assert_eq!(pairs.get("Ren").map(String::as_str), Some("Kenji"));
        assert_eq!(pairs.len(), 2);
    }

    fn unit(block_id: &str, text: &str) -> TranslationUnitPayload {
        TranslationUnitPayload {
            block_id: block_id.to_string(),
            source_text: text.to_string(),
            character_variable: None,
        }
    }

    #[tokio::test]
    async fn translate_batch_maps_results_back_by_position() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/v2/translate"))
            .and(header("Authorization", "DeepL-Auth-Key test-key"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "translations": [
                    {"text": "Bonjour."},
                    {"text": "Au revoir."}
                ]
            })))
            .mount(&server)
            .await;

        let mut provider =
            DeepLProvider::new("test-key".to_string(), &[]).with_base_url(server.uri());
        let units = vec![unit("a", "Hello."), unit("b", "Goodbye.")];
        let result = provider.translate_batch(&units, "english", "french").await;

        assert!(result.failed_ids.is_empty());
        assert_eq!(result.translations[0].block_id, "a");
        assert_eq!(result.translations[0].translated_text, "Bonjour.");
        assert_eq!(result.translations[1].translated_text, "Au revoir.");
    }

    #[tokio::test]
    async fn translate_batch_reports_chunk_as_failed_on_error() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/v2/translate"))
            .respond_with(ResponseTemplate::new(456))
            .mount(&server)
            .await;

        let mut provider =
            DeepLProvider::new("test-key".to_string(), &[]).with_base_url(server.uri());
        let units = vec![unit("a", "Hello.")];
        let result = provider.translate_batch(&units, "english", "french").await;

        assert!(result.translations.is_empty());
        assert_eq!(result.failed_ids, vec!["a".to_string()]);
    }

    #[tokio::test]
    async fn test_connection_true_on_success() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v2/usage"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "character_count": 100, "character_limit": 500000
            })))
            .mount(&server)
            .await;

        let provider = DeepLProvider::new("test-key".to_string(), &[]).with_base_url(server.uri());
        assert!(provider.test_connection().await);
    }

    #[tokio::test]
    async fn test_connection_false_on_auth_failure() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v2/usage"))
            .respond_with(ResponseTemplate::new(403))
            .mount(&server)
            .await;

        let provider = DeepLProvider::new("bad-key".to_string(), &[]).with_base_url(server.uri());
        assert!(!provider.test_connection().await);
    }

    #[tokio::test]
    async fn character_usage_returns_counts() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v2/usage"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "character_count": 42, "character_limit": 500000
            })))
            .mount(&server)
            .await;

        let provider = DeepLProvider::new("test-key".to_string(), &[]).with_base_url(server.uri());
        let (used, limit) = provider.character_usage().await.unwrap();
        assert_eq!(used, Some(42));
        assert_eq!(limit, Some(500000));
    }

    #[tokio::test]
    async fn glossary_is_synced_once_before_first_translate() {
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v2/glossaries"))
            .respond_with(
                ResponseTemplate::new(200).set_body_json(serde_json::json!({"glossaries": []})),
            )
            .expect(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path("/v2/glossaries"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "glossary_id": "glo-1", "name": "rts-en-fr"
            })))
            .expect(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path("/v2/translate"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "translations": [{"text": "Bonjour."}]
            })))
            .mount(&server)
            .await;

        let characters = vec![character("Eileen -> Aline")];
        let mut provider =
            DeepLProvider::new("test-key".to_string(), &characters).with_base_url(server.uri());

        provider
            .translate_batch(&[unit("a", "Hello.")], "english", "french")
            .await;
        provider
            .translate_batch(&[unit("b", "Hi.")], "english", "french")
            .await;

        assert_eq!(provider.glossary_id.as_deref(), Some("glo-1"));
    }
}
