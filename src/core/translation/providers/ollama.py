"""Ollama LLM provider for context-aware translation."""

import json
import logging

import httpx

from core.i18n import i18n
from core.storage.repositories import Character
from core.translation.context_builder import (
    MAX_UNITS_PER_BATCH,
    ContextualUnit,
    build_batch_prompt,
    build_system_prompt,
    split_into_batches,
)
from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslateBatchResult,
    TranslationProviderError,
    TranslationUnitPayload,
)

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://localhost:11434"
REQUEST_TIMEOUT = 300.0
DEFAULT_CONTEXT_LENGTH = 4096
MAX_NUM_CTX = 8192
TRANSLATION_TEMPERATURE = 0.2
_MIN_DUPLICATE_TEXT_LENGTH = 4
_PS_TIMEOUT = 5.0
_CPU_OFFLOAD_WARNING_THRESHOLD = 0.95
_CLOUD_SUFFIX = "-cloud"


def is_cloud_model(model: str) -> bool:
    """Report whether a model runs on Ollama's servers rather than here.

    Cloud models carry a -cloud suffix, gpt-oss:120b-cloud for instance,
    and reach the very same local endpoint: the daemon authenticates the
    request once the user has signed in and forwards it. Nothing of the
    model is loaded into this machine's memory, which is why the guards
    written for local hardware do not apply to them.

    Args:
        model: The model name as typed in the settings.

    Returns:
        True when the name marks a cloud model.
    """
    return model.endswith(_CLOUD_SUFFIX)


def _build_response_schema(count: int) -> dict[str, object]:
    """Build a JSON schema requiring exactly `count` translation entries.

    Without minItems/maxItems, a model can legally satisfy the schema
    after emitting a single entry — and small quantized models reliably
    do exactly that on longer batches, closing the array early instead of
    covering every requested unit. Pinning the array length turns "the
    model stopped early" into a grammar violation the constrained decoder
    can't produce, rather than a silent, valid-but-incomplete response.

    Args:
        count: Number of units in this batch — the exact array length
            the model must produce.

    Returns:
        A JSON schema dict for Ollama's structured-output `format` field.
    """
    return {
        "type": "array",
        "minItems": count,
        "maxItems": count,
        "items": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string"},
                "translation": {"type": "string"},
            },
            "required": ["block_id", "translation"],
        },
    }


def _extract_entry(item: object) -> tuple[str, str] | None:
    """Pull (block_id, translated_text) out of one loosely-shaped response item.

    Small models don't reliably use the exact key names asked for in the
    system prompt — "id" instead of "block_id" is common. Accepting both
    avoids failing an entire batch over one non-compliant item.

    Args:
        item: One element of the model's parsed JSON response.

    Returns:
        A (block_id, translated_text) tuple, or None if item isn't a dict
        with a recognizable identifier and translation.
    """
    if not isinstance(item, dict):
        return None
    block_id = item.get("block_id", item.get("id"))
    translation = item.get("translation")
    if block_id is None or translation is None:
        return None
    return str(block_id), str(translation)


def _drop_duplicate_content(
    translations: list[dict[str, str]], source_by_id: dict[str, str]
) -> tuple[list[dict[str, str]], list[str]]:
    """Drop translations that are byte-for-byte copies across unrelated units.

    When a heavily quantized model is required to fill every array slot
    (see _build_response_schema()) but runs out of anything genuine to
    say, it tends to pad the response by repeating a neighboring entry's
    translation verbatim instead of generating distinct content — e.g.
    the translation for "Load" ends up copied onto the entry for an
    unrelated credits paragraph. A short, incidental match (a common word
    like "Oui") is normal and left alone; only longer repeats shared
    across units with different source_text are treated as padding.

    Args:
        translations: Matched (block_id, translated_text) entries for
            this batch.
        source_by_id: source_text for every block_id in the batch.

    Returns:
        Tuple of (kept translations, block_ids dropped as duplicate
        padding).
    """
    ids_by_text: dict[str, list[str]] = {}
    for t in translations:
        ids_by_text.setdefault(t["translated_text"], []).append(t["block_id"])

    duplicate_ids: set[str] = set()
    for text, ids in ids_by_text.items():
        if len(ids) < 2 or len(text) < _MIN_DUPLICATE_TEXT_LENGTH:
            continue
        if len({source_by_id.get(i, "") for i in ids}) > 1:
            duplicate_ids.update(ids)

    if not duplicate_ids:
        return translations, []
    kept = [t for t in translations if t["block_id"] not in duplicate_ids]
    return kept, sorted(duplicate_ids)


