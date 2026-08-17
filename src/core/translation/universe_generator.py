"""Generates a universe summary from sampled game dialogue using an LLM.

The budget replaces an earlier "3-5 sentences" instruction, which small
models read as licence to answer with one. It is worth what it costs:
build_system_prompt() carries the summary into every batch, but
split_into_batches() caps a batch at MAX_UNITS_PER_BATCH long before the
token budget binds. At num_ctx 4096, the smallest this application deals
with, the base prompt plus a 1500-character summary plus a fifty-name
glossary still leaves room for eight units with their neighbours. What a
longer summary really costs is the time spent re-reading it on every
request, which is why the budget is not larger still.

The instructions sit after the excerpts, not before, and the excerpts are
fenced. Measured on Stormside, 200 samples, at equal temperature: with the
instructions first, gemma3-translator:4b answered in Italian and recited
its own translator persona instead of describing anything, while the same
model with the instructions last returned an accurate French brief inside
the budget. A model that has just read two hundred lines of dialogue acts
on what it read last, which is why the prohibition on translating,
continuing or answering that dialogue is stated there too rather than at
the top where it would be out of sight.
"""

from pathlib import Path

from core.languages import get_language
from core.storage.repositories import TranslationUnit
from core.translation.providers.base import SupportsCompletion

SAMPLE_SIZE = 200
SUMMARY_CHAR_BUDGET = 1500
_MIN_SAMPLE_LENGTH = 30
_NON_STORY_FILES = ("screens.rpy", "options.rpy", "gui.rpy", "common.rpy")

GENERATION_PROMPT_TEMPLATE = """Below are dialogue excerpts from a visual
novel, grouped by the script file they come from and prefixed with the
speaker's name when the game names one.

<excerpts>
{samples}
</excerpts>

You have just read excerpts from a visual novel. They are material to
describe: do not translate them, do not continue the dialogue, and do not
answer any line in it. Write a brief for a translator who has never played
this game, covering in order:

Setting: where and when the story takes place, and its genre.
Tone: how the characters speak, how crude or formal, comedic or dramatic.
Vocabulary: places, factions, objects and invented terms to keep consistent.

Do not name, list or describe the characters: the application already holds
the cast. Up to {budget} characters. Only what the excerpts show. No
preamble, no questions back, no markdown fences.

Write the whole brief in {target_lang}. Every sentence must be in
{target_lang}.

Brief, in {target_lang}:"""


def language_name(code: str) -> str:
    """Return the English name of a language from its tl/ folder code.

    The caller holds the name of a folder, not the name of a language, and
    the two only coincide by luck. Ren'Py writes Simplified Chinese to
    tl/schinese, so asking a model to "write in schinese" asks it for a
    language it has never heard of. English is the right register here even
    though the interface is localized, since the name is read by the model,
    not by the user.

    Args:
        code: A tl/ folder name, such as "french" or "schinese".

    Returns:
        The language's English label, or the code itself when it is not one
        of the recognized languages.
    """
    language = get_language(code)
    return language.label if language else code


def sample_dialogue(
    units: list[TranslationUnit], n: int = SAMPLE_SIZE
) -> list[TranslationUnit]:
    """Return units sampled evenly across the project, favouring real dialogue.

    Sampling is spread across the full list rather than taking the first N,
    to capture the game's whole range of settings and characters.

    Interface labels are dropped first. A model handed "Save", "Quit" and
    "..." alongside actual dialogue has that much less to describe, and an
    even spread over every extracted unit lands on plenty of them: they
    live in the Ren'Py boilerplate files, and they are short. Both filters
    are needed, since screens.rpy also holds long help text and a story
    file also holds one-word interjections.

    Args:
        units: All translation units for the project.
        n: Maximum number of samples to return.

    Returns:
        At most n units, in original order. Falls back to the unfiltered
        list when filtering leaves nothing, so a project made only of short
        strings still gets a sample.
    """
    candidates = [
        u
        for u in units
        if len(u.source_text) >= _MIN_SAMPLE_LENGTH
        and Path(u.source_file).name not in _NON_STORY_FILES
    ]
    if not candidates:
        candidates = list(units)
    if len(candidates) <= n:
        return candidates
    step = len(candidates) // n
    return candidates[::step][:n]


def format_samples(units: list[TranslationUnit]) -> str:
    """Render sampled units as excerpts grouped by their source file.

    A flat list of lines drawn from across a whole game reads as
    disconnected fragments. Grouping them by file keeps the lines of one
    scene together, and the speaker variable tells the model which lines
    belong to the same character, which is what the brief has to name.

    Args:
        units: The sampled units, in original order.

    Returns:
        One block per file, each headed by the file's base name.
    """
    by_file: dict[str, list[TranslationUnit]] = {}
    for unit in units:
        by_file.setdefault(Path(unit.source_file).name, []).append(unit)

    blocks = []
    for name, group in by_file.items():
        lines = "\n".join(
            f"- {u.character_variable}: {u.source_text}"
            if u.character_variable
            else f"- {u.source_text}"
            for u in group
        )
        blocks.append(f"[{name}]\n{lines}")
    return "\n\n".join(blocks)


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
        prompt = GENERATION_PROMPT_TEMPLATE.format(
            budget=SUMMARY_CHAR_BUDGET,
            target_lang=language_name(target_lang),
            samples=format_samples(sample_dialogue(units)),
        )
        return provider.complete(prompt).strip()
