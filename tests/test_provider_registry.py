"""Tests for core/providers/registry.py."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from core.settings import Settings
from core.translation.providers.base import TranslateBatchRequest
from core.translation.providers.claude_provider import ClaudeProvider
from core.translation.providers.deepl import DeepLProvider
from core.translation.providers.libretranslate import LibreTranslateProvider
from core.translation.providers.mistral_provider import MistralProvider
from core.translation.providers.ollama import OllamaProvider
from core.translation.providers.registry import (
    ProviderRegistry,
    _parse_ollama_batch_size,
)


class _FakeResponse:
    """Stand-in for httpx.Response that skips the network entirely."""

    def __init__(self, json_data: object) -> None:
        self._json_data = json_data

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        pass


@pytest.fixture()
def fake_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Point the registry's settings reference at a fresh temp-backed instance."""
    s = Settings.__new__(Settings)
    s._config_dir = tmp_path
    s._config_file = tmp_path / "settings.json"
    s._data = {}
    s._load()
    monkeypatch.setattr("core.translation.providers.registry.settings", s)
    return s


def test_available_empty_when_not_configured(fake_settings: Settings) -> None:
    registry = ProviderRegistry()
    assert registry.available() == []


def test_available_includes_deepl_when_configured(fake_settings: Settings) -> None:
    fake_settings.set("deepl_api_key", "abc123")
    registry = ProviderRegistry()
    assert registry.available() == ["deepl"]


def test_get_raises_when_not_configured(fake_settings: Settings) -> None:
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="not configured"):
        registry.get("deepl")


def test_get_returns_deepl_provider_when_configured(fake_settings: Settings) -> None:
    fake_settings.set("deepl_api_key", "abc123")
    registry = ProviderRegistry()
    provider = registry.get("deepl")
    assert isinstance(provider, DeepLProvider)


def test_get_raises_for_unknown_provider(fake_settings: Settings) -> None:
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="Unknown provider"):
        registry.get("bogus")


def test_available_includes_ollama_when_configured(fake_settings: Settings) -> None:
    fake_settings.set("ollama_model", "llama3")
    registry = ProviderRegistry()
    assert registry.available() == ["ollama"]


def test_get_raises_when_ollama_model_not_configured(fake_settings: Settings) -> None:
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="not configured"):
        registry.get("ollama")


def test_get_returns_ollama_provider_with_context_kwargs(
    fake_settings: Settings,
) -> None:
    fake_settings.set("ollama_model", "llama3")
    registry = ProviderRegistry()
    provider = registry.get("ollama", universe_summary="A world.", characters=[])
    assert isinstance(provider, OllamaProvider)


def test_get_returns_ollama_provider_honoring_batch_size(
    fake_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The batch size setting must reach OllamaProvider's actual batching."""
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        if not json["messages"]:
            return _FakeResponse({"message": {"content": "[]"}})
        chat_payloads.append(json)
        return _FakeResponse(
            {"message": {"content": '[{"block_id": "a", "translation": "x"}]'}}
        )

    def _get(url: str, timeout: float) -> _FakeResponse:
        raise httpx.HTTPError("no /api/ps mock configured for this test")

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    monkeypatch.setattr("core.translation.providers.ollama.httpx.get", _get)
    fake_settings.set("ollama_model", "llama3")
    fake_settings.set("ollama_batch_size", "1")
    registry = ProviderRegistry()
    provider = registry.get("ollama")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )

    provider.translate_batch(request)

    assert len(chat_payloads) == 2


@pytest.mark.parametrize(
    ("setting_key", "provider_id", "provider_class"),
    [
        ("libretranslate_url", "libretranslate", LibreTranslateProvider),
        ("claude_api_key", "claude", ClaudeProvider),
        ("mistral_api_key", "mistral", MistralProvider),
    ],
)
def test_new_providers_available_and_buildable(
    fake_settings: Settings,
    setting_key: str,
    provider_id: str,
    provider_class: type,
) -> None:
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="not configured"):
        registry.get(provider_id)
    assert provider_id not in registry.available()

    fake_settings.set(setting_key, "value123")
    assert provider_id in registry.available()
    assert isinstance(registry.get(provider_id), provider_class)


def test_available_llm_excludes_non_llm_providers(fake_settings: Settings) -> None:
    fake_settings.set("deepl_api_key", "abc")
    fake_settings.set("libretranslate_url", "http://x")
    fake_settings.set("ollama_model", "llama3")
    fake_settings.set("claude_api_key", "key")
    fake_settings.set("mistral_api_key", "key")
    registry = ProviderRegistry()
    assert registry.available_llm() == ["ollama", "claude", "mistral"]


@pytest.mark.parametrize("raw", ["abc", "0", "999", None])
def test_parse_ollama_batch_size_falls_back_to_none(raw: str | None) -> None:
    assert _parse_ollama_batch_size(raw) is None


@pytest.mark.parametrize("raw", ["1", "8", "32"])
def test_parse_ollama_batch_size_accepts_bounds(raw: str) -> None:
    assert _parse_ollama_batch_size(raw) == int(raw)
