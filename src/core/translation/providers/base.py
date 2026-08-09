"""Base protocol and data types shared by all translation providers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import NotRequired, Protocol, TypedDict, runtime_checkable


class TranslationProviderError(Exception):
    """Raised for a foreseeable provider failure (unreachable server, bad config).

    TranslationJob catches this specifically to stop the job cleanly with
    a user-facing message, instead of logging a full traceback as an
    unexpected crash.
    """


class TranslationUnitPayload(TypedDict):
    """The unit shape passed from TranslationJob into a provider.

    character_variable is only present when the caller can supply it —
    context-aware providers like Ollama use it, DeepL ignores it.
    """

    block_id: str
    source_text: str
    character_variable: NotRequired[str | None]


@dataclass
class TranslateBatchRequest:
    """A batch of units to translate.

    Attributes:
        units: The units to translate.
        source_lang: Source language code (e.g. "EN").
        target_lang: Target language code (e.g. "FR").
        on_batch_start: Optional callback invoked before each of the
            provider's own internal network requests, with
            (current_request_index, total_requests), both 1-based. Lets
            the UI show activity even while a single request is still
            in flight — useful for slow local LLM providers.
        is_cancelled: Optional callback the provider should poll between
            its own internal network requests, returning True once the
            job has been cancelled. Lets a cancellation take effect
            immediately instead of waiting for the whole batch — the
            provider should stop after finishing the request already in
            flight and return whatever it completed so far.
        on_event: Optional callback for a human-readable message about
            something notable a provider does outside the normal
            translated/failed outcome — e.g. Ollama preloading its model
            before the first request. Lets the UI surface that activity
            instead of appearing frozen.
    """

    units: list[TranslationUnitPayload]
    source_lang: str
    target_lang: str
    on_batch_start: Callable[[int, int], None] | None = None
    is_cancelled: Callable[[], bool] | None = None
    on_event: Callable[[str], None] | None = None


@dataclass
class TranslateBatchResult:
    """The outcome of a translate_batch call.

    Attributes:
        translations: List of dicts with keys block_id and translated_text.
        failed_ids: block_ids that could not be translated.
    """

    translations: list[dict[str, str]]
    failed_ids: list[str]


@runtime_checkable
class SupportsGlossary(Protocol):
    """Optional capability for providers with server-side glossary support.

    A provider implementing this protocol can upload term pairs once and
    then apply them to every subsequent translate_batch call.
    """

    def sync_glossary(
        self,
        term_pairs: dict[str, str],
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Upload term pairs and return an opaque glossary ID.

        Args:
            term_pairs: Mapping of source term to target term.
            source_lang: Source language identifier.
            target_lang: Target language identifier.

        Returns:
            A provider-specific glossary ID.
        """
        ...


@runtime_checkable
class SupportsCompletion(Protocol):
    """Optional capability for LLM providers that can answer a free prompt.

    Used by features that need plain text generation outside the
    translation pipeline (e.g. the AI universe summary).
    """

    def complete(self, prompt: str) -> str:
        """Send a single free-form prompt and return the model's text reply.

        Args:
            prompt: The full prompt to send.

        Returns:
            The model's raw text response.

        Raises:
            TranslationProviderError: If the provider cannot be reached or
                returns an unusable response.
        """
        ...


@runtime_checkable
class TranslationProvider(Protocol):
    """Common interface for all translation providers (MT and LLM)."""

    @property
    def id(self) -> str:
        """Unique identifier (e.g. 'deepl', 'ollama')."""
        ...

    @property
    def requires_api_key(self) -> bool:
        """True if an API key is required to use this provider."""
        ...

    def test_connection(self) -> bool:
        """Return True if the provider is reachable and credentials are valid."""
        ...

    def translate_batch(self, request: TranslateBatchRequest) -> TranslateBatchResult:
        """Translate a batch of texts.

        Args:
            request: The units and language pair to translate.

        Returns:
            The translated units and the block_ids that failed.
        """
        ...
