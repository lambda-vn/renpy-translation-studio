"""Tests for core/universe_generator.py."""

import pytest

from core.storage.repositories import TranslationUnit
from core.translation.providers.base import TranslationProviderError
from core.translation.universe_generator import (
    SAMPLE_SIZE,
    UniverseGenerator,
    sample_dialogue,
)


class _FakeCompletionProvider:
    def __init__(self, reply: str = "A summary.") -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.raise_exc: Exception | None = None

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.reply


def _unit(i: int) -> TranslationUnit:
    return TranslationUnit(
        id=i,
        block_id=f"b{i}",
        source_file="game/script.rpy",
        source_line=i,
        character_variable=None,
        source_text=f"Line {i}",
        translated_text="",
        status="not_translated",
    )


def test_sample_dialogue_returns_all_when_small() -> None:
    units = [_unit(i) for i in range(5)]
    assert sample_dialogue(units) == [u.source_text for u in units]


def test_sample_dialogue_caps_and_spreads_when_large() -> None:
    units = [_unit(i) for i in range(SAMPLE_SIZE * 3)]
    samples = sample_dialogue(units)
    assert len(samples) == SAMPLE_SIZE
    assert samples[0] == "Line 0"
    assert samples[1] == "Line 3"


def test_generate_builds_prompt_with_samples_and_language() -> None:
    provider = _FakeCompletionProvider(reply="  Un monde sombre.  ")
    units = [_unit(i) for i in range(3)]

    summary = UniverseGenerator().generate(units, provider, "french")

    assert summary == "Un monde sombre."
    prompt = provider.prompts[0]
    assert "french" in prompt
    assert "- Line 0" in prompt
    assert "- Line 2" in prompt


def test_generate_propagates_provider_error() -> None:
    provider = _FakeCompletionProvider()
    provider.raise_exc = TranslationProviderError("down")
    with pytest.raises(TranslationProviderError):
        UniverseGenerator().generate([_unit(0)], provider, "french")
