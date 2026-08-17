"""Tests for core/universe_generator.py."""

import pytest

from core.storage.repositories import TranslationUnit
from core.translation.providers.base import TranslationProviderError
from core.translation.universe_generator import (
    SAMPLE_SIZE,
    SUMMARY_CHAR_BUDGET,
    UniverseGenerator,
    format_samples,
    language_name,
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


def _unit(
    i: int,
    text: str | None = None,
    source_file: str = "/games/demo/game/script.rpy",
    character_variable: str | None = None,
) -> TranslationUnit:
    return TranslationUnit(
        id=i,
        block_id=f"b{i}",
        source_file=source_file,
        source_line=i,
        character_variable=character_variable,
        source_text=(
            text if text is not None else f"Line {i} of perfectly ordinary dialogue."
        ),
        translated_text="",
        status="not_translated",
    )


def test_sample_dialogue_returns_all_when_small() -> None:
    units = [_unit(i) for i in range(5)]
    assert sample_dialogue(units) == units


def test_sample_dialogue_caps_and_spreads_when_large() -> None:
    units = [_unit(i) for i in range(SAMPLE_SIZE * 3)]
    samples = sample_dialogue(units)
    assert len(samples) == SAMPLE_SIZE
    assert samples[0] is units[0]
    assert samples[1] is units[3]


def test_sample_dialogue_drops_short_texts() -> None:
    units = [_unit(0, text="Save"), _unit(1), _unit(2, text="...")]
    assert sample_dialogue(units) == [units[1]]


def test_sample_dialogue_drops_renpy_boilerplate_files() -> None:
    units = [
        _unit(0, source_file="/games/demo/game/screens.rpy"),
        _unit(1),
        _unit(2, source_file="/games/demo/game/options.rpy"),
    ]
    assert sample_dialogue(units) == [units[1]]


def test_sample_dialogue_falls_back_when_filters_empty_the_list() -> None:
    units = [_unit(0, text="Save"), _unit(1, text="Quit")]
    assert sample_dialogue(units) == units


def test_format_samples_groups_by_file_and_names_the_speaker() -> None:
    units = [
        _unit(0, text="A dark corridor stretches ahead.", character_variable="n"),
        _unit(1, text="Who goes there, stranger?", character_variable="eileen"),
        _unit(2, text="A second scene begins.", source_file="/g/game/chapter2.rpy"),
    ]

    rendered = format_samples(units)

    assert "[script.rpy]" in rendered
    assert "[chapter2.rpy]" in rendered
    assert "- eileen: Who goes there, stranger?" in rendered
    assert "- A second scene begins." in rendered


def test_language_name_turns_a_folder_code_into_a_language() -> None:
    assert language_name("french") == "French"
    assert language_name("schinese") == "Chinese (Simplified)"


def test_language_name_keeps_an_unknown_code_as_is() -> None:
    assert language_name("klingon") == "klingon"


def test_generate_asks_for_the_language_not_the_folder_name() -> None:
    provider = _FakeCompletionProvider()

    UniverseGenerator().generate([_unit(0)], provider, "schinese")

    assert "Chinese (Simplified)" in provider.prompts[0]
    assert "schinese" not in provider.prompts[0]


def test_generate_builds_prompt_with_samples_language_and_budget() -> None:
    provider = _FakeCompletionProvider(reply="  Un monde sombre.  ")
    units = [_unit(i) for i in range(3)]

    summary = UniverseGenerator().generate(units, provider, "french")

    assert summary == "Un monde sombre."
    prompt = provider.prompts[0]
    assert "French" in prompt
    assert str(SUMMARY_CHAR_BUDGET) in prompt
    assert "- Line 0 of perfectly ordinary dialogue." in prompt
    assert "- Line 2 of perfectly ordinary dialogue." in prompt


def test_generate_propagates_provider_error() -> None:
    provider = _FakeCompletionProvider()
    provider.raise_exc = TranslationProviderError("down")
    with pytest.raises(TranslationProviderError):
        UniverseGenerator().generate([_unit(0)], provider, "french")
