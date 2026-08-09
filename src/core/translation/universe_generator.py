"""Generates a universe summary from sampled game dialogue using an LLM."""

from core.storage.repositories import TranslationUnit
from core.translation.providers.base import SupportsCompletion

SAMPLE_SIZE = 200

GENERATION_PROMPT_TEMPLATE = """You are analyzing a visual novel game.
Based on the following dialogue samples, write a concise summary (3-5 sentences)
describing the game's setting, tone, themes, and main characters.
Write the summary in {target_lang}. Answer with the summary only.

Dialogue samples:
{samples}

Summary:"""


def sample_dialogue(units: list[TranslationUnit], n: int = SAMPLE_SIZE) -> list[str]:
    """Return source texts sampled evenly across the unit list.

    Distributes sampling across the full list rather than taking the
    first N, to capture the game's full range of settings and characters.

    Args:
        units: All translation units for the project.
        n: Maximum number of samples to return.

    Returns:
        At most n source texts, in original order.
    """
    if len(units) <= n:
        return [u.source_text for u in units]
    step = len(units) // n
    return [units[i].source_text for i in range(0, len(units), step)][:n]


class UniverseGenerator:
    """Generates a universe summary via an LLM provider.

    Only called on explicit user action. Never runs automatically.
    """

    def generate(
        self,
        units: list[TranslationUnit],
        provider: SupportsCompletion,
        target_lang: str,
    ) -> str:
        """Generate and return a universe summary string.

        Args:
            units: All translation units for the project.
            provider: An LLM provider able to answer a free-form prompt.
            target_lang: The language in which to write the summary.

        Returns:
            The generated summary, stripped of surrounding whitespace.

        Raises:
            TranslationProviderError: If the provider request fails.
        """
        samples = sample_dialogue(units)
        prompt = GENERATION_PROMPT_TEMPLATE.format(
            target_lang=target_lang,
            samples="\n".join(f"- {s}" for s in samples),
        )
        return provider.complete(prompt).strip()
