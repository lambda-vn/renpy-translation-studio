"""Persistent application settings stored as JSON.

Settings are stored as settings.json in the machine-wide config directory,
see core.app_dirs.config_dir():
  - Linux   : ~/.config/renpy-translation-studio/
  - Windows : %LOCALAPPDATA%/renpy-translation-studio/
  - macOS   : ~/Library/Application Support/renpy-translation-studio/

API keys are stored in the OS keyring (Windows Credential Manager, macOS
Keychain, Linux Secret Service) rather than in the JSON file above. A working
keyring backend is a hard requirement for storing API keys: if none is
available, set() raises SettingsError instead of falling back to plaintext.
"""

import contextlib
import json
import logging

import keyring
import keyring.errors

from core.app_dirs import APP_NAME, config_dir

_logger = logging.getLogger(__name__)


class SettingsError(Exception):
    """Raised when a setting cannot be persisted."""


DEFAULTS: dict[str, str | None] = {
    "locale": "en",
    "sdk_path": None,
    "default_provider": None,
    "ollama_endpoint": "http://localhost:11434",
    "ollama_model": None,
    "ollama_batch_size": None,
    "libretranslate_url": None,
    "claude_model": None,
    "mistral_model": None,
    "verbose_logging": None,
}

_KEYRING_KEYS = frozenset(
    {
        "deepl_api_key",
        "libretranslate_api_key",
        "claude_api_key",
        "mistral_api_key",
    }
)

_KNOWN_KEYS = frozenset(DEFAULTS) | _KEYRING_KEYS


class Settings:
    """Read/write application settings from a JSON file and the OS keyring."""

    def __init__(self) -> None:
        """Initialize settings, loading from disk if the file exists."""
        self._config_dir = config_dir()
        self._config_file = self._config_dir / "settings.json"
        self._data: dict[str, str | None] = {}
        self._load()

    def _load(self) -> None:
        """Load settings from disk, merging with defaults for missing keys."""
        self._data = dict(DEFAULTS)
        self._keyring_available = True
        stored: dict[str, str | None] = {}
        if self._config_file.exists():
            with self._config_file.open(encoding="utf-8") as f:
                stored = json.load(f)
            self._data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        self._migrate_plaintext_api_keys(stored)

    def _migrate_plaintext_api_keys(self, stored: dict[str, str | None]) -> None:
        """Move any API keys left in plaintext JSON by a pre-keyring version."""
        migrated = False
        for key in _KEYRING_KEYS:
            plaintext_value = stored.get(key)
            if not plaintext_value:
                continue
            try:
                self._keyring_set(key, plaintext_value)
            except SettingsError:
                _logger.warning(
                    "No OS keyring backend available; '%s' could not be "
                    "migrated out of plaintext storage.",
                    key,
                )
                continue
            migrated = True
        if migrated:
            self._save()

    def _keyring_set(self, key: str, value: str | None) -> None:
        """Store or clear a value in the OS keyring.

        Raises:
            SettingsError: If no keyring backend is available.
        """
        try:
            if value:
                keyring.set_password(APP_NAME, key, value)
            else:
                with contextlib.suppress(keyring.errors.PasswordDeleteError):
                    keyring.delete_password(APP_NAME, key)
        except keyring.errors.KeyringError as exc:
            self._keyring_available = False
            raise SettingsError(
                f"No OS keyring backend available to store '{key}'."
            ) from exc

    def _save(self) -> None:
        """Persist current settings to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with self._config_file.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, key: str) -> str | None:
        """Return the value for the given key, or None if not set.

        Args:
            key: Setting key to retrieve.

        Returns:
            The stored value, or None.
        """
        if key in _KEYRING_KEYS:
            if not self._keyring_available:
                return None
            try:
                return keyring.get_password(APP_NAME, key)
            except keyring.errors.KeyringError:
                self._keyring_available = False
                return None
        return self._data.get(key)

    def set(self, key: str, value: str | None) -> None:
        """Update a setting and persist it immediately.

        API keys are written to the OS keyring rather than settings.json.

        Args:
            key: Setting key to update.
            value: New value, or None to clear.

        Raises:
            KeyError: If the key is not a known setting.
            SettingsError: If the key is an API key and no keyring backend
                is available to store it.
        """
        if key not in _KNOWN_KEYS:
            raise KeyError(f"Unknown setting key: {key}")
        if key in _KEYRING_KEYS:
            self._keyring_set(key, value)
            return
        self._data[key] = value
        self._save()

    @property
    def is_first_launch(self) -> bool:
        """True if the settings file does not exist yet."""
        return not self._config_file.exists()


settings = Settings()
