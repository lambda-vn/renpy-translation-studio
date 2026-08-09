"""Tests for core/context_builder.py."""

from core.storage.repositories import Character
from core.translation.context_builder import (
    MAX_UNITS_PER_BATCH,
    ContextualUnit,
    build_batch_prompt,
    build_system_prompt,
    estimate_tokens,
    split_into_batches,
)


def _unit(block_id: str, text: str) -> ContextualUnit:
    return ContextualUnit(
        block_id=block_id,
        source_text=text,
        character_variable=None,
        prev_text=None,
        next_text=None,
    )


def test_estimate_tokens_minimum_one() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a") == 1


def test_estimate_tokens_scales_with_length() -> None:
    assert estimate_tokens("a" * 100) == 25


def test_build_system_prompt_includes_universe_and_characters() -> None:
    prompt = build_system_prompt(
        universe_summary="A dark fantasy world.",
        characters=[
            Character(id=1, variable="e", display_name="Eileen", notes="stern")
        ],
        source_lang="english",
        target_lang="french",
    )
    assert "A dark fantasy world." in prompt
    assert "e (Eileen): stern" in prompt
    assert "english" in prompt
    assert "french" in prompt


def test_build_system_prompt_forbids_html_tags() -> None:
    prompt = build_system_prompt(
        universe_summary=None,
        characters=[],
        source_lang="english",
        target_lang="french",
    )
    assert "HTML" in prompt
    assert "{a=...}...{/a}" in prompt


def test_build_system_prompt_explains_tags_generically() -> None:
    """The model must preserve unlisted tags like {p}, not just the examples.

    Enumerating a few example tags without stating the general {tag}
    pattern led the model to only reliably keep the tags it was shown and
    drop unfamiliar ones such as {p}.
    """
    prompt = build_system_prompt(
        universe_summary=None,
        characters=[],
        source_lang="english",
        target_lang="french",
    )
    assert "{p}" in prompt
    assert "even for tag names you don't recognize" in prompt


def test_build_system_prompt_handles_stuttering() -> None:
    """Stuttered dialogue must be translated with an equivalent stutter.

    Without this rule the model either copies the broken source verbatim
    or translates the clean sentence and drops the speech impediment.
    """
    prompt = build_system_prompt(
        universe_summary=None,
        characters=[],
        source_lang="english",
        target_lang="french",
    )
    assert "stutter" in prompt
    assert "Sl..ow d..own" in prompt


def test_build_system_prompt_omits_empty_sections() -> None:
    prompt = build_system_prompt(
        universe_summary=None,
        characters=[],
        source_lang="english",
        target_lang="french",
    )
    assert "Universe context" not in prompt
    assert "Characters" not in prompt


def test_build_batch_prompt_includes_context() -> None:
    unit = ContextualUnit(
        block_id="a",
        source_text="Hello",
        character_variable="e",
        prev_text="Before",
        next_text="After",
    )
    prompt = build_batch_prompt([unit])
    assert "context_before: Before" in prompt
    assert "speaker: e" in prompt
    assert "source: Hello" in prompt
    assert "context_after: After" in prompt


def test_split_into_batches_respects_token_budget() -> None:
    units = [_unit(str(i), "word " * 50) for i in range(10)]
    batches = split_into_batches(units, "system", num_ctx=200)
    assert len(batches) > 1
    assert sum(len(b) for b in batches) == 10


def test_split_into_batches_single_batch_when_small() -> None:
    units = [_unit(str(i), "hi") for i in range(5)]
    batches = split_into_batches(units, "system", num_ctx=100_000)
    assert len(batches) == 1
    assert len(batches[0]) == 5


def test_split_into_batches_oversized_unit_forms_its_own_batch() -> None:
    huge = _unit("huge", "word " * 1000)
    small = _unit("small", "hi")
    batches = split_into_batches([huge, small], "system", num_ctx=200)
    assert any(len(b) == 1 and b[0].block_id == "huge" for b in batches)


def test_split_into_batches_system_prompt_counted_as_overhead() -> None:
    units = [_unit(str(i), "x" * 20) for i in range(4)]
    batches_short_system = split_into_batches(units, "s", num_ctx=100)
    batches_long_system = split_into_batches(units, "s" * 500, num_ctx=100)
    assert len(batches_long_system) >= len(batches_short_system)


def test_split_into_batches_caps_units_regardless_of_token_budget() -> None:
    units = [_unit(str(i), "hi") for i in range(MAX_UNITS_PER_BATCH + 5)]
    batches = split_into_batches(units, "system", num_ctx=1_000_000)
    assert all(len(b) <= MAX_UNITS_PER_BATCH for b in batches)
    assert sum(len(b) for b in batches) == len(units)


def test_split_into_batches_respects_custom_max_units() -> None:
    units = [_unit(str(i), "hi") for i in range(7)]
    batches = split_into_batches(units, "system", num_ctx=1_000_000, max_units=3)
    assert all(len(b) <= 3 for b in batches)
    assert sum(len(b) for b in batches) == len(units)
