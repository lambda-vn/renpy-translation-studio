"""Tests for core/providers/claude_provider.py."""

import json

import anthropic
import httpx
import pytest

from core.translation.context_builder import MAX_UNITS_PER_BATCH
from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslationProviderError,
)
from core.translation.providers.claude_provider import ClaudeProvider


class _FakeBlock:
    def __init__(self, type_: str, text: str) -> None:
        self.type = type_
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock("text", text)]


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.reply_text: str | None = None
        self.raise_exc: Exception | None = None

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.reply_text is not None:
            return _FakeResponse(self.reply_text)
        user_prompt = str(kwargs["messages"][0]["content"])  # type: ignore[index]
        entries = [
            {"block_id": line.split("block_id: ")[1], "translation": "ok"}
            for line in user_prompt.splitlines()
            if line.startswith("block_id: ")
        ]
        return _FakeResponse(json.dumps(entries))


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _provider() -> tuple[ClaudeProvider, _FakeClient]:
    provider = ClaudeProvider(api_key="key")
    fake = _FakeClient()
    provider._client = fake  # type: ignore[assignment]
    return provider, fake


def _api_error() -> anthropic.APIError:
    return anthropic.APIError("boom", httpx.Request("POST", "http://x"), body=None)


def _auth_error() -> anthropic.AuthenticationError:
    response = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    return anthropic.AuthenticationError("bad key", response=response, body=None)


def test_translate_batch_maps_translations() -> None:
    provider, _fake = _provider()
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


def test_translate_batch_splits_into_batches() -> None:
    provider, fake = _provider()
    units = [
        {"block_id": str(i), "source_text": "hi"}
        for i in range(MAX_UNITS_PER_BATCH + 2)
    ]
    request = TranslateBatchRequest(
        units=units, source_lang="english", target_lang="french"
    )

    result = provider.translate_batch(request)

    assert len(fake.messages.calls) == 2
    assert len(result.translations) == MAX_UNITS_PER_BATCH + 2


def test_translate_batch_reports_missing_ids_as_failed() -> None:
    provider, fake = _provider()
    fake.messages.reply_text = '[{"block_id": "a", "translation": "ok"}]'
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.translations == [{"block_id": "a", "translated_text": "ok"}]
    assert result.failed_ids == ["b"]


def test_translate_batch_marks_batch_failed_on_api_error() -> None:
    provider, fake = _provider()
    fake.messages.raise_exc = _api_error()
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.translations == []
    assert result.failed_ids == ["a"]


def test_translate_batch_marks_batch_failed_on_bad_json() -> None:
    provider, fake = _provider()
    fake.messages.reply_text = "I'm sorry, I cannot translate this."
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.translations == []
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

    assert fake.messages.calls == []
    assert result.translations == []
    assert result.failed_ids == []


def test_test_connection_true_on_success() -> None:
    provider, fake = _provider()
    fake.messages.reply_text = "pong"
    assert provider.test_connection() is True


def test_test_connection_false_on_auth_error() -> None:
    provider, fake = _provider()
    fake.messages.raise_exc = _auth_error()
    assert provider.test_connection() is False


def test_test_connection_true_on_other_api_error() -> None:
    provider, fake = _provider()
    fake.messages.raise_exc = _api_error()
    assert provider.test_connection() is True


def test_complete_returns_text() -> None:
    provider, fake = _provider()
    fake.messages.reply_text = "A dark fantasy world."
    assert provider.complete("Summarize.") == "A dark fantasy world."


def test_complete_raises_provider_error_on_api_error() -> None:
    provider, fake = _provider()
    fake.messages.raise_exc = _api_error()
    with pytest.raises(TranslationProviderError):
        provider.complete("Summarize.")
