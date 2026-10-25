//! Provider credentials and app-wide settings. Port of
//! `app/views/provider_config.py`'s backend calls. Connection tests take
//! the value currently typed in a field rather than what's saved, since
//! Python's own "Test connection" button works the same way — nothing
//! here writes settings.json until "Save" is pressed. An empty key field
//! falls back on the saved key: keys are never read back into the field,
//! so without it a saved key could not be tested at all.

use std::sync::atomic::Ordering;

use tauri::State;

use crate::app_state::AppState;
use crate::core::settings::finish_onboarding;
use crate::core::storage::translation_memory;
use crate::core::translation::providers::deepl::DeepLProvider;
use crate::core::translation::providers::libretranslate::LibreTranslateProvider;
use crate::core::translation::providers::ollama::OllamaProvider;
use crate::core::translation::providers::registry;
use crate::core::validators::is_valid_sdk_path;

use super::dto::{MemoryPair, SettingsPayload, TestConnectionResult};

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
        verbose_logging: settings
            .get("verbose_logging")
            .is_some_and(|v| !v.is_empty()),
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

/// Whether this is the first launch (no settings file existed at startup
/// and the onboarding has not been finished since).
#[tauri::command]
pub async fn is_first_launch(state: State<'_, AppState>) -> Result<bool, String> {
    Ok(state.first_launch.load(Ordering::SeqCst))
}

/// Whether a path names a Ren'Py launcher (or a folder holding one), for
/// the SDK field of the onboarding and settings screens.
#[tauri::command]
pub async fn validate_sdk_path(path: String) -> Result<bool, String> {
    Ok(is_valid_sdk_path(std::path::Path::new(path.trim())))
}

/// Finish the onboarding: refuse an SDK path that is not a Ren'Py
/// launcher, then write the UI language (and the SDK path when given) so
/// the screen does not come back.
#[tauri::command]
pub async fn complete_onboarding(
    state: State<'_, AppState>,
    locale: String,
    sdk_path: Option<String>,
) -> Result<(), String> {
    finish_onboarding(
        &mut *state.settings.lock().await,
        &locale,
        sdk_path.as_deref(),
    )?;
    state.first_launch.store(false, Ordering::SeqCst);
    Ok(())
}

/// What the machine-wide translation memory holds, per language pair,
/// largest first. Empty when it cannot be read.
#[tauri::command]
pub async fn memory_stats() -> Result<Vec<MemoryPair>, String> {
    let stats = translation_memory::open(&translation_memory::default_path())
        .and_then(|memory| translation_memory::stats(&memory))
        .unwrap_or_default();
    Ok(stats
        .into_iter()
        .map(|(source_language, target_language, entries)| MemoryPair {
            source_language,
            target_language,
            entries,
        })
        .collect())
}

/// Drop everything the memory stores for one language pair; returns how
/// many entries went. Irreversible; the caller owns the confirmation.
#[tauri::command]
pub async fn forget_memory(
    source_language: String,
    target_language: String,
) -> Result<usize, String> {
    translation_memory::open(&translation_memory::default_path())
        .and_then(|memory| translation_memory::forget(&memory, &source_language, &target_language))
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn test_deepl_connection(
    state: State<'_, AppState>,
    api_key: String,
) -> Result<TestConnectionResult, String> {
    let api_key = typed_or_saved(&state, api_key, "deepl_api_key").await;
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
    state: State<'_, AppState>,
    url: String,
    api_key: Option<String>,
) -> Result<TestConnectionResult, String> {
    let api_key = Some(
        typed_or_saved(
            &state,
            api_key.unwrap_or_default(),
            "libretranslate_api_key",
        )
        .await,
    )
    .filter(|key| !key.trim().is_empty());
    let provider = LibreTranslateProvider::new(&url, api_key)?;
    let ok = provider.test_connection().await;
    Ok(TestConnectionResult {
        ok,
        detail: None,
        models: Vec::new(),
    })
}

/// The key typed in the field, or the saved one when the field is empty.
async fn typed_or_saved(state: &State<'_, AppState>, typed: String, key: &str) -> String {
    if !typed.trim().is_empty() {
        return typed;
    }
    state.settings.lock().await.get(key).unwrap_or_default()
}
