//! Provider credentials and app-wide settings. Port of
//! `app/views/provider_config.py`'s backend calls. Connection tests take
//! the value currently typed in a field rather than what's saved, since
//! Python's own "Test connection" button works the same way — nothing
//! here reads or writes settings.json until "Save" is pressed.

use tauri::State;

use crate::app_state::AppState;
use crate::core::translation::providers::deepl::DeepLProvider;
use crate::core::translation::providers::libretranslate::LibreTranslateProvider;
use crate::core::translation::providers::ollama::OllamaProvider;
use crate::core::translation::providers::registry;

use super::dto::{SettingsPayload, TestConnectionResult};

#[tauri::command]
pub async fn get_settings(state: State<'_, AppState>) -> Result<SettingsPayload, String> {
    let mut settings = state.settings.lock().await;
    Ok(SettingsPayload {
        locale: settings.get("locale"),
        theme: settings.get("theme"),
        default_provider: settings.get("default_provider"),
        deepl_api_key_set: settings.get("deepl_api_key").is_some_and(|v| !v.is_empty()),
        ollama_endpoint: settings.get("ollama_endpoint"),
        ollama_model: settings.get("ollama_model"),
        ollama_batch_size: settings.get("ollama_batch_size"),
        libretranslate_url: settings.get("libretranslate_url"),
        libretranslate_api_key_set: settings
            .get("libretranslate_api_key")
            .is_some_and(|v| !v.is_empty()),
        verbose_logging: settings.get("verbose_logging").as_deref() == Some("true"),
        sdk_path: settings.get("sdk_path"),
        available_providers: registry::available(&mut settings),
        available_llm_providers: registry::available_llm(&mut settings),
    })
}

#[tauri::command]
pub async fn set_setting(
    state: State<'_, AppState>,
    key: String,
    value: Option<String>,
) -> Result<(), String> {
    state
        .settings
        .lock()
        .await
        .set(&key, value.as_deref())
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn test_deepl_connection(api_key: String) -> Result<TestConnectionResult, String> {
    if api_key.trim().is_empty() {
        return Ok(TestConnectionResult {
            ok: false,
            detail: Some("No API key.".to_string()),
            models: Vec::new(),
        });
    }
    let provider = DeepLProvider::new(api_key, &[]);
    if !provider.test_connection().await {
        return Ok(TestConnectionResult {
            ok: false,
            detail: None,
            models: Vec::new(),
        });
    }
    let detail = match provider.character_usage().await {
        Ok((Some(used), Some(limit))) => Some(format!("{used}/{limit} characters used")),
        _ => None,
    };
    Ok(TestConnectionResult {
        ok: true,
        detail,
        models: Vec::new(),
    })
}

#[tauri::command]
pub async fn test_ollama_connection(endpoint: String) -> Result<TestConnectionResult, String> {
    let endpoint = if endpoint.trim().is_empty() {
        "http://localhost:11434".to_string()
    } else {
        endpoint
    };
    let provider = OllamaProvider::new(&endpoint, String::new(), None, Vec::new(), None);
    if !provider.test_connection().await {
        return Ok(TestConnectionResult {
            ok: false,
            detail: None,
            models: Vec::new(),
        });
    }
    let models = provider.list_models().await.unwrap_or_default();
    Ok(TestConnectionResult {
        ok: true,
        detail: None,
        models,
    })
}

#[tauri::command]
pub async fn test_libretranslate_connection(
    url: String,
    api_key: Option<String>,
) -> Result<TestConnectionResult, String> {
    let provider = LibreTranslateProvider::new(&url, api_key)?;
    let ok = provider.test_connection().await;
    Ok(TestConnectionResult {
        ok,
        detail: None,
        models: Vec::new(),
    })
}
