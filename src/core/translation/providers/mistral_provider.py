"""Mistral AI LLM provider."""

import json
import logging

import httpx
from mistralai.client import Mistral, models
from mistralai.client.errors import MistralError

from core.i18n import i18n
from core.storage.repositories import Character
from core.translation.context_builder import (
    build_batch_prompt,
    build_system_prompt,
    split_into_batches,
)
from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslateBatchResult,
    TranslationProviderError,
)
from core.translation.providers.llm_common import add_context, parse_translations

logger = logging.getLogger(__name__)

MISTRAL_DEFAULT_MODEL = "mistral-large-latest"
MISTRAL_CONTEXT_WINDOW = 128_000


class MistralProvider:
    """Translates using the Mistral AI API."""

    id = "mistral"
    requires_api_key = True

    def __init__(
        self,
        api_key: str,
        model: str = MISTRAL_DEFAULT_MODEL,
        universe_summary: str | None = None,
        characters: list[Character] | None = None,
    ) -> None:
        """Initialize the Mistral provider.

        Args:
            api_key: The Mistral API key.
            model: Mistral model identifier to use.
            universe_summary: Optional free-form description of the game's setting.
            characters: Character glossary to inject into every prompt.
        """
        self._client = Mistral(api_key=api_key)
        self._model = model
        self._universe_summary = universe_summary
        self._characters = characters or []

    def test_connection(self) -> bool:
        """Check the API key by listing available models.

        Returns:
            True if the key is accepted and the API is reachable.
        """
        try:
            self._client.models.list()
            return True
        except (MistralError, httpx.HTTPError) as exc:
            logger.warning("Mistral test_connection failed: %s", type(exc).__name__)
            return False

    def translate_batch(self, request: TranslateBatchRequest) -> TranslateBatchResult:
        """Translate all units in the request using dynamic batching.

        Checks request.is_cancelled before each API request, so a
        cancellation takes effect after the current request instead of
        waiting for the whole batch to finish.

        Args:
            request: The units and language pair to translate.

        Returns:
            The translated units and the block_ids that failed.
        """
        system_prompt = build_system_prompt(
            universe_summary=self._universe_summary,
            characters=self._characters,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )
        contextual_units = add_context(request.units)
        batches = split_into_batches(
            contextual_units, system_prompt, MISTRAL_CONTEXT_WINDOW
        )
        logger.info(
            "translate_batch: model=%s units=%d -> %d request(s)",
            self._model,
            len(request.units),
            len(batches),
        )

        all_translations: list[dict[str, str]] = []
        all_failed: list[str] = []

        for index, batch in enumerate(batches, start=1):
            if request.is_cancelled and request.is_cancelled():
                logger.info(
                    "translate_batch cancelled before request %d/%d",
                    index,
                    len(batches),
                )
                break
            if request.on_batch_start:
                request.on_batch_start(index, len(batches))
            requested_ids = {u.block_id for u in batch}
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Batch sent: %s",
                    [(u.block_id, u.source_text) for u in batch],
                )
            try:
                content = self._chat(
                    system_prompt, build_batch_prompt(batch), json_mode=True
                )
                logger.debug("Batch raw response: %s", content)
                translations, missing = parse_translations(content, requested_ids)
                all_translations.extend(translations)
                all_failed.extend(missing)
            except (MistralError, httpx.HTTPError) as exc:
                logger.warning(
                    "Mistral request %d/%d failed: %s: %s",
                    index,
                    len(batches),
                    type(exc).__name__,
                    exc,
                )
                all_failed.extend(sorted(requested_ids))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Failed to parse Mistral response %d/%d: %s",
                    index,
                    len(batches),
                    exc,
                )
                all_failed.extend(sorted(requested_ids))

        return TranslateBatchResult(
            translations=all_translations, failed_ids=all_failed
        )

    def complete(self, prompt: str) -> str:
        """Send a single free-form prompt and return the text reply.

        Args:
            prompt: The full prompt to send.

        Returns:
            The model's raw text response.

        Raises:
            TranslationProviderError: If the API request fails.
        """
        try:
            return self._chat(None, prompt, json_mode=False)
        except (MistralError, httpx.HTTPError, ValueError) as exc:
            logger.warning("Mistral completion failed: %s: %s", type(exc).__name__, exc)
            raise TranslationProviderError(
                i18n.t("providers.mistral_request_failed")
            ) from exc

    def _chat(
        self, system_prompt: str | None, user_prompt: str, json_mode: bool
    ) -> str:
        """Send one chat completion request and return the text content.

        Args:
            system_prompt: Optional system message.
            user_prompt: The user message.
            json_mode: When True, force valid-JSON output via response_format.

        Returns:
            The response text content.

        Raises:
            MistralError: If the API rejects the request.
            httpx.HTTPError: If the server cannot be reached.
            ValueError: If the response carries no usable text content.
        """
        messages: list[models.ChatCompletionRequestMessageTypedDict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        response = self._client.chat.complete(
            model=self._model,
            messages=messages,
            stream=False,
            response_format={"type": "json_object"} if json_mode else None,
        )
        if not response.choices:
            raise ValueError("Mistral response has no choices")
        message = response.choices[0].message
        content = message.content if message else None
        if not isinstance(content, str):
            raise ValueError("Mistral response content is not text")
        return content
