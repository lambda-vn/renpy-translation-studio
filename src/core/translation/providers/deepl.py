"""DeepL Machine Translation provider."""

import logging
import re

import deepl

from core.languages import get_language
from core.storage.repositories import Character
from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslateBatchResult,
    TranslationUnitPayload,
)

logger = logging.getLogger(__name__)

DEEPL_BATCH_SIZE = 50

_TERM_PAIR_PATTERN = re.compile(r"^\s*(.+?)\s*(?:->|→)\s*(.+?)\s*$")


def resolve_deepl_lang(code: str) -> str:
    """Map a Ren'Py language identifier to a DeepL language code.

    Identifiers declared in core.languages are mapped to their DeepL
    equivalent; anything else is passed through uppercased so the API can
    accept or reject it explicitly.

    Args:
        code: A Ren'Py language identifier or an ISO language code.

    Returns:
        A DeepL-compatible language code.
    """
    lang = get_language(code)
    if lang is not None:
        return lang.deepl or lang.iso.upper()
    return code.upper()


def build_term_pairs(characters: list[Character]) -> dict[str, str]:
    """Extract glossary term pairs from character notes.

    A character note line of the form "Eileen -> Aline" (or with the
    "→" arrow) declares that the source term on the left must always be
    translated as the term on the right. Lines that don't match this
    format are ignored silently — the notes field is free-form.

    Args:
        characters: The character glossary entries to scan.

    Returns:
        Mapping of source term to target term, possibly empty.
    """
    pairs: dict[str, str] = {}
    for character in characters:
        if not character.notes:
            continue
        for line in character.notes.splitlines():
            match = _TERM_PAIR_PATTERN.match(line)
            if match:
                pairs[match.group(1)] = match.group(2)
    return pairs


class DeepLProvider:
    """Translates text using the DeepL API."""

    id = "deepl"
    requires_api_key = True

    def __init__(self, api_key: str, characters: list[Character] | None = None) -> None:
        """Initialize the DeepL client.

        Args:
            api_key: The DeepL API key.
            characters: Character glossary entries whose notes may contain
                "source -> target" term pairs to enforce via a DeepL
                glossary.
        """
        self._client = deepl.Translator(api_key)
        self._term_pairs = build_term_pairs(characters or [])
        self._glossary_id: str | None = None
        self._glossary_synced = False

    def sync_glossary(
        self,
        term_pairs: dict[str, str],
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Upload term pairs as a DeepL glossary and return its ID.

        Deletes any existing glossary with the same name first, so stale
        glossaries never accumulate in the DeepL account.

        Args:
            term_pairs: Mapping of source term to target term.
            source_lang: Ren'Py language identifier or ISO code.
            target_lang: Ren'Py language identifier or ISO code.

        Returns:
            The DeepL glossary ID.

        Raises:
            deepl.DeepLException: If the glossary cannot be created (e.g.
                unsupported language pair or invalid API key).
        """
        source = resolve_deepl_lang(source_lang)
        target = resolve_deepl_lang(target_lang)
        name = f"rts-{source.lower()}-{target.lower()}"
        for existing in self._client.list_glossaries():
            if existing.name == name:
                self._client.delete_glossary(existing)
        glossary = self._client.create_glossary(
            name,
            source_lang=source,
            target_lang=target,
            entries=term_pairs,
        )
        logger.info("Synced DeepL glossary %r (%d term(s))", name, len(term_pairs))
        return str(glossary.glossary_id)

    def _ensure_glossary(self, source_lang: str, target_lang: str) -> None:
        """Sync the character term pairs as a glossary, once per provider.

        Runs lazily on the first translate_batch call so the network
        round-trip happens on the job's background thread. A failure
        (unsupported language pair, quota, network) is logged and the
        job continues without a glossary rather than aborting.

        Args:
            source_lang: Ren'Py language identifier or ISO code.
            target_lang: Ren'Py language identifier or ISO code.
        """
        if self._glossary_synced or not self._term_pairs:
            return
        self._glossary_synced = True
        try:
            self._glossary_id = self.sync_glossary(
                self._term_pairs, source_lang, target_lang
            )
        except deepl.DeepLException as exc:
            logger.warning(
                "DeepL glossary sync failed, translating without it: %s", exc
            )

    def test_connection(self) -> bool:
        """Ping the DeepL API by fetching account usage.

        Returns:
            True if the API key is valid and the API is reachable.
        """
        try:
            self._client.get_usage()
            return True
        except deepl.DeepLException as exc:
            logger.warning("DeepL test_connection failed: %s", exc)
            return False

    def get_character_usage(self) -> tuple[int | None, int | None]:
        """Fetch the current character usage and monthly limit.

        Returns:
            A tuple of (characters used, character limit). Either value
            may be None if the account has no applicable limit.

        Raises:
            deepl.DeepLException: If the API key is invalid or unreachable.
        """
        usage = self._client.get_usage()
        return usage.character.count, usage.character.limit

    def translate_batch(self, request: TranslateBatchRequest) -> TranslateBatchResult:
        """Send texts to DeepL in chunks of DEEPL_BATCH_SIZE.

        Checks request.is_cancelled before each chunk, so a cancellation
        takes effect after the current request instead of waiting for
        the whole batch to finish.

        Args:
            request: The units and language pair to translate.

        Returns:
            The translated units and the block_ids that failed per chunk
            already sent when cancellation is requested.
        """
        self._ensure_glossary(request.source_lang, request.target_lang)
        translations: list[dict[str, str]] = []
        failed_ids: list[str] = []
        chunks = self._chunks(request.units, DEEPL_BATCH_SIZE)
        logger.info(
            "translate_batch: %d unit(s) in %d chunk(s)",
            len(request.units),
            len(chunks),
        )

        for index, chunk in enumerate(chunks, start=1):
            if request.is_cancelled and request.is_cancelled():
                logger.info(
                    "translate_batch cancelled before chunk %d/%d", index, len(chunks)
                )
                break
            if request.on_batch_start:
                request.on_batch_start(index, len(chunks))
            try:
                texts = [unit["source_text"] for unit in chunk]
                results = self._client.translate_text(
                    texts,
                    source_lang=resolve_deepl_lang(request.source_lang),
                    target_lang=resolve_deepl_lang(request.target_lang),
                    glossary=self._glossary_id,
                )
                if not isinstance(results, list):
                    results = [results]
                for unit, result in zip(chunk, results, strict=True):
                    logger.debug(
                        "Unit %s: %r -> %r",
                        unit["block_id"],
                        unit["source_text"],
                        result.text,
                    )
                    translations.append(
                        {
                            "block_id": unit["block_id"],
                            "translated_text": result.text,
                        }
                    )
            except deepl.DeepLException as exc:
                logger.warning("Chunk %d/%d failed: %s", index, len(chunks), exc)
                failed_ids.extend(unit["block_id"] for unit in chunk)

        return TranslateBatchResult(translations=translations, failed_ids=failed_ids)

    @staticmethod
    def _chunks(
        items: list[TranslationUnitPayload], size: int
    ) -> list[list[TranslationUnitPayload]]:
        """Split items into successive chunks of `size`.

        Args:
            items: The list to split.
            size: Maximum length of each chunk.

        Returns:
            A list of chunks.
        """
        return [items[i : i + size] for i in range(0, len(items), size)]
