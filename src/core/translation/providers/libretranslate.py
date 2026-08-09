"""LibreTranslate Machine Translation provider."""

import logging

import httpx

from core.languages import get_language
from core.translation.providers.base import TranslateBatchRequest, TranslateBatchResult

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30.0


def strip_added_whitespace(source: str, translated: str) -> str:
    """Strip whitespace the API added at edges the source doesn't have.

    LibreTranslate sometimes appends line breaks to its translations.
    Each edge of the translation is only stripped when the matching edge
    of the source text carries no whitespace itself, so intentional
    leading/trailing spacing in the source is never lost.

    Args:
        source: The original source text.
        translated: The translation returned by the API.

    Returns:
        The translation with provider-added edge whitespace removed.
    """
    if not source or not source[0].isspace():
        translated = translated.lstrip()
    if not source or not source[-1].isspace():
        translated = translated.rstrip()
    return translated


def resolve_libretranslate_lang(code: str) -> str:
    """Map a Ren'Py language identifier to a LibreTranslate language code.

    Identifiers declared in core.languages are mapped to their ISO
    equivalent; anything else is passed through lowercased so the API can
    accept or reject it explicitly.

    Args:
        code: A Ren'Py language identifier or an ISO language code.

    Returns:
        A LibreTranslate-compatible language code.
    """
    lang = get_language(code)
    return lang.iso if lang is not None else code.lower()


class LibreTranslateProvider:
    """Translates text using any LibreTranslate-compatible instance.

    The endpoint URL is mandatory and has no hardcoded default — the user
    must explicitly provide one (e.g. http://localhost:5000 for
    self-hosted, or a public instance URL with its API key). Public
    instances have unpredictable rate limits; self-hosting is recommended.
    """

    id = "libretranslate"
    requires_api_key = False

    def __init__(self, endpoint: str, api_key: str | None = None) -> None:
        """Initialize the LibreTranslate provider.

        Args:
            endpoint: Base URL of the LibreTranslate instance.
            api_key: Optional API key, required only on private instances.

        Raises:
            ValueError: If the endpoint is empty.
        """
        if not endpoint:
            raise ValueError("LibreTranslate endpoint URL is required.")
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key

    def test_connection(self) -> bool:
        """Return True if the instance responds to /languages.

        Returns:
            True if the instance is reachable.
        """
        try:
            resp = httpx.get(f"{self._endpoint}/languages", timeout=5)
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("test_connection to %s failed: %s", self._endpoint, exc)
            return False

    def translate_batch(self, request: TranslateBatchRequest) -> TranslateBatchResult:
        """Translate texts one API call per unit (LibreTranslate limitation).

        Checks request.is_cancelled before each call, so a cancellation
        takes effect after the current request instead of waiting for
        the whole batch to finish. The api_key field is omitted from the
        payload when unset — an empty string breaks some instances.

        Args:
            request: The units and language pair to translate.

        Returns:
            The translated units and the block_ids that failed.
        """
        translations: list[dict[str, str]] = []
        failed_ids: list[str] = []
        total = len(request.units)
        logger.info("translate_batch: %d unit(s) via %s", total, self._endpoint)

        for index, unit in enumerate(request.units, start=1):
            if request.is_cancelled and request.is_cancelled():
                logger.info("translate_batch cancelled before unit %d/%d", index, total)
                break
            if request.on_batch_start:
                request.on_batch_start(index, total)
            payload: dict[str, str] = {
                "q": unit["source_text"],
                "source": resolve_libretranslate_lang(request.source_lang),
                "target": resolve_libretranslate_lang(request.target_lang),
                "format": "text",
            }
            if self._api_key:
                payload["api_key"] = self._api_key
            try:
                resp = httpx.post(
                    f"{self._endpoint}/translate",
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                translated = strip_added_whitespace(
                    unit["source_text"], str(resp.json().get("translatedText", ""))
                )
                logger.debug(
                    "Unit %s: %r -> %r",
                    unit["block_id"],
                    unit["source_text"],
                    translated,
                )
                translations.append(
                    {"block_id": unit["block_id"], "translated_text": translated}
                )
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "Unit %d/%d failed: %s: %s", index, total, type(exc).__name__, exc
                )
                failed_ids.append(unit["block_id"])

        return TranslateBatchResult(translations=translations, failed_ids=failed_ids)
