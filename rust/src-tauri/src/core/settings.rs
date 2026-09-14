//! Persistent application settings stored as JSON.
//!
//! Port of `core/settings.py`. Settings are stored as `settings.json` in
//! the machine-wide config directory, the same one the 1.0.0 Python
//! application already writes to — this file is part of the frozen
//! contract in `CLAUDE.md`'s compatibility policy, not a fresh format.
//!
//! API keys are stored in the OS keyring (Windows Credential Manager,
//! macOS Keychain, Linux Secret Service) rather than in the JSON file.
//! A working keyring backend is a hard requirement for storing API keys:
//! if none is available, `set()` returns [`SettingsError`] instead of
//! falling back to plaintext.

use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

use keyring::Entry;

pub const APP_NAME: &str = "renpy-translation-studio";

const DEFAULTS: &[(&str, Option<&str>)] = &[
    ("locale", Some("en")),
    ("theme", Some("system")),
    ("sdk_path", None),
    ("default_provider", None),
    ("ollama_endpoint", Some("http://localhost:11434")),
    ("ollama_model", None),
    ("ollama_batch_size", None),
    ("libretranslate_url", None),
    ("verbose_logging", None),
];

const KEYRING_KEYS: &[&str] = &["deepl_api_key", "libretranslate_api_key"];

#[derive(Debug, thiserror::Error)]
pub enum SettingsError {
    #[error("unknown setting key: {0}")]
    UnknownKey(String),
    #[error("no OS keyring backend available to store '{0}'")]
    KeyringUnavailable(String),
}

/// Read/write application settings from a JSON file and the OS keyring.
pub struct Settings {
    config_file: PathBuf,
    data: HashMap<String, Option<String>>,
    keyring_available: bool,
}

impl Settings {
    /// Load settings from the machine-wide config directory.
    pub fn load() -> Self {
        let config_file = config_dir().join("settings.json");
        Self::load_from(config_file)
    }

    /// Load settings from an explicit config file path.
    ///
    /// The general entry point is [`Settings::load`]; this exists so
    /// tests can point at a temporary file without touching the real
    /// machine-wide config.
    pub fn load_from(config_file: PathBuf) -> Self {
        let mut settings = Self {
            config_file,
            data: DEFAULTS
                .iter()
                .map(|(k, v)| (k.to_string(), v.map(str::to_string)))
                .collect(),
            keyring_available: true,
        };
        settings.reload();
        settings
    }

    /// Re-read the config file from disk, merging with defaults for
    /// missing keys.
    pub fn reload(&mut self) {
        self.data = DEFAULTS
            .iter()
            .map(|(k, v)| (k.to_string(), v.map(str::to_string)))
            .collect();
        self.keyring_available = true;

        let Ok(contents) = fs::read_to_string(&self.config_file) else {
            return;
        };
        let Ok(stored) = serde_json::from_str::<HashMap<String, Option<String>>>(&contents) else {
            return;
        };
        for (key, value) in &stored {
            if DEFAULTS.iter().any(|(k, _)| k == key) {
                self.data.insert(key.clone(), value.clone());
            }
        }
        self.migrate_plaintext_api_keys(&stored);
    }

    /// Move any API keys left in plaintext JSON by a pre-keyring version.
    fn migrate_plaintext_api_keys(&mut self, stored: &HashMap<String, Option<String>>) {
        let mut migrated = false;
        for key in KEYRING_KEYS {
            let Some(Some(plaintext_value)) = stored.get(*key) else {
                continue;
            };
            if self.keyring_set(key, Some(plaintext_value)).is_ok() {
                migrated = true;
            }
        }
        if migrated {
            self.save();
        }
    }

    fn keyring_set(&mut self, key: &str, value: Option<&str>) -> Result<(), SettingsError> {
        let entry = Entry::new(APP_NAME, key)
            .map_err(|_| SettingsError::KeyringUnavailable(key.to_string()))?;
        let result = match value {
            Some(v) if !v.is_empty() => entry.set_password(v),
            _ => entry.delete_credential().or(Ok(())),
        };
        result.map_err(|_| {
            self.keyring_available = false;
            SettingsError::KeyringUnavailable(key.to_string())
        })
    }

