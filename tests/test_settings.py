"""Unit tests for core.settings.Settings."""

import json
from pathlib import Path

import keyring.errors
import pytest

from core import settings as settings_module
from core.settings import DEFAULTS, Settings, SettingsError
from tests.conftest import FakeKeyring


class _NoBackendKeyring:
    """Stand-in simulating an environment with no keyring backend available."""

    errors = keyring.errors

    def get_password(self, service: str, username: str) -> str | None:
        """Always raise, as if no backend could handle the request."""
        raise keyring.errors.NoKeyringError("no backend")

    def set_password(self, service: str, username: str, password: str) -> None:
        """Always raise, as if no backend could handle the request."""
        raise keyring.errors.NoKeyringError("no backend")

    def delete_password(self, service: str, username: str) -> None:
        """Always raise, as if no backend could handle the request."""
        raise keyring.errors.NoKeyringError("no backend")


@pytest.fixture()
def tmp_settings(tmp_path: Path, fake_keyring: FakeKeyring) -> Settings:
    """Return a fresh Settings instance backed by a temporary directory."""
    s = Settings.__new__(Settings)
    s._config_dir = tmp_path
    s._config_file = tmp_path / "settings.json"
    s._data = {}
    s._load()
    return s


def _reload(original: Settings) -> Settings:
    """Build a second Settings instance pointed at the same config file."""
    reload = Settings.__new__(Settings)
    reload._config_dir = original._config_dir
    reload._config_file = original._config_file
    reload._data = {}
    reload._load()
    return reload


def test_first_launch_true_when_no_file(tmp_settings: Settings) -> None:
    """is_first_launch is True when the settings file does not exist."""
    assert tmp_settings.is_first_launch is True


def test_first_launch_false_after_set(tmp_settings: Settings) -> None:
    """is_first_launch is False after any setting is persisted."""
    tmp_settings.set("locale", "en")
    assert tmp_settings.is_first_launch is False


def test_default_returned_for_unset_key(tmp_settings: Settings) -> None:
    """Default values are returned when no file exists."""
    assert tmp_settings.get("locale") == DEFAULTS["locale"]
    assert tmp_settings.get("sdk_path") == DEFAULTS["sdk_path"]


def test_set_persists_to_disk(tmp_settings: Settings) -> None:
    """set() writes the value to disk so a fresh instance reads it back."""
    tmp_settings.set("locale", "fr")

    assert _reload(tmp_settings).get("locale") == "fr"


def test_set_persists_none(tmp_settings: Settings) -> None:
    """set() with None writes null and is read back as None."""
    tmp_settings.set("sdk_path", "/some/path")
    tmp_settings.set("sdk_path", None)

    assert _reload(tmp_settings).get("sdk_path") is None


def test_unknown_key_raises(tmp_settings: Settings) -> None:
    """set() with an unknown key raises KeyError."""
    with pytest.raises(KeyError, match="Unknown setting key"):
        tmp_settings.set("nonexistent", "value")


def test_extra_keys_in_file_ignored(tmp_settings: Settings) -> None:
    """Unknown keys in the JSON file are ignored during load."""
    tmp_settings._config_dir.mkdir(parents=True, exist_ok=True)
    payload = {"locale": "fr", "unknown_key": "garbage"}
    tmp_settings._config_file.write_text(json.dumps(payload), encoding="utf-8")
    tmp_settings._load()
    assert tmp_settings.get("locale") == "fr"
    assert tmp_settings.get("sdk_path") == DEFAULTS["sdk_path"]


def test_api_key_set_goes_to_keyring_not_json(
    tmp_settings: Settings, fake_keyring: FakeKeyring
) -> None:
    """API keys are stored in the keyring, and never written to settings.json."""
    tmp_settings.set("locale", "fr")
    tmp_settings.set("claude_api_key", "sk-secret")

    assert fake_keyring.get_password(settings_module.APP_NAME, "claude_api_key") == (
        "sk-secret"
    )
    on_disk = json.loads(tmp_settings._config_file.read_text(encoding="utf-8"))
    assert "claude_api_key" not in on_disk


def test_api_key_set_alone_creates_no_settings_file(
    tmp_settings: Settings,
) -> None:
    """Setting only an API key never touches settings.json at all."""
    tmp_settings.set("claude_api_key", "sk-secret")

    assert not tmp_settings._config_file.exists()


def test_api_key_get_reads_from_keyring(tmp_settings: Settings) -> None:
    """get() for an API key returns the value stored in the keyring."""
    tmp_settings.set("mistral_api_key", "m-secret")

    assert _reload(tmp_settings).get("mistral_api_key") == "m-secret"


def test_api_key_cleared_with_none(tmp_settings: Settings) -> None:
    """Setting an API key to None removes it from the keyring."""
    tmp_settings.set("deepl_api_key", "d-secret")
    tmp_settings.set("deepl_api_key", None)

    assert tmp_settings.get("deepl_api_key") is None


def test_plaintext_api_key_migrated_to_keyring_on_load(
    tmp_path: Path, fake_keyring: FakeKeyring
) -> None:
    """An API key left in plaintext JSON by an older version is migrated."""
    config_file = tmp_path / "settings.json"
    config_file.write_text(
        json.dumps({"claude_api_key": "old-plaintext-key"}), encoding="utf-8"
    )

    s = Settings.__new__(Settings)
    s._config_dir = tmp_path
    s._config_file = config_file
    s._data = {}
    s._load()

    assert s.get("claude_api_key") == "old-plaintext-key"
    assert (
        fake_keyring.get_password(settings_module.APP_NAME, "claude_api_key")
        == "old-plaintext-key"
    )
    on_disk = json.loads(config_file.read_text(encoding="utf-8"))
    assert "claude_api_key" not in on_disk


def test_keyring_unavailable_raises_on_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a keyring backend, set() raises instead of storing in plaintext."""
    monkeypatch.setattr(settings_module, "keyring", _NoBackendKeyring())

    s = Settings.__new__(Settings)
    s._config_dir = tmp_path
    s._config_file = tmp_path / "settings.json"
    s._data = {}
    s._load()

    with pytest.raises(SettingsError):
        s.set("claude_api_key", "some-key")

    assert s.get("claude_api_key") is None
    assert not s._config_file.exists()


def test_keyring_unavailable_leaves_legacy_plaintext_key_unmigrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-keyring plaintext key is left alone if migration cannot succeed."""
    config_file = tmp_path / "settings.json"
    config_file.write_text(
        json.dumps({"claude_api_key": "old-plaintext-key"}), encoding="utf-8"
    )
    monkeypatch.setattr(settings_module, "keyring", _NoBackendKeyring())

    s = Settings.__new__(Settings)
    s._config_dir = tmp_path
    s._config_file = config_file
    s._data = {}
    s._load()

    assert s.get("claude_api_key") is None
