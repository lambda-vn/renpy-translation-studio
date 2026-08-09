"""Helpers shared by cloud LLM providers (Claude, Mistral)."""

import json

from core.translation.context_builder import ContextualUnit
from core.translation.providers.base import TranslationUnitPayload


def add_context(units: list[TranslationUnitPayload]) -> list[ContextualUnit]:
    """Enrich each unit with its previous and next source texts.

    Args:
        units: The units to translate, each with block_id, source_text,
            and optionally character_variable.

    Returns:
        One ContextualUnit per input unit, in the same order.
    """
    result: list[ContextualUnit] = []
    for i, unit in enumerate(units):
        result.append(
            ContextualUnit(
                block_id=unit["block_id"],
                source_text=unit["source_text"],
                character_variable=unit.get("character_variable"),
                prev_text=units[i - 1]["source_text"] if i > 0 else None,
                next_text=units[i + 1]["source_text"] if i < len(units) - 1 else None,
            )
        )
    return result


def parse_translations(
    content: str, requested_ids: set[str]
) -> tuple[list[dict[str, str]], list[str]]:
    """Parse an LLM JSON response into translations and missing block_ids.

    Accepts either a bare JSON array of {block_id, translation} objects
    or an object wrapping such an array under any key — JSON-object
    output modes force a top-level object on some providers. Entries
    with an unrecognized block_id are ignored; requested ids the model
    did not answer are reported as failed instead of being lost.

    Args:
        content: The raw JSON text returned by the model.
        requested_ids: The block_ids that were requested in this batch.

    Returns:
        Tuple of (translations, missing_block_ids), where translations
        are dicts with keys block_id and translated_text.

    Raises:
        json.JSONDecodeError: If content is not valid JSON.
        ValueError: If the JSON does not contain an array.
    """
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        parsed = next((v for v in parsed.values() if isinstance(v, list)), parsed)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")

    translations: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        block_id = item.get("block_id", item.get("id"))
        translation = item.get("translation")
        if block_id is None or translation is None:
            continue
        if str(block_id) in requested_ids:
            translations.append(
                {"block_id": str(block_id), "translated_text": str(translation)}
            )

    missing = sorted(requested_ids - {t["block_id"] for t in translations})
    return translations, missing