    fn save(&self) {
        if let Some(parent) = self.config_file.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if let Ok(json) = serde_json::to_string_pretty(&self.data) {
            let _ = fs::write(&self.config_file, json);
        }
    }

    /// Return the value for the given key, or `None` if not set.
    pub fn get(&mut self, key: &str) -> Option<String> {
        if KEYRING_KEYS.contains(&key) {
            if !self.keyring_available {
                return None;
            }
            let Ok(entry) = Entry::new(APP_NAME, key) else {
                return None;
            };
            return match entry.get_password() {
                Ok(v) => Some(v),
                Err(keyring::Error::NoEntry) => None,
                Err(_) => {
                    self.keyring_available = false;
                    None
                }
            };
        }
        self.data.get(key).cloned().flatten()
    }

    /// Update a setting and persist it immediately.
    ///
    /// API keys are written to the OS keyring rather than `settings.json`.
    pub fn set(&mut self, key: &str, value: Option<&str>) -> Result<(), SettingsError> {
        if KEYRING_KEYS.contains(&key) {
            return self.keyring_set(key, value);
        }
        if !DEFAULTS.iter().any(|(k, _)| *k == key) {
            return Err(SettingsError::UnknownKey(key.to_string()));
        }
        self.data.insert(key.to_string(), value.map(str::to_string));
        self.save();
        Ok(())
    }

    /// `true` if the settings file does not exist yet.
    pub fn is_first_launch(&self) -> bool {
        !self.config_file.exists()
    }
}

/// The directory holding the machine-wide application files: settings,
/// the recent-project registry, and the translation memory.
///
/// Matches the 1.0.0 Python application's `platformdirs.user_config_dir(
/// APP_NAME, appauthor=False)` exactly — no separate author segment —
/// since this directory, and everything in it, is part of the frozen
/// data contract:
///   - Linux   : `~/.config/renpy-translation-studio/`
///   - Windows : `%LOCALAPPDATA%/renpy-translation-studio/`
///   - macOS   : `~/Library/Application Support/renpy-translation-studio/`
pub fn config_dir() -> PathBuf {
    dirs::config_local_dir()
        .expect("no config directory on this platform")
        .join(APP_NAME)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    static COUNTER: AtomicU32 = AtomicU32::new(0);

    fn temp_settings() -> Settings {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!("rts-settings-test-{n}.json"));
        let _ = fs::remove_file(&path);
        Settings::load_from(path)
    }

    #[test]
    fn default_returned_for_unset_key() {
        let mut s = temp_settings();
        assert_eq!(s.get("locale").as_deref(), Some("en"));
        assert_eq!(s.get("sdk_path"), None);
    }

    #[test]
    fn set_persists_to_disk() {
        let mut s = temp_settings();
        s.set("locale", Some("fr")).unwrap();

        let mut reloaded = Settings::load_from(s.config_file.clone());
        assert_eq!(reloaded.get("locale").as_deref(), Some("fr"));
    }

    #[test]
    fn set_persists_none() {
        let mut s = temp_settings();
        s.set("sdk_path", Some("/some/path")).unwrap();
        s.set("sdk_path", None).unwrap();

        let mut reloaded = Settings::load_from(s.config_file.clone());
        assert_eq!(reloaded.get("sdk_path"), None);
    }

    #[test]
    fn unknown_key_is_rejected() {
        let mut s = temp_settings();
        assert!(matches!(
            s.set("nonexistent", Some("value")),
            Err(SettingsError::UnknownKey(_))
        ));
    }

    #[test]
    fn extra_keys_in_file_are_ignored() {
        let mut s = temp_settings();
        fs::write(&s.config_file, r#"{"locale":"fr","unknown_key":"garbage"}"#).unwrap();
        s.reload();
        assert_eq!(s.get("locale").as_deref(), Some("fr"));
        assert_eq!(s.get("sdk_path").as_deref(), None);
    }

    #[test]
    fn first_launch_is_false_after_set() {
        let mut s = temp_settings();
        assert!(s.is_first_launch());
        s.set("locale", Some("en")).unwrap();
        assert!(!s.is_first_launch());
    }
}
