"""Tests for core/providers/mistral_provider.py."""

import json

import httpx
import pytest
from mistralai.client.errors import MistralError

from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslationProviderError,
)
from core.translation.providers.mistral_provider import MistralProvider


class _FakeMessage:
    def __init__(self, content: object) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: object) -> None:
        self.message = _FakeMessage(content)


class _FakeChatResponse:
    def __init__(self, content: object) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChat:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.reply: object | None = None
        self.raise_exc: Exception | None = None

    def complete(self, **kwargs: object) -> _FakeChatResponse:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.reply is not None:
            return _FakeChatResponse(self.reply)
        messages = kwargs["messages"]
        user_prompt = str(messages[-1]["content"])  # type: ignore[index]
        entries = [
            {"block_id": line.split("block_id: ")[1], "translation": "ok"}
            for line in user_prompt.splitlines()
            if line.startswith("block_id: ")
        ]
        return _FakeChatResponse(json.dumps(entries))


class _FakeModels:
    def __init__(self) -> None:
        self.raise_exc: Exception | None = None

    def list(self) -> object:
        if self.raise_exc is not None:
            raise self.raise_exc
        return object()


class _FakeClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()
        self.models = _FakeModels()


def _provider() -> tuple[MistralProvider, _FakeClient]:
    provider = MistralProvider(api_key="key")
    fake = _FakeClient()
    provider._client = fake  # type: ignore[assignment]
    return provider, fake


def _mistral_error() -> MistralError:
    response = httpx.Response(500, request=httpx.Request("POST", "http://x"))
    return MistralError("boom", response)


def test_translate_batch_maps_translations() -> None:
    provider, fake = _provider()
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.translations == [
        {"block_id": "a", "translated_text": "ok"},
        {"block_id": "b", "translated_text": "ok"},
    ]
    assert result.failed_ids == []
    assert fake.chat.calls[0]["response_format"] == {"type": "json_object"}


def test_translate_batch_accepts_object_wrapped_array() -> None:
    provider, fake = _provider()
    fake.chat.reply = json.dumps(
        {"translations": [{"block_id": "a", "translation": "ok"}]}
    )
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.translations == [{"block_id": "a", "translated_text": "ok"}]


def test_translate_batch_marks_batch_failed_on_api_error() -> None:
    provider, fake = _provider()
    fake.chat.raise_exc = _mistral_error()
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.translations == []
    assert result.failed_ids == ["a"]


def test_translate_batch_marks_batch_failed_on_non_text_content() -> None:
    provider, fake = _provider()
    fake.chat.reply = ["chunk"]
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.failed_ids == ["a"]


def test_translate_batch_stops_when_cancelled() -> None:
    provider, fake = _provider()
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
        is_cancelled=lambda: True,
    )

    result = provider.translate_batch(request)

    assert fake.chat.calls == []
    assert result.translations == []
    assert result.failed_ids == []


def test_test_connection_true_on_success() -> None:
    provider, _fake = _provider()
    assert provider.test_connection() is True


def test_test_connection_false_on_api_error() -> None:
    provider, fake = _provider()
    fake.models.raise_exc = _mistral_error()
    assert provider.test_connection() is False


def test_test_connection_false_on_network_error() -> None:
    provider, fake = _provider()
    fake.models.raise_exc = httpx.ConnectError("down")
    assert provider.test_connection() is False


def test_complete_returns_text_without_json_mode() -> None:
    provider, fake = _provider()
    fake.chat.reply = "A dark fantasy world."

    assert provider.complete("Summarize.") == "A dark fantasy world."
    assert fake.chat.calls[0]["response_format"] is None


def test_complete_raises_provider_error_on_api_error() -> None:
    provider, fake = _provider()
    fake.chat.raise_exc = _mistral_error()
    with pytest.raises(TranslationProviderError):
        provider.complete("Summarize.")
