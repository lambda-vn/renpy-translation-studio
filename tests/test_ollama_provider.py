"""Tests for core/providers/ollama.py."""

import json as json_module
from typing import Any

import httpx
import pytest

from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslationProviderError,
)
from core.translation.providers.ollama import (
    COMPLETION_MAX_TOKENS,
    COMPLETION_TEMPERATURE,
    DEFAULT_CONTEXT_LENGTH,
    MAX_NUM_CTX,
    TRANSLATION_TEMPERATURE,
    OllamaProvider,
    _drop_duplicate_content,
    is_cloud_model,
)


class _FakeResponse:
    """Stand-in for httpx.Response that skips the network entirely."""

    def __init__(self, json_data: object, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError("boom")


@pytest.fixture(autouse=True)
def _stub_ps_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent the CPU-offload check from making a real network call.

    translate_batch() now calls GET /api/ps after preloading the model.
    Tests that don't care about that check would otherwise hit a real
    (and unreachable) network address. Tests exercising the CPU-offload
    warning override httpx.get themselves, which simply replaces this.
    """

    def _get(url: str, timeout: float) -> _FakeResponse:
        raise httpx.HTTPError("no /api/ps mock configured for this test")

    monkeypatch.setattr(
        "core.translation.providers.ollama.httpx.get", _get, raising=False
    )


def test_test_connection_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.translation.providers.ollama.httpx.get",
        lambda url, timeout: _FakeResponse({}, status_code=200),
    )
    provider = OllamaProvider(endpoint="http://localhost:11434", model="llama3")
    assert provider.test_connection() is True


def test_test_connection_false_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(url: str, timeout: float) -> _FakeResponse:
        raise httpx.HTTPError("unreachable")

    monkeypatch.setattr("core.translation.providers.ollama.httpx.get", _raise)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="llama3")
    assert provider.test_connection() is False


def test_list_models_returns_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.translation.providers.ollama.httpx.get",
        lambda url, timeout: _FakeResponse(
            {"models": [{"name": "llama3"}, {"name": "mistral"}]}
        ),
    )
    provider = OllamaProvider(endpoint="http://localhost:11434", model="llama3")
    assert provider.list_models() == ["llama3", "mistral"]


@pytest.mark.parametrize(
    ("architecture", "key_suffix"),
    [("llama", "llama.context_length"), ("qwen2", "qwen2.context_length")],
)
def test_get_context_length_parses_architecture(
    monkeypatch: pytest.MonkeyPatch, architecture: str, key_suffix: str
) -> None:
    monkeypatch.setattr(
        "core.translation.providers.ollama.httpx.post",
        lambda url, json, timeout: _FakeResponse(
            {"model_info": {"general.architecture": architecture, key_suffix: 8192}}
        ),
    )
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    assert provider.get_context_length("m") == 8192


def test_get_context_length_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.translation.providers.ollama.httpx.post",
        lambda url, json, timeout: _FakeResponse({"model_info": {}}),
    )
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    assert provider.get_context_length("m") == DEFAULT_CONTEXT_LENGTH


def test_translate_batch_caps_num_ctx_to_max_when_model_context_is_larger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse(
                {
                    "model_info": {
                        "general.architecture": "llama",
                        "llama.context_length": 131072,
                    }
                }
            )
        chat_payloads.append(json)
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    provider.translate_batch(request)

    assert chat_payloads[0]["options"]["num_ctx"] == MAX_NUM_CTX


def test_translate_batch_keeps_num_ctx_when_model_context_is_smaller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse(
                {
                    "model_info": {
                        "general.architecture": "llama",
                        "llama.context_length": 4096,
                    }
                }
            )
        chat_payloads.append(json)
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    provider.translate_batch(request)

    assert chat_payloads[0]["options"]["num_ctx"] == 4096


def test_translate_batch_uses_custom_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured batch_size must cap units per request, not just the default."""
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        if not json["messages"]:
            return _FakeResponse({"message": {"content": "[]"}})
        chat_payloads.append(json)
        block_id = json["messages"][1]["content"].split("block_id: ")[1].split("\n")[0]
        content = json_module.dumps([{"block_id": block_id, "translation": "x"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(
        endpoint="http://localhost:11434", model="m", batch_size=1
    )
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)

    assert len(chat_payloads) == 2
    assert result.failed_ids == []


def test_translate_batch_wraps_unreachable_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        raise httpx.HTTPError("unreachable")

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    with pytest.raises(TranslationProviderError):
        provider.translate_batch(request)


def test_translate_batch_returns_translations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == []


def test_translate_batch_unwraps_object_wrapped_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Small models often wrap the array in an object despite instructions."""

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps(
            {"translations": [{"block_id": "a", "translation": "Bonjour"}]}
        )
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == []


def test_translate_batch_accepts_id_instead_of_block_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some models use "id" instead of the requested "block_id" key."""

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps({"blocks": [{"id": "a", "translation": "Bonjour"}]})
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == []


def test_translate_batch_one_malformed_item_does_not_fail_whole_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One item missing a usable id must not lose the rest of the batch."""

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps(
            [
                {"block_id": "a", "translation": "Bonjour"},
                {"unexpected": "shape"},
            ]
        )
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == ["b"]


def test_translate_batch_wraps_bare_single_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that only translated the first unit may skip the array wrapper."""

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps({"block_id": "a", "translation": "Bonjour"})
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == ["b"]


def test_translate_batch_marks_missing_block_ids_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model returning fewer entries than requested must not lose units."""

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == ["b"]


def test_translate_batch_ignores_hallucinated_block_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra block_ids the model invents must not inflate the result."""

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps(
            [
                {"block_id": "a", "translation": "Bonjour"},
                {"block_id": "ghost", "translation": "???"},
            ]
        )
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == []


def test_translate_batch_requests_json_schema_and_low_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        if not json["messages"]:
            return _FakeResponse({"message": {"content": "[]"}})
        chat_payloads.append(json)
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    provider.translate_batch(request)

    assert len(chat_payloads) == 1
    assert isinstance(chat_payloads[0]["format"], dict)
    assert chat_payloads[0]["format"]["type"] == "array"
    assert chat_payloads[0]["format"]["minItems"] == 1
    assert chat_payloads[0]["format"]["maxItems"] == 1
    assert chat_payloads[0]["options"]["temperature"] == TRANSLATION_TEMPERATURE


def test_translate_batch_pins_array_length_to_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The schema must require exactly len(batch) entries, not just >=1.

    Without minItems/maxItems set to the batch size, a model can legally
    satisfy the schema after a single entry — small quantized models
    reliably do exactly that on longer batches instead of covering every
    requested unit.
    """
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        if not json["messages"]:
            return _FakeResponse({"message": {"content": "[]"}})
        chat_payloads.append(json)
        content = json_module.dumps([{"block_id": "a", "translation": "x"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
            {"block_id": "c", "source_text": "Again"},
        ],
        source_lang="english",
        target_lang="french",
    )
    provider.translate_batch(request)

    assert chat_payloads[0]["format"]["minItems"] == 3
    assert chat_payloads[0]["format"]["maxItems"] == 3


def test_translate_batch_stops_before_any_request_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preload still fires once, but no real translation request is sent.

    The cancellation check lives in the per-batch loop, not before the
    one-time preload — the model gets loaded regardless, but the loop
    breaks before sending any request built from the actual units.
    """
    post_urls: list[str] = []

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        post_urls.append(url)
        return _FakeResponse({"model_info": {}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
        is_cancelled=lambda: True,
    )
    result = provider.translate_batch(request)
    chat_urls = [url for url in post_urls if "chat" in url]
    assert len(chat_urls) == 1
    assert result.translations == []
    assert result.failed_ids == []


def test_translate_batch_cancelled_after_first_batch_keeps_its_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_index = [0]

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse(
                {
                    "model_info": {
                        "general.architecture": "llama",
                        "llama.context_length": 60,
                    }
                }
            )
        if not json["messages"]:
            return _FakeResponse({"message": {"content": "[]"}})
        block_id = str(call_index[0])
        call_index[0] += 1
        content = json_module.dumps([{"block_id": block_id, "translation": "y"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    units = [
        {"block_id": str(i), "source_text": f"hello world number {i}"} for i in range(5)
    ]
    cancelled_after_first_check = [False]

    def _is_cancelled() -> bool:
        was_cancelled = cancelled_after_first_check[0]
        cancelled_after_first_check[0] = True
        return was_cancelled

    request = TranslateBatchRequest(
        units=units,
        source_lang="english",
        target_lang="french",
        is_cancelled=_is_cancelled,
    )
    result = provider.translate_batch(request)
    assert 1 <= len(result.translations) < len(units)


def test_translate_batch_marks_failed_when_object_has_no_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps({"note": "no translations here"})
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == []
    assert result.failed_ids == ["a"]


def test_translate_batch_marks_failed_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        return _FakeResponse({"message": {"content": "not json"}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == []
    assert result.failed_ids == ["a"]


class TestDropDuplicateContent:
    """Tests for _drop_duplicate_content."""

    def test_drops_long_duplicate_across_different_sources(self) -> None:
        translations = [
            {"block_id": "a", "translated_text": "Créé avec Ren'Py, merci !"},
            {"block_id": "b", "translated_text": "Créé avec Ren'Py, merci !"},
        ]
        source_by_id = {"a": "Made with Ren'Py, thanks!", "b": "Load"}

        kept, dropped = _drop_duplicate_content(translations, source_by_id)

        assert kept == []
        assert dropped == ["a", "b"]

    def test_keeps_short_coincidental_match(self) -> None:
        translations = [
            {"block_id": "a", "translated_text": "Oui"},
            {"block_id": "b", "translated_text": "Oui"},
        ]
        source_by_id = {"a": "Yes", "b": "Yeah"}

        kept, dropped = _drop_duplicate_content(translations, source_by_id)

        assert kept == translations
        assert dropped == []

    def test_keeps_duplicate_when_sources_are_the_same(self) -> None:
        """Two units that genuinely share the same source text may share

        the same translation too — that's not padding.
        """
        translations = [
            {"block_id": "a", "translated_text": "Chargement rapide"},
            {"block_id": "b", "translated_text": "Chargement rapide"},
        ]
        source_by_id = {"a": "Quick Load", "b": "Quick Load"}

        kept, dropped = _drop_duplicate_content(translations, source_by_id)

        assert kept == translations
        assert dropped == []

    def test_no_duplicates_returns_all(self) -> None:
        translations = [
            {"block_id": "a", "translated_text": "Bonjour"},
            {"block_id": "b", "translated_text": "Au revoir"},
        ]
        source_by_id = {"a": "Hello", "b": "Goodbye"}

        kept, dropped = _drop_duplicate_content(translations, source_by_id)

        assert kept == translations
        assert dropped == []


def test_translate_batch_drops_padded_duplicate_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration case reproducing the observed padding failure mode.

    Ollama, forced by minItems/maxItems to fill every slot, copied the
    translation for "Made with Ren'Py..." onto the unrelated "Load" unit
    instead of translating it. The duplicate must be dropped rather than
    accepted as ai_suggested content for the wrong unit.
    """

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps(
            [
                {"block_id": "credits", "translation": "Créé avec Ren'Py, merci !"},
                {"block_id": "load", "translation": "Créé avec Ren'Py, merci !"},
            ]
        )
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "credits", "source_text": "Made with Ren'Py, thanks!"},
            {"block_id": "load", "source_text": "Load"},
        ],
        source_lang="english",
        target_lang="french",
    )

    result = provider.translate_batch(request)

    assert result.translations == []
    assert sorted(result.failed_ids) == ["credits", "load"]


def test_translate_batch_marks_failed_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        raise httpx.HTTPError("boom")

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)
    assert result.translations == []
    assert result.failed_ids == ["a"]


def test_preload_sends_empty_messages_with_matching_num_ctx_and_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preload_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse(
                {
                    "model_info": {
                        "general.architecture": "llama",
                        "llama.context_length": 4096,
                    }
                }
            )
        if not json["messages"]:
            preload_payloads.append(json)
            return _FakeResponse({"message": {"content": "[]"}})
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    events: list[str] = []
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
        on_event=events.append,
    )
    provider.translate_batch(request)

    assert len(preload_payloads) == 1
    assert preload_payloads[0]["messages"] == []
    assert preload_payloads[0]["options"]["num_ctx"] == 4096
    assert any("Loading" in e for e in events)


def test_cpu_offload_warning_emitted_once_across_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warning must fire once per job, not once per translate_batch call."""

    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    def _get(url: str, timeout: float) -> _FakeResponse:
        return _FakeResponse({"models": [{"name": "m", "size": 10, "size_vram": 6}]})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    monkeypatch.setattr("core.translation.providers.ollama.httpx.get", _get)
    events: list[str] = []
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    for _ in range(2):
        request = TranslateBatchRequest(
            units=[{"block_id": "a", "source_text": "Hello"}],
            source_lang="english",
            target_lang="french",
            on_event=events.append,
        )
        provider.translate_batch(request)

    warnings = [e for e in events if "CPU" in e]
    assert len(warnings) == 1
    assert "40%" in warnings[0]


def test_no_cpu_offload_warning_at_full_vram_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    def _get(url: str, timeout: float) -> _FakeResponse:
        return _FakeResponse({"models": [{"name": "m", "size": 10, "size_vram": 10}]})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    monkeypatch.setattr("core.translation.providers.ollama.httpx.get", _get)
    events: list[str] = []
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
        on_event=events.append,
    )
    provider.translate_batch(request)

    assert not any("CPU" in e for e in events)


def test_ps_unreachable_does_not_crash_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: object, timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse({"model_info": {}})
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    def _get(url: str, timeout: float) -> _FakeResponse:
        raise httpx.HTTPError("unreachable")

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    monkeypatch.setattr("core.translation.providers.ollama.httpx.get", _get)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="m")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = provider.translate_batch(request)

    assert result.translations == [{"block_id": "a", "translated_text": "Bonjour"}]
    assert result.failed_ids == []


def test_a_cloud_model_keeps_its_whole_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAX_NUM_CTX guards this machine's VRAM, which a cloud model never uses.

    Capping it there only shrinks the batches: split_into_batches takes
    the system prompt and the output margin out of num_ctx, and a rich
    universe summary can leave room for one unit instead of eight.
    """
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse(
                {
                    "model_info": {
                        "general.architecture": "llama",
                        "llama.context_length": 131072,
                    }
                }
            )
        chat_payloads.append(json)
        content = json_module.dumps([{"block_id": "a", "translation": "Bonjour"}])
        return _FakeResponse({"message": {"content": content}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(
        endpoint="http://localhost:11434", model="gpt-oss:120b-cloud"
    )
    provider.translate_batch(
        TranslateBatchRequest(
            units=[{"block_id": "a", "source_text": "Hello"}],
            source_lang="english",
            target_lang="french",
        )
    )

    assert chat_payloads[0]["options"]["num_ctx"] == 131072


def test_is_cloud_model_reads_the_suffix() -> None:
    assert is_cloud_model("gpt-oss:120b-cloud")
    assert is_cloud_model("qwen3-coder:480b-cloud")
    assert not is_cloud_model("mistral:7b")
    assert not is_cloud_model("cloud-atlas:3b")


def test_complete_pins_the_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    chat_payloads: list[dict[str, Any]] = []

    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if "show" in url:
            return _FakeResponse(
                {
                    "model_info": {
                        "general.architecture": "gemma3",
                        "gemma3.context_length": 8192,
                    }
                }
            )
        chat_payloads.append(json)
        return _FakeResponse({"message": {"content": "A brief."}})

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="gemma3:1b")

    assert provider.complete("Describe this game.") == "A brief."
    assert chat_payloads[0]["options"]["temperature"] == COMPLETION_TEMPERATURE
    assert chat_payloads[0]["options"]["num_predict"] == COMPLETION_MAX_TOKENS
    assert chat_payloads[0]["options"]["num_ctx"] == 8192


def test_complete_raises_on_unreachable_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        raise httpx.HTTPError("unreachable")

    monkeypatch.setattr("core.translation.providers.ollama.httpx.post", _post)
    provider = OllamaProvider(endpoint="http://localhost:11434", model="gemma3:1b")

    with pytest.raises(TranslationProviderError):
        provider.complete("Describe this game.")
