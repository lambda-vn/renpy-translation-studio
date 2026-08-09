"""Tests for core/providers/deepl.py."""

from typing import Any

import deepl
import pytest

from core.storage.repositories import Character
from core.translation.providers.base import TranslateBatchRequest
from core.translation.providers.deepl import (
    DEEPL_BATCH_SIZE,
    DeepLProvider,
    build_term_pairs,
    resolve_deepl_lang,
)


class _FakeTextResult:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeGlossaryInfo:
    def __init__(self, name: str, glossary_id: str) -> None:
        self.name = name
        self.glossary_id = glossary_id


class _FakeTranslator:
    """Stand-in for deepl.Translator that records calls instead of hitting the API."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.calls: list[list[str]] = []
        self.glossary_args: list[str | None] = []
        self.fail_on: set[str] = set()
        self.glossaries: list[_FakeGlossaryInfo] = []
        self.deleted_glossaries: list[str] = []
        self.created_glossaries: list[dict[str, Any]] = []
        self.fail_glossary_create = False

    def translate_text(
        self,
        texts: list[str],
        *,
        source_lang: str,
        target_lang: str,
        glossary: str | None = None,
    ) -> list[_FakeTextResult]:
        self.calls.append(list(texts))
        self.glossary_args.append(glossary)
        if self.fail_on & set(texts):
            raise deepl.DeepLException("boom")
        return [_FakeTextResult(f"{t}-{target_lang}") for t in texts]

    def get_usage(self) -> Any:
        return object()

    def list_glossaries(self) -> list[_FakeGlossaryInfo]:
        return list(self.glossaries)

    def delete_glossary(self, glossary: _FakeGlossaryInfo) -> None:
        self.deleted_glossaries.append(glossary.glossary_id)
        self.glossaries = [
            g for g in self.glossaries if g.glossary_id != glossary.glossary_id
        ]

    def create_glossary(
        self,
        name: str,
        *,
        source_lang: str,
        target_lang: str,
        entries: dict[str, str],
    ) -> _FakeGlossaryInfo:
        if self.fail_glossary_create:
            raise deepl.DeepLException("glossary rejected")
        self.created_glossaries.append(
            {
                "name": name,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "entries": dict(entries),
            }
        )
        info = _FakeGlossaryInfo(name, f"gid-{len(self.created_glossaries)}")
        self.glossaries.append(info)
        return info


def _character(variable: str, display_name: str, notes: str | None) -> Character:
    return Character(id=0, variable=variable, display_name=display_name, notes=notes)


@pytest.fixture()
def provider(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DeepLProvider, _FakeTranslator]:
    fake = _FakeTranslator("key")
    monkeypatch.setattr(
        "core.translation.providers.deepl.deepl.Translator", lambda api_key: fake
    )
    return DeepLProvider(api_key="key"), fake


def test_resolve_deepl_lang_known() -> None:
    assert resolve_deepl_lang("french") == "FR"
    assert resolve_deepl_lang("english") == "EN"
    assert resolve_deepl_lang("SCHINESE") == "ZH"


def test_resolve_deepl_lang_unknown_falls_back_to_upper() -> None:
    assert resolve_deepl_lang("klingon") == "KLINGON"


def test_translate_batch_maps_results(
    provider: tuple[DeepLProvider, _FakeTranslator],
) -> None:
    p, _fake = provider
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    result = p.translate_batch(request)
    assert result.translations == [{"block_id": "a", "translated_text": "Hello-FR"}]
    assert result.failed_ids == []


def test_translate_batch_chunks_units(
    provider: tuple[DeepLProvider, _FakeTranslator],
) -> None:
    p, fake = provider
    units = [
        {"block_id": str(i), "source_text": f"text {i}"}
        for i in range(DEEPL_BATCH_SIZE + 5)
    ]
    request = TranslateBatchRequest(
        units=units, source_lang="english", target_lang="french"
    )
    result = p.translate_batch(request)
    assert len(fake.calls) == 2
    assert len(fake.calls[0]) == DEEPL_BATCH_SIZE
    assert len(fake.calls[1]) == 5
    assert len(result.translations) == DEEPL_BATCH_SIZE + 5


def test_translate_batch_stops_early_when_cancelled(
    provider: tuple[DeepLProvider, _FakeTranslator],
) -> None:
    p, fake = provider
    units = [
        {"block_id": str(i), "source_text": f"text {i}"}
        for i in range(DEEPL_BATCH_SIZE + 5)
    ]
    request = TranslateBatchRequest(
        units=units,
        source_lang="english",
        target_lang="french",
        is_cancelled=lambda: True,
    )
    result = p.translate_batch(request)
    assert len(fake.calls) == 0
    assert result.translations == []
    assert result.failed_ids == []


def test_translate_batch_cancelled_after_first_chunk_keeps_its_result(
    provider: tuple[DeepLProvider, _FakeTranslator],
) -> None:
    p, fake = provider
    units = [
        {"block_id": str(i), "source_text": f"text {i}"}
        for i in range(DEEPL_BATCH_SIZE + 5)
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
    result = p.translate_batch(request)
    assert len(fake.calls) == 1
    assert len(result.translations) == DEEPL_BATCH_SIZE


def test_translate_batch_marks_chunk_failed_on_exception(
    provider: tuple[DeepLProvider, _FakeTranslator],
) -> None:
    p, fake = provider
    fake.fail_on = {"Hello"}
    request = TranslateBatchRequest(
        units=[
            {"block_id": "a", "source_text": "Hello"},
            {"block_id": "b", "source_text": "World"},
        ],
        source_lang="english",
        target_lang="french",
    )
    result = p.translate_batch(request)
    assert result.translations == []
    assert result.failed_ids == ["a", "b"]


def test_translate_batch_failed_chunk_does_not_block_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTranslator("key")
    fake.fail_on = {"text 0"}
    monkeypatch.setattr(
        "core.translation.providers.deepl.deepl.Translator", lambda api_key: fake
    )
    p = DeepLProvider(api_key="key")
    units = [
        {"block_id": str(i), "source_text": f"text {i}"}
        for i in range(DEEPL_BATCH_SIZE + 1)
    ]
    request = TranslateBatchRequest(
        units=units, source_lang="english", target_lang="french"
    )
    result = p.translate_batch(request)
    assert len(result.failed_ids) == DEEPL_BATCH_SIZE
    assert len(result.translations) == 1


def test_build_term_pairs_parses_both_arrows() -> None:
    characters = [
        _character("e", "Eileen", "Eileen -> Aline"),
        _character("l", "Lucy", "Lucy → Lucie\nSoft-spoken, shy"),
    ]
    assert build_term_pairs(characters) == {"Eileen": "Aline", "Lucy": "Lucie"}


def test_build_term_pairs_ignores_free_form_notes() -> None:
    characters = [
        _character("e", "Eileen", "Stern, formal register"),
        _character("l", "Lucy", None),
    ]
    assert build_term_pairs(characters) == {}


def test_translate_batch_syncs_glossary_once_and_uses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTranslator("key")
    monkeypatch.setattr(
        "core.translation.providers.deepl.deepl.Translator", lambda api_key: fake
    )
    p = DeepLProvider(
        api_key="key", characters=[_character("e", "Eileen", "Eileen -> Aline")]
    )
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    p.translate_batch(request)
    p.translate_batch(request)

    assert len(fake.created_glossaries) == 1
    assert fake.created_glossaries[0]["name"] == "rts-en-fr"
    assert fake.created_glossaries[0]["entries"] == {"Eileen": "Aline"}
    assert fake.glossary_args == ["gid-1", "gid-1"]


def test_sync_glossary_deletes_existing_with_same_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTranslator("key")
    fake.glossaries = [
        _FakeGlossaryInfo("rts-en-fr", "old-id"),
        _FakeGlossaryInfo("other", "keep-id"),
    ]
    monkeypatch.setattr(
        "core.translation.providers.deepl.deepl.Translator", lambda api_key: fake
    )
    p = DeepLProvider(api_key="key")

    p.sync_glossary({"Eileen": "Aline"}, "english", "french")

    assert fake.deleted_glossaries == ["old-id"]
    assert any(g.glossary_id == "keep-id" for g in fake.glossaries)


def test_translate_batch_continues_without_glossary_on_sync_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTranslator("key")
    fake.fail_glossary_create = True
    monkeypatch.setattr(
        "core.translation.providers.deepl.deepl.Translator", lambda api_key: fake
    )
    p = DeepLProvider(
        api_key="key", characters=[_character("e", "Eileen", "Eileen -> Aline")]
    )
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )

    result = p.translate_batch(request)

    assert result.translations == [{"block_id": "a", "translated_text": "Hello-FR"}]
    assert fake.glossary_args == [None]


def test_translate_batch_without_term_pairs_never_touches_glossaries(
    provider: tuple[DeepLProvider, _FakeTranslator],
) -> None:
    p, fake = provider
    request = TranslateBatchRequest(
        units=[{"block_id": "a", "source_text": "Hello"}],
        source_lang="english",
        target_lang="french",
    )
    p.translate_batch(request)
    assert fake.created_glossaries == []
    assert fake.glossary_args == [None]


def test_test_connection_true_on_success(
    provider: tuple[DeepLProvider, _FakeTranslator],
) -> None:
    p, _fake = provider
    assert p.test_connection() is True


def test_test_connection_false_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingTranslator:
        def __init__(self, api_key: str) -> None:
            pass

        def get_usage(self) -> Any:
            raise deepl.DeepLException("nope")

    monkeypatch.setattr(
        "core.translation.providers.deepl.deepl.Translator", _FailingTranslator
    )
    p = DeepLProvider(api_key="key")
    assert p.test_connection() is False
