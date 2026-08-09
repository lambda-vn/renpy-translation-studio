"""Tests for core/providers/libretranslate.py."""

from typing import Any

import httpx
import pytest

from core.translation.providers.base import TranslateBatchRequest
from core.translation.providers.libretranslate import (
    LibreTranslateProvider,
    resolve_libretranslate_lang,
    strip_added_whitespace,
)


class _FakeResponse:
    def __init__(self, json_data: object, status_code: int = 200) -> None:
        self._json_data = json_data
        self.status_code = status_code

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=None,
                response=None,  # type: ignore[arg-type]
            )


def test_endpoint_is_required() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        LibreTranslateProvider(endpoint="")


def test_resolve_libretranslate_lang() -> None:
    assert resolve_libretranslate_lang("french") == "fr"
    assert resolve_libretranslate_lang("SCHINESE") == "zh"
    assert resolve_libretranslate_lang("EO") == "eo"


def test_translate_batch_one_request_per_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict[str, str]] = []

    def _post(url: str, json: dict[str, str], timeout: float) -> _FakeResponse:
        payloads.append(json)
        return _FakeResponse({"translatedText": f"{json['q']}-fr"})

    monkeypatch.setattr("core.translation.providers.libretranslate.httpx.post", _post)
    p = LibreTranslateProvider(endpoint="http://localhost:5000")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )

    result = p.translate_batch(request)

    assert len(payloads) == 2
    assert payloads[0] == {
        "q": "Hello",
        "source": "en",
        "target": "fr",
        "format": "text",
    }
    assert result.translations == [
        {"block_id": "a", "translated_text": "Hello-fr"},
        {"block_id": "b", "translated_text": "World-fr"},
    ]
    assert result.failed_ids == []


def test_api_key_omitted_when_unset_and_sent_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict[str, str]] = []

    def _post(url: str, json: dict[str, str], timeout: float) -> _FakeResponse:
        payloads.append(json)
        return _FakeResponse({"translatedText": "x"})

    monkeypatch.setattr("core.translation.providers.libretranslate.httpx.post", _post)
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    LibreTranslateProvider(endpoint="http://x").translate_batch(request)
    LibreTranslateProvider(endpoint="http://x", api_key="secret").translate_batch(
        request
    )

    assert "api_key" not in payloads[0]
    assert payloads[1]["api_key"] == "secret"


def test_strip_added_whitespace_removes_provider_line_breaks() -> None:
    assert strip_added_whitespace("Hello", "\nBonjour\n") == "Bonjour"
    assert strip_added_whitespace("Hello", "  Bonjour  ") == "Bonjour"


def test_strip_added_whitespace_keeps_source_edges() -> None:
    assert strip_added_whitespace(" Hello ", " Bonjour \n") == " Bonjour \n"
    assert strip_added_whitespace("Hello\n", "Bonjour\n") == "Bonjour\n"
    assert strip_added_whitespace("\nHello", "\nBonjour") == "\nBonjour"


def test_translate_batch_strips_added_line_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _post(url: str, json: dict[str, str], timeout: float) -> _FakeResponse:
        return _FakeResponse({"translatedText": f"\n{json['q']}-fr\n"})

    monkeypatch.setattr("core.translation.providers.libretranslate.httpx.post", _post)
    p = LibreTranslateProvider(endpoint="http://x")
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    result = p.translate_batch(request)

    assert result.translations == [{"block_id": "a", "translated_text": "Hello-fr"}]


def test_failed_unit_does_not_block_others(monkeypatch: pytest.MonkeyPatch) -> None:
    def _post(url: str, json: dict[str, str], timeout: float) -> _FakeResponse:
        if json["q"] == "Hello":
            raise httpx.ConnectError("boom")
        return _FakeResponse({"translatedText": f"{json['q']}-fr"})

    monkeypatch.setattr("core.translation.providers.libretranslate.httpx.post", _post)
    p = LibreTranslateProvider(endpoint="http://x")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )

    result = p.translate_batch(request)

    assert result.failed_ids == ["a"]
    assert result.translations == [{"block_id": "b", "translated_text": "World-fr"}]


def test_translate_batch_stops_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _post(url: str, json: dict[str, str], timeout: float) -> _FakeResponse:
        calls.append(json["q"])
        return _FakeResponse({"translatedText": "x"})

    monkeypatch.setattr("core.translation.providers.libretranslate.httpx.post", _post)
    p = LibreTranslateProvider(endpoint="http://x")
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
        is_cancelled=lambda: len(calls) >= 1,
    )

    result = p.translate_batch(request)

    assert calls == ["Hello"]
    assert len(result.translations) == 1


def test_test_connection_true_when_languages_responds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.translation.providers.libretranslate.httpx.get",
        lambda url, timeout: _FakeResponse([], status_code=200),
    )
    assert LibreTranslateProvider(endpoint="http://x").test_connection() is True


def test_test_connection_false_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _get(url: str, timeout: float) -> _FakeResponse:
        raise httpx.ConnectError("down")

    monkeypatch.setattr("core.translation.providers.libretranslate.httpx.get", _get)
    assert LibreTranslateProvider(endpoint="http://x").test_connection() is False
