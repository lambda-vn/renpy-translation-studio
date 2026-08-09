"""Builds structured LLM prompts for translation with surrounding context."""

from dataclasses import dataclass

from core.storage.repositories import Character

TOKENS_PER_CHAR_ESTIMATE = 0.25
OUTPUT_MARGIN_RATIO = 0.20
MAX_UNITS_PER_BATCH = 8


@dataclass
class ContextualUnit:
    """A translation unit enriched with its immediate source-text neighbors."""

    block_id: str
    source_text: str
    character_variable: str | None
    prev_text: str | None
    next_text: str | None


def estimate_tokens(text: str) -> int:
    """Estimate token count using a conservative character-based heuristic.

    This is intentionally imprecise — the truncate=false safety net in Ollama
    handles cases where the actual count exceeds the budget.

    Args:
        text: The text to estimate.

    Returns:
        An approximate token count, at least 1.
    """
    return max(1, int(len(text) * TOKENS_PER_CHAR_ESTIMATE))


def build_system_prompt(
    universe_summary: str | None,
    characters: list[Character],
    source_lang: str,
    target_lang: str,
) -> str:
    """Build the static system prompt injected before every batch request.

    Args:
        universe_summary: Optional free-form description of the game's setting.
        characters: Character glossary to inject, if any.
        source_lang: Source language identifier.
        target_lang: Target language identifier.

    Returns:
        The complete system prompt string.
    """
    parts = [
        f"You are a visual novel translator. Translate from {source_lang} "
        f"to {target_lang}.",
        "The source text can contain Ren'Py text tags: any token wrapped "
        "in curly braces, such as {b}, {i}, {u}, {w}, {nw}, {p}, {fast}, "
        "{a=...}...{/a}, {color=...}...{/color}, {size=+10}. They control "
        "timing, pauses, styling and links in the game engine and are "
        "never part of the sentence itself. Copy every {tag} found in the "
        "source into the translation verbatim, in the same relative "
        "position, even for tag names you don't recognize.",
        "Preserve all Python interpolations ([variable_name]) exactly as they appear.",
        'When the source text stutters or hesitates (e.g. "W-what?", '
        '"Sl..ow d..own", "I... I don\'t know"), translate the intended '
        "sentence and reproduce an equivalent stutter or hesitation on the "
        "corresponding words in the target language.",
        "Never use HTML tags (such as <a>, <h1>, <p>) — Ren'Py does not "
        "use HTML markup, only the {tag} syntax shown above.",
        'Return ONLY a JSON array: [{"block_id": "...", "translation": "..."}]',
        "Do not add explanations or wrap in markdown code blocks.",
    ]
    if universe_summary:
        parts.append(f"\nUniverse context:\n{universe_summary}")
    if characters:
        glossary = "\n".join(
            f"- {c.variable} ({c.display_name})" + (f": {c.notes}" if c.notes else "")
            for c in characters
        )
        parts.append(f"\nCharacters:\n{glossary}")
    return "\n\n".join(parts)


def build_batch_prompt(units: list[ContextualUnit]) -> str:
    """Build the user message for a batch of translation units.

    Args:
        units: The contextual units to include in the prompt.

    Returns:
        The formatted user message string.
    """
    lines = []
    for unit in units:
        entry = [f"block_id: {unit.block_id}"]
        if unit.prev_text:
            entry.append(f"context_before: {unit.prev_text}")
        if unit.character_variable:
            entry.append(f"speaker: {unit.character_variable}")
        entry.append(f"source: {unit.source_text}")
        if unit.next_text:
            entry.append(f"context_after: {unit.next_text}")
        lines.append("\n".join(entry))
    return "\n\n---\n\n".join(lines)


def split_into_batches(
    units: list[ContextualUnit],
    system_prompt: str,
    num_ctx: int,
    max_units: int = MAX_UNITS_PER_BATCH,
) -> list[list[ContextualUnit]]:
    """Split units into batches that fit within the model's context window.

    Reserves 20% of the context window for the output. Uses the system
    prompt token count as a fixed overhead per batch. Also caps each batch
    at max_units regardless of remaining token budget — smaller LLMs
    reliably follow the structured-JSON-array instruction for a handful of
    units, but tend to drop most of a large batch even when it fits
    comfortably within the context window. A batch of short, similar
    labels (menu items like "Save"/"Quick Save"/"Quick Load") is also
    where these models most often attach a translation to the wrong
    block_id — keeping batches small reduces how many easily-confused
    items it has to keep straight at once.

    Args:
        units: The contextual units to split.
        system_prompt: The system prompt that will accompany every batch.
        num_ctx: The model's context window size, in tokens.
        max_units: Maximum number of units per batch, regardless of token
            budget. Defaults to MAX_UNITS_PER_BATCH.

    Returns:
        A list of batches, each a list of ContextualUnit.
    """
    output_margin = int(num_ctx * OUTPUT_MARGIN_RATIO)
    system_tokens = estimate_tokens(system_prompt)
    available = num_ctx - system_tokens - output_margin

    batches: list[list[ContextualUnit]] = []
    current_batch: list[ContextualUnit] = []
    current_tokens = 0

    for unit in units:
        unit_text = build_batch_prompt([unit])
        unit_tokens = estimate_tokens(unit_text)

        if current_batch and (
            current_tokens + unit_tokens > available or len(current_batch) >= max_units
        ):
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(unit)
        current_tokens += unit_tokens

    if current_batch:
        batches.append(current_batch)

    return batches
