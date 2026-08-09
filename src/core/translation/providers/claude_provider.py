"""Anthropic Claude LLM provider."""

import json
import logging

import anthropic

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

CLAUDE_DEFAULT_MODEL = "claude-sonnet-4-6"
CLAUDE_CONTEXT_WINDOW = 200_000
CLAUDE_MAX_OUTPUT_TOKENS = 8192
COMPLETION_MAX_TOKENS = 1024


class ClaudeProvider:
    """Translates using the Anthropic Claude API."""

    id = "claude"
    requires_api_key = True

    def __init__(
        self,
        api_key: str,
        model: str = CLAUDE_DEFAULT_MODEL,
        universe_summary: str | None = None,
        characters: list[Character] | None = None,
    ) -> None:
        """Initialize the Claude provider.

        Args:
            api_key: The Anthropic API key.
            model: Claude model identifier to use.
            universe_summary: Optional free-form description of the game's setting.
            characters: Character glossary to inject into every prompt.
        """
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._universe_summary = universe_summary
        self._characters = characters or []

    def test_connection(self) -> bool:
        """Check the API key by sending a minimal request.

        Returns:
            True if the key is accepted. A non-authentication API error
            still counts as reachable — the key itself is valid.
        """
        try:
            self._client.messages.create(
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except anthropic.AuthenticationError:
            return False
        except anthropic.APIConnectionError:
            return False
        except anthropic.APIError:
            return True

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
            contextual_units, system_prompt, CLAUDE_CONTEXT_WINDOW
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
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=CLAUDE_MAX_OUTPUT_TOKENS,
                    system=system_prompt,
                    messages=[{"role": "user", "content": build_batch_prompt(batch)}],
                )
                content = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                logger.debug("Batch raw response: %s", content)
                translations, missing = parse_translations(content, requested_ids)
                all_translations.extend(translations)
                all_failed.extend(missing)
            except anthropic.APIError as exc:
                logger.warning(
                    "Claude request %d/%d failed: %s: %s",
                    index,
                    len(batches),
                    type(exc).__name__,
                    exc,
                )
                all_failed.extend(sorted(requested_ids))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Failed to parse Claude response %d/%d: %s",
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
            response = self._client.messages.create(
                model=self._model,
                max_tokens=COMPLETION_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            logger.warning("Claude completion failed: %s: %s", type(exc).__name__, exc)
            raise TranslationProviderError(
                i18n.t("providers.claude_request_failed")
            ) from exc
        return "".join(block.text for block in response.content if block.type == "text")
