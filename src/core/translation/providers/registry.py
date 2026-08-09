"""Provider registry — add a new provider by registering it here."""

from core.i18n import i18n
from core.settings import settings
from core.storage.repositories import Character
from core.translation.providers.base import TranslationProvider
from core.translation.providers.claude_provider import (
    CLAUDE_DEFAULT_MODEL,
    ClaudeProvider,
)
from core.translation.providers.deepl import DeepLProvider
from core.translation.providers.libretranslate import LibreTranslateProvider
from core.translation.providers.mistral_provider import (
    MISTRAL_DEFAULT_MODEL,
    MistralProvider,
)
from core.translation.providers.ollama import OllamaProvider

MIN_OLLAMA_BATCH_SIZE = 1
MAX_OLLAMA_BATCH_SIZE = 32

LLM_PROVIDER_IDS = frozenset({"ollama", "claude", "mistral"})


def _parse_ollama_batch_size(value: str | None) -> int | None:
    """Parse the ollama_batch_size setting, falling back to the default.

    Args:
        value: The raw setting value, or None if unset.

    Returns:
        A valid batch size between MIN_OLLAMA_BATCH_SIZE and
        MAX_OLLAMA_BATCH_SIZE, or None to let the provider use its default.
    """
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if not (MIN_OLLAMA_BATCH_SIZE <= parsed <= MAX_OLLAMA_BATCH_SIZE):
        return None
    return parsed


class ProviderRegistry:
    """Builds provider instances from current settings."""

    def get(
        self,
        provider_id: str,
        *,
        universe_summary: str | None = None,
        characters: list[Character] | None = None,
    ) -> TranslationProvider:
        """Return a configured provider instance for the given id.

        Args:
            provider_id: Identifier of the provider to build (e.g. "deepl").
            universe_summary: Optional context passed to context-aware
                providers (Ollama, Claude, Mistral). Ignored by providers
                that don't use it.
            characters: Character glossary passed to context-aware
                providers and to DeepL (glossary term pairs). Ignored by
                providers that don't use it.

        Returns:
            A configured TranslationProvider instance.

        Raises:
            ValueError: If the provider is unknown or not configured.
        """
        if provider_id == "deepl":
            api_key = settings.get("deepl_api_key")
            if not api_key:
                raise ValueError(i18n.t("providers.deepl_not_configured"))
            return DeepLProvider(api_key=api_key, characters=characters)
        if provider_id == "ollama":
            model = settings.get("ollama_model")
            if not model:
                raise ValueError(i18n.t("providers.ollama_not_configured"))
            endpoint = settings.get("ollama_endpoint") or "http://localhost:11434"
            batch_size = _parse_ollama_batch_size(settings.get("ollama_batch_size"))
            return OllamaProvider(
                endpoint=endpoint,
                model=model,
                universe_summary=universe_summary,
                characters=characters,
                batch_size=batch_size,
            )
        if provider_id == "libretranslate":
            url = settings.get("libretranslate_url")
            if not url:
                raise ValueError(i18n.t("providers.libretranslate_not_configured"))
            return LibreTranslateProvider(
                endpoint=url,
                api_key=settings.get("libretranslate_api_key"),
            )
        if provider_id == "claude":
            claude_key = settings.get("claude_api_key")
            if not claude_key:
                raise ValueError(i18n.t("providers.claude_not_configured"))
            return ClaudeProvider(
                api_key=claude_key,
                model=settings.get("claude_model") or CLAUDE_DEFAULT_MODEL,
                universe_summary=universe_summary,
                characters=characters,
            )
        if provider_id == "mistral":
            mistral_key = settings.get("mistral_api_key")
            if not mistral_key:
                raise ValueError(i18n.t("providers.mistral_not_configured"))
            return MistralProvider(
                api_key=mistral_key,
                model=settings.get("mistral_model") or MISTRAL_DEFAULT_MODEL,
                universe_summary=universe_summary,
                characters=characters,
            )
        raise ValueError(f"Unknown provider: {provider_id}")

    def available(self) -> list[str]:
        """Return ids of providers that have their credentials configured.

        Returns:
            List of provider ids ready to use.
        """
        result = []
        if settings.get("deepl_api_key"):
            result.append("deepl")
        if settings.get("ollama_model"):
            result.append("ollama")
        if settings.get("libretranslate_url"):
            result.append("libretranslate")
        if settings.get("claude_api_key"):
            result.append("claude")
        if settings.get("mistral_api_key"):
            result.append("mistral")
        return result

    def available_llm(self) -> list[str]:
        """Return ids of configured providers able to answer free prompts.

        Returns:
            List of LLM provider ids ready to use.
        """
        return [pid for pid in self.available() if pid in LLM_PROVIDER_IDS]


registry = ProviderRegistry()