class OllamaProvider:
    """Translates using a locally running Ollama model."""

    id = "ollama"
    requires_api_key = False

    def __init__(
        self,
        endpoint: str,
        model: str,
        universe_summary: str | None = None,
        characters: list[Character] | None = None,
        batch_size: int | None = None,
    ) -> None:
        """Initialize the Ollama provider.

        Args:
            endpoint: Base URL of the Ollama server (e.g. http://localhost:11434).
            model: Name of the local model to use.
            universe_summary: Optional free-form description of the game's setting.
            characters: Character glossary to inject into every prompt.
            batch_size: Maximum number of units per request. Defaults to
                MAX_UNITS_PER_BATCH when None.
        """
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._universe_summary = universe_summary
        self._characters = characters or []
        self._batch_size = batch_size
        self._num_ctx: int | None = None

    def test_connection(self) -> bool:
        """Return True if the Ollama server is reachable.

        Returns:
            True if the server responded successfully.
        """
        try:
            resp = httpx.get(f"{self._endpoint}/api/tags", timeout=5)
            logger.debug(
                "test_connection to %s -> status=%s", self._endpoint, resp.status_code
            )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("test_connection to %s failed: %s", self._endpoint, exc)
            return False

    def list_models(self) -> list[str]:
        """Return the names of all locally available models.

        Returns:
            List of model names known to the Ollama server.

        Raises:
            httpx.HTTPError: If the server is unreachable or returns an error.
        """
        resp = httpx.get(f"{self._endpoint}/api/tags", timeout=10)
        resp.raise_for_status()
        models: list[str] = [m["name"] for m in resp.json().get("models", [])]
        logger.debug("list_models on %s -> %s", self._endpoint, models)
        return models

    def _resolve_num_ctx(self) -> int:
        """Decide how much context to ask the model for.

        MAX_NUM_CTX protects this machine's VRAM: past it the KV cache
        spills and generation collapses. A cloud model is not loaded
        here at all, the daemon signing the request and forwarding it to
        Ollama's servers, so the cap protects nothing and only costs.

        It costs whenever the system prompt is large. split_into_batches
        subtracts it, plus the output margin, from num_ctx; a rich
        universe summary and a long character glossary can leave so
        little that batches fall to one or two units instead of eight,
        which is many times the requests for the same work. That is the
        setup this application recommends, so it is the one to protect.

        Returns:
            The model's own context length for a cloud model, capped at
            MAX_NUM_CTX for anything running locally.

        Raises:
            httpx.HTTPError: If the server is unreachable.
        """
        length = self.get_context_length(self._model)
        if is_cloud_model(self._model):
            logger.debug("%s runs on Ollama's servers, num_ctx uncapped", self._model)
            return length
        return min(length, MAX_NUM_CTX)

    def get_context_length(self, model: str) -> int:
        """Fetch the maximum context length for the given model via /api/show.

        Args:
            model: Name of the model to inspect.

        Returns:
            The model's context length in tokens, or a conservative default
            if it could not be determined.

        Raises:
            httpx.HTTPError: If the server is unreachable or returns an error.
        """
        resp = httpx.post(
            f"{self._endpoint}/api/show",
            json={"name": model},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        model_info = data.get("model_info", {})
        architecture = model_info.get("general.architecture", "")
        key = f"{architecture}.context_length"
        length = int(model_info.get(key, DEFAULT_CONTEXT_LENGTH))
        logger.debug(
            "get_context_length(%s): architecture=%r key=%r -> %d",
            model,
            architecture,
            key,
            length,
        )
        return length

    def translate_batch(self, request: TranslateBatchRequest) -> TranslateBatchResult:
        """Translate all units in the request using dynamic batching.

        Checks request.is_cancelled before each sub-batch request, so a
        cancellation takes effect after the current request instead of
        waiting for the whole chunk to finish.

        Args:
            request: The units and language pair to translate.

        Returns:
            The translated units and the block_ids that failed per
            sub-batch already sent when cancellation is requested.

        Raises:
            TranslationProviderError: If the Ollama server cannot be
                reached to determine the model's context length.
        """
        if self._num_ctx is None:
            try:
                self._num_ctx = self._resolve_num_ctx()
            except httpx.HTTPError as exc:
                logger.warning("Cannot reach Ollama at %s: %s", self._endpoint, exc)
                raise TranslationProviderError(
                    i18n.t("providers.ollama_unreachable").format(
                        endpoint=self._endpoint
                    )
                ) from exc
            self._preload_and_warn(request)

        system_prompt = build_system_prompt(
            universe_summary=self._universe_summary,
            characters=self._characters,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )

        contextual_units = self._add_context(request.units)
        batches = split_into_batches(
            contextual_units,
            system_prompt,
            self._num_ctx,
            max_units=self._batch_size or MAX_UNITS_PER_BATCH,
        )
        logger.info(
            "translate_batch: endpoint=%s model=%s units=%d num_ctx=%d -> "
            "%d request(s)",
            self._endpoint,
            self._model,
            len(request.units),
            self._num_ctx,
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
            logger.debug(
                "Sending request %d/%d (%d unit(s))", index, len(batches), len(batch)
            )
            translations, failed = self._translate_single_batch(batch, system_prompt)
            if failed:
                logger.warning(
                    "Request %d/%d failed for %d unit(s)",
                    index,
                    len(batches),
                    len(failed),
                )
            all_translations.extend(translations)
            all_failed.extend(failed)

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
            TranslationProviderError: If the Ollama server cannot be
                reached or returns an unusable response.
        """
        if self._num_ctx is None:
            try:
                self._num_ctx = self._resolve_num_ctx()
            except httpx.HTTPError as exc:
                logger.warning("Cannot reach Ollama at %s: %s", self._endpoint, exc)
                raise TranslationProviderError(
                    i18n.t("providers.ollama_unreachable").format(
                        endpoint=self._endpoint
                    )
                ) from exc
        try:
            resp = httpx.post(
                f"{self._endpoint}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_ctx": self._num_ctx},
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return str(resp.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("Ollama completion failed: %s: %s", type(exc).__name__, exc)
            raise TranslationProviderError(
                i18n.t("providers.ollama_request_failed").format(
                    endpoint=self._endpoint
                )
            ) from exc

    def _preload_and_warn(self, request: TranslateBatchRequest) -> None:
        """Load the model into memory and warn if it spills onto CPU.

        Ollama unloads a model after ~5 minutes of inactivity, so the
        first request of a job would otherwise pay for a full cold load
        with no visible feedback — the app would appear frozen. Sending a
        chat request with an empty messages array is the documented way
        to make Ollama load a model without generating anything; it
        returns as soon as the model is ready, near-instantly if it was
        already loaded. Immediately after, /api/ps reports how much of
        the loaded model sits in VRAM versus CPU, so a user running a
        model too big for their GPU gets told why translation is slow
        instead of having to run `ollama ps` themselves.

        Neither step can fail the job: any error (unreachable server,
        unexpected response shape) is logged and swallowed. A genuinely
        unreachable server was already caught by get_context_length()
        just before this is called.

        Args:
            request: The batch request this preload is happening for,
                used only for its on_event callback.
        """
        if request.on_event:
            request.on_event(i18n.t("job_events.model_loading"))
        try:
            httpx.post(
                f"{self._endpoint}/api/chat",
                json={
                    "model": self._model,
                    "messages": [],
                    "options": {"num_ctx": self._num_ctx},
                },
                timeout=REQUEST_TIMEOUT,
            ).raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("Model preload failed, continuing anyway: %s", exc)
            return

        try:
            resp = httpx.get(f"{self._endpoint}/api/ps", timeout=_PS_TIMEOUT)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            entry = next(
                (m for m in models if self._model in (m.get("name"), m.get("model"))),
                None,
            )
            if entry is None:
                return
            size = entry.get("size", 0)
            size_vram = entry.get("size_vram", 0)
            if not size:
                return
            ratio = size_vram / size
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            logger.debug("Cannot check /api/ps, continuing anyway: %s", exc)
            return

        if ratio < _CPU_OFFLOAD_WARNING_THRESHOLD and request.on_event:
            cpu_percent = round((1 - ratio) * 100)
            request.on_event(
                i18n.t("job_events.cpu_offload_warning").format(percent=cpu_percent)
            )

    def _add_context(self, units: list[TranslationUnitPayload]) -> list[ContextualUnit]:
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
                    next_text=(
                        units[i + 1]["source_text"] if i < len(units) - 1 else None
                    ),
                )
            )
        return result

    def _translate_single_batch(
        self,
        batch: list[ContextualUnit],
        system_prompt: str,
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Send one batch to Ollama and parse the JSON response.

        Uses a low temperature (TRANSLATION_TEMPERATURE) rather than the
        model's default — a weak or heavily quantized model at default
        temperature can drift into echoing the system prompt itself
        instead of translating, especially on longer batches. Also passes
        a JSON schema (_build_response_schema()) as format instead of the
        plain "json" string, which constrains the model's output via
        grammar-based sampling to an array of exactly len(batch)
        {block_id, translation} objects. This can't stop a model from
        putting nonsense inside a translation field, but it can no longer
        wrap the array in an object, return a single bare object, stop
        after one entry, or use the wrong key names — _extract_entry()
        and the requested_ids check below remain as a second line of
        defense regardless. Pinning the array length also means a model
        that runs out of genuine content to generate can no longer just
        stop — instead it tends to pad remaining slots by repeating a
        neighboring entry's translation verbatim, which
        _drop_duplicate_content() catches and discards.

        Args:
            batch: The contextual units to translate in this request.
            system_prompt: The system prompt accompanying this request.

        Returns:
            Tuple of (translations, failed_block_ids). On any failure the
            whole batch is reported as failed rather than partially
            parsed. block_ids the model silently dropped, or that were
            filled with a duplicate of another unit's translation, are
            also reported as failed instead of being lost or accepted
            with the wrong content.
        """
        requested_ids = {u.block_id for u in batch}
        source_by_id = {u.block_id: u.source_text for u in batch}
        user_prompt = build_batch_prompt(batch)
        logger.debug(
            "Batch sent: %s",
            [(u.block_id, u.source_text) for u in batch],
        )
        content = ""
        try:
            resp = httpx.post(
                f"{self._endpoint}/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "format": _build_response_schema(len(batch)),
                    "options": {
                        "num_ctx": self._num_ctx,
                        "truncate": False,
                        "temperature": TRANSLATION_TEMPERATURE,
                    },
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                if _extract_entry(parsed) is not None:
                    parsed = [parsed]
                else:
                    parsed = next(
                        (v for v in parsed.values() if isinstance(v, list)), parsed
                    )
            if not isinstance(parsed, list):
                raise ValueError(f"Expected a JSON array, got {type(parsed).__name__}")
            logger.debug("Batch raw response (%d item(s)): %s", len(parsed), parsed)
            translations: list[dict[str, str]] = []
            for item in parsed:
                entry = _extract_entry(item)
                if entry is not None and entry[0] in requested_ids:
                    block_id, translated_text = entry
                    translations.append(
                        {"block_id": block_id, "translated_text": translated_text}
                    )
                elif entry is not None:
                    logger.debug(
                        "Ignoring entry with unrecognized block_id %r: %r",
                        entry[0],
                        entry[1],
                    )
            translations, duplicate_ids = _drop_duplicate_content(
                translations, source_by_id
            )
            if duplicate_ids:
                logger.warning(
                    "Ollama repeated the same translation across %d unrelated "
                    "unit(s), dropping them: %s",
                    len(duplicate_ids),
                    sorted(duplicate_ids),
                )
            missing_ids = sorted(requested_ids - {t["block_id"] for t in translations})
            if missing_ids:
                logger.warning(
                    "Ollama returned %d/%d translation(s); missing block_id(s): %s",
                    len(translations),
                    len(requested_ids),
                    missing_ids,
                )
            return translations, missing_ids
        except httpx.HTTPError as exc:
            logger.warning(
                "Ollama request to %s failed: %s: %s",
                self._endpoint,
                type(exc).__name__,
                exc,
            )
            return [], [u.block_id for u in batch]
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning(
                "Failed to parse Ollama response: %s: %s (content: %r)",
                type(exc).__name__,
                exc,
                content[:300],
            )
            return [], [u.block_id for u in batch]
