//! Builds provider instances from current settings. Port of
//! `core/translation/providers/registry.py`.
//!
//! Python's registry raises `ValueError` with an `i18n.t()`-translated
//! message; nothing under `core::` carries UI strings (see
//! `core::translation::quality`'s own note on the same point), so these
//! return a [`ProviderError`], a message key the interface translates.

use super::base::{ProviderError, TranslationProvider};
use super::deepl::DeepLProvider;
use super::libretranslate::LibreTranslateProvider;
use super::ollama::OllamaProvider;
use crate::core::settings::Settings;
use crate::core::storage::repositories::Character;

pub const MIN_OLLAMA_BATCH_SIZE: i64 = 1;
pub const MAX_OLLAMA_BATCH_SIZE: i64 = 32;

pub const LLM_PROVIDER_IDS: [&str; 1] = ["ollama"];

fn non_empty(value: Option<String>) -> Option<String> {
    value.filter(|s| !s.is_empty())
}

fn parse_ollama_batch_size(value: Option<String>) -> Option<usize> {
    let parsed: i64 = value?.parse().ok()?;
    if (MIN_OLLAMA_BATCH_SIZE..=MAX_OLLAMA_BATCH_SIZE).contains(&parsed) {
        Some(parsed as usize)
    } else {
        None
    }
}

/// Build a configured provider instance for `provider_id`.
/// The Ollama provider as the settings describe it. Kept apart from [`get`]
/// for the callers that need what only an LLM does: `complete()`.
pub fn ollama(
    settings: &mut Settings,
    universe_summary: Option<String>,
    characters: Vec<Character>,
) -> Result<OllamaProvider, ProviderError> {
    let model = non_empty(settings.get("ollama_model")).ok_or(ProviderError::NotConfigured {
        provider: OllamaProvider::ID,
    })?;
    let endpoint = non_empty(settings.get("ollama_endpoint"))
        .unwrap_or_else(|| "http://localhost:11434".to_string());
    let batch_size = parse_ollama_batch_size(settings.get("ollama_batch_size"));
    Ok(OllamaProvider::new(
        &endpoint,
        model,
        universe_summary,
        characters,
        batch_size,
    ))
}

pub fn get(
    settings: &mut Settings,
    provider_id: &str,
    universe_summary: Option<String>,
    characters: Vec<Character>,
) -> Result<Box<dyn TranslationProvider>, ProviderError> {
    match provider_id {
        DeepLProvider::ID => {
            let api_key =
                non_empty(settings.get("deepl_api_key")).ok_or(ProviderError::NotConfigured {
                    provider: DeepLProvider::ID,
                })?;
            Ok(Box::new(DeepLProvider::new(api_key, &characters)))
        }
        OllamaProvider::ID => Ok(Box::new(ollama(settings, universe_summary, characters)?)),
        LibreTranslateProvider::ID => {
            let url = non_empty(settings.get("libretranslate_url")).ok_or(
                ProviderError::NotConfigured {
                    provider: LibreTranslateProvider::ID,
                },
            )?;
            let api_key = non_empty(settings.get("libretranslate_api_key"));
            LibreTranslateProvider::new(&url, api_key)
                .map(|p| Box::new(p) as Box<dyn TranslationProvider>)
        }
        other => Err(ProviderError::UnknownProvider {
            id: other.to_string(),
        }),
    }
}

/// Ids of providers that have their credentials configured.
pub fn available(settings: &mut Settings) -> Vec<&'static str> {
    let mut result = Vec::new();
    if non_empty(settings.get("deepl_api_key")).is_some() {
        result.push(DeepLProvider::ID);
    }
    if non_empty(settings.get("ollama_model")).is_some() {
        result.push(OllamaProvider::ID);
    }
    if non_empty(settings.get("libretranslate_url")).is_some() {
        result.push(LibreTranslateProvider::ID);
    }
    result
}

/// Ids of configured providers able to answer free prompts.
pub fn available_llm(settings: &mut Settings) -> Vec<&'static str> {
    available(settings)
        .into_iter()
        .filter(|id| LLM_PROVIDER_IDS.contains(id))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::sync::atomic::{AtomicU32, Ordering};

    static COUNTER: AtomicU32 = AtomicU32::new(0);

    fn temp_settings() -> Settings {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!("rts-registry-test-{n}.json"));
        let _ = fs::remove_file(&path);
        Settings::load_from(path)
    }

    #[test]
    fn unconfigured_provider_is_refused() {
        let mut settings = temp_settings();
        assert_eq!(
            get(&mut settings, "deepl", None, vec![]).err(),
            Some(ProviderError::NotConfigured { provider: "deepl" })
        );
    }

    #[test]
    fn unknown_provider_id_is_refused() {
        let mut settings = temp_settings();
        assert_eq!(
            get(&mut settings, "mistral", None, vec![]).err(),
            Some(ProviderError::UnknownProvider {
                id: "mistral".to_string()
            })
        );
    }

    #[test]
    fn provider_error_serializes_as_a_catalog_key() {
        let error = ProviderError::NotConfigured { provider: "deepl" };
        assert_eq!(
            serde_json::to_value(&error).unwrap(),
            serde_json::json!({ "key": "providers.deepl_not_configured", "params": {} })
        );
        let error = ProviderError::OllamaUnreachable {
            endpoint: "http://localhost:11434".to_string(),
        };
        assert_eq!(
            serde_json::to_value(&error).unwrap(),
            serde_json::json!({
                "key": "providers.ollama_unreachable",
                "params": { "endpoint": "http://localhost:11434" }
            })
        );
    }

    #[test]
    fn ollama_defaults_endpoint_when_unset() {
        let mut settings = temp_settings();
        settings.set("ollama_model", Some("llama3")).unwrap();
        let provider = get(&mut settings, "ollama", None, vec![]).unwrap();
        assert_eq!(provider.id(), "ollama");
    }

    #[test]
    fn available_lists_only_configured_providers() {
        let mut settings = temp_settings();
        assert!(available(&mut settings).is_empty());
        settings.set("ollama_model", Some("llama3")).unwrap();
        assert_eq!(available(&mut settings), vec!["ollama"]);
        assert_eq!(available_llm(&mut settings), vec!["ollama"]);
    }

    #[test]
    fn out_of_range_ollama_batch_size_falls_back_to_default() {
        assert_eq!(parse_ollama_batch_size(Some("0".to_string())), None);
        assert_eq!(parse_ollama_batch_size(Some("100".to_string())), None);
        assert_eq!(parse_ollama_batch_size(Some("8".to_string())), Some(8));
        assert_eq!(parse_ollama_batch_size(None), None);
    }
}
