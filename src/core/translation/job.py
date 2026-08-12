"""Manages a translation job running in a background thread."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from core.i18n import i18n
from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslateBatchResult,
    TranslationProvider,
    TranslationProviderError,
    TranslationUnitPayload,
)
from core.translation.quality import TAG_PATTERN
from core.translation.quality import check as quality_check

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 50

_BLOCKING_QUALITY_KINDS = {"missing_var", "unexpected_html"}

_RETRY_CHUNK_SIZES = [8, 1]
_MAX_RETRY_PASSES = len(_RETRY_CHUNK_SIZES)


def _default_thread_runner(target: Callable[..., None], *args: object) -> None:
    """Run target in a plain daemon thread — the default outside Flet.

    Args:
        target: The function to run in the background.
        *args: Positional arguments forwarded to target.
    """
    threading.Thread(target=target, args=args, daemon=True).start()


def needs_translation(source_text: str) -> bool:
    """Return False if source_text has no letters and translating it is pointless.

    Ren'Py text tags ({w=0.5}, {i}, {cps=20}, ...) are stripped first, since
    their tag names are letters but never player-visible text — a
    tag-wrapped ellipsis like "...{w=0.5}" has nothing to translate either.

    Also used at extraction time to pre-fill such units with their source
    text instead of sending them through a translation provider.

    Args:
        source_text: The unit's source text.

    Returns:
        True if source_text contains at least one alphabetic character
        outside of Ren'Py text tags.
    """
    stripped = TAG_PATTERN.sub("", source_text)
    return any(ch.isalpha() for ch in stripped)


def group_by_source(
    units: list[TranslationUnitPayload],
) -> tuple[list[TranslationUnitPayload], dict[str, list[str]]]:
    """Keep one unit per distinct source text, and note who shares it.

    A game repeats itself: 40 820 units of one script hold 22 997
    distinct texts, and "..." alone appears 1 607 times. Sending each
    occurrence is 44% of the requests spent asking the same question, and
    on a paid provider it is 44% of the bill. It also produces 1 607
    answers that may not agree with each other, where a human correcting
    the first one expects to have corrected them all.

    The first occurrence is the one sent. Its neighbours and its speaker
    are the ones the provider sees, so an LLM prompted with the line
    before and after gets those of the first occurrence rather than of
    each: a small loss on the exact context, against a request that is
    not sent at all.

    Args:
        units: The units to translate, in the order they will be sent.

    Returns:
        Tuple of (the units to actually send, the block ids waiting on
        each of them). A text occurring once has an empty list.
    """
    representatives: list[TranslationUnitPayload] = []
    followers: dict[str, list[str]] = {}
    leader_of: dict[str, str] = {}
    for unit in units:
        leader = leader_of.get(unit["source_text"])
        if leader is None:
            leader_of[unit["source_text"]] = unit["block_id"]
            representatives.append(unit)
            followers[unit["block_id"]] = []
        else:
            followers[leader].append(unit["block_id"])
    return representatives, followers


def spread_to_followers(
    result: TranslateBatchResult, followers: dict[str, list[str]]
) -> TranslateBatchResult:
    """Hand each answer to every unit that was waiting on it.

    Args:
        result: What came back for the units actually sent.
        followers: Block ids sharing each sent unit's source text.

    Returns:
        The same outcome, stated for every unit of the job. A failure
        spreads too: a unit whose text could not be translated has no
        translation either, and counting it as anything else would leave
        done and failed short of the total.
    """
    translations: list[dict[str, str]] = []
    for translation in result.translations:
        translations.append(translation)
        translations.extend(
            {"block_id": block_id, "translated_text": translation["translated_text"]}
            for block_id in followers.get(translation["block_id"], ())
        )
    failed_ids: list[str] = []
    for block_id in result.failed_ids:
        failed_ids.append(block_id)
        failed_ids.extend(followers.get(block_id, ()))
    return TranslateBatchResult(translations=translations, failed_ids=failed_ids)


@dataclass
class JobProgress:
    """Snapshot of a translation job's progress.

    Attributes:
        total: Total number of units to translate.
        done: Number of units successfully translated so far.
        failed: Number of units that failed so far.
        running: True while the background thread is active.
        finished: True once the job has stopped, successfully or not.
        error: Error message if the job aborted unexpectedly.
    """

    total: int = 0
    done: int = 0
    failed: int = 0
    running: bool = False
    finished: bool = False
    error: str | None = None


class TranslationJob:
    """Runs a translation batch in a background thread.

    Calls on_chunk after each chunk with the raw provider result, so the
    caller can persist translations as they arrive — this is what makes
    cancellation preserve already-translated units. Calls on_progress with
    the updated JobProgress so the UI can update, and on_complete when the
    job stops, successfully or not. Units still failing after the main
    pass get up to _MAX_RETRY_PASSES additional attempts in smaller
    chunks (see _retry_failed_units) before being reported as failed.

    A source text is only ever sent once, however many units carry it
    (see group_by_source): the answer is handed to all of them, so what
    on_chunk and the progress report is every unit of the job, while what
    the provider was asked is only the distinct texts.
    """

    def __init__(
        self,
        on_chunk: Callable[[TranslateBatchResult], None],
        on_progress: Callable[[JobProgress], None],
        on_complete: Callable[[JobProgress], None],
        on_batch_start: Callable[[int, int], None] | None = None,
        on_event: Callable[[str], None] | None = None,
        thread_runner: Callable[..., None] | None = None,
    ) -> None:
        """Initialize the job with its callbacks.

        Args:
            on_chunk: Called with the result of each translated chunk.
            on_progress: Called with the updated progress after each chunk.
            on_complete: Called once when the job stops.
            on_batch_start: Called before each of the provider's own
                internal network requests, with (index, total), both
                1-based. Lets the UI show activity while a single slow
                request (e.g. a local LLM) is still in flight.
            on_event: Called with a human-readable message whenever
                something notable happens beyond the plain done/failed
                count — a rejected AI suggestion (with the reason), or
                units skipped because they had nothing to translate. Lets
                the UI show the user what's actually happening during the
                job instead of just a final tally.
            thread_runner: Called with (self._run, *args) to start the
                background work. Defaults to a plain daemon thread. Flet
                callers should pass page.run_thread instead — a plain
                threading.Thread runs outside the page's session executor,
                so UI updates triggered from it can sit unflushed until an
                unrelated client round-trip (e.g. a window resize) happens
                to pump them through.
        """
        self._on_chunk = on_chunk
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_batch_start = on_batch_start
        self._on_event = on_event
        self._thread_runner = thread_runner or _default_thread_runner
        self._cancelled = threading.Event()
        self.progress = JobProgress()

    def start(
        self,
        units: list[TranslationUnitPayload],
        provider: TranslationProvider,
        source_lang: str,
        target_lang: str,
    ) -> None:
        """Start the translation job in a background thread.

        Args:
            units: Units to translate, each with block_id, source_text, and
                optionally character_variable.
            provider: The translation provider to use.
            source_lang: Source language code.
            target_lang: Target language code.
        """
        self.progress = JobProgress(total=len(units), running=True)
        self._thread_runner(self._run, units, provider, source_lang, target_lang)

    def cancel(self) -> None:
        """Request cancellation. Already-translated units are preserved."""
        self._cancelled.set()

    def _emit_event(self, message: str) -> None:
        """Forward a notable event to the UI callback, if any.

        Args:
            message: Human-readable description of what happened.
        """
        if self._on_event:
            self._on_event(message)

    @staticmethod
    def _verify_quality(
        chunk: list[TranslationUnitPayload], result: TranslateBatchResult
    ) -> tuple[TranslateBatchResult, list[str]]:
        """Reject only the AI suggestions that are actually implausible.

        A provider (especially a small local LLM) can return a translation
        that has nothing to do with its source — a missing interpolated
        variable ([player_name]) would break the game, and unexpected HTML
        markup is a reliable sign the model hallucinated instead of
        translating (_BLOCKING_QUALITY_KINDS). Those are rejected outright,
        as is a translation that's simply the source text echoed back
        unchanged (the model gave up instead of translating).

        Everything else quality_check() flags — a missing/extra Ren'Py
        tag, or an unusual length — is real but cosmetic: small models
        reliably drop tags they don't recognize even when told to keep
        them, and length ratios swing wildly on short strings. Rejecting
        the whole suggestion over that throws away translations that are
        largely correct and quick for a human to touch up. These are kept
        as ai_suggested, with a warning event so the UI can flag them for
        review instead of silently discarding them.

        Args:
            chunk: The units that were sent to the provider, for their
                source_text.
            result: The provider's raw result for this chunk.

        Returns:
            A TranslateBatchResult with implausible translations moved
            from translations to failed_ids, plus one human-readable
            message per rejection or warning.
        """
        source_by_id = {u["block_id"]: u["source_text"] for u in chunk}
        verified: list[dict[str, str]] = []
        rejected: list[str] = []
        events: list[str] = []
        for translation in result.translations:
            block_id = translation["block_id"]
            translated_text = translation["translated_text"]
            source = source_by_id.get(block_id, "")

            if source and translated_text.strip() == source.strip():
                logger.warning(
                    "Rejecting AI suggestion for %s: identique au texte source",
                    block_id,
                )
                rejected.append(block_id)
                events.append(
                    i18n.t("job_events.translation_rejected_identical").format(
                        block_id=block_id
                    )
                )
                continue

            issues = quality_check(source, translated_text)
            blocking = [i for i in issues if i.kind in _BLOCKING_QUALITY_KINDS]
            if blocking:
                reason = "; ".join(issue.detail for issue in blocking)
                logger.warning("Rejecting AI suggestion for %s: %s", block_id, reason)
                rejected.append(block_id)
                events.append(
                    i18n.t("job_events.translation_rejected_reason").format(
                        block_id=block_id, reason=reason
                    )
                )
                continue

            warnings = [i for i in issues if i.kind not in _BLOCKING_QUALITY_KINDS]
            if warnings:
                reason = "; ".join(issue.detail for issue in warnings)
                events.append(
                    i18n.t("job_events.translation_accepted_with_warning").format(
                        block_id=block_id, reason=reason
                    )
                )
            verified.append(translation)
        return (
            TranslateBatchResult(
                translations=verified, failed_ids=[*result.failed_ids, *rejected]
            ),
            events,
        )

    def _retry_failed_units(
        self,
        failed_ids: list[str],
        units_by_id: dict[str, TranslationUnitPayload],
        followers: dict[str, list[str]],
        provider: TranslationProvider,
        source_lang: str,
        target_lang: str,
    ) -> None:
        """Retry failed units in progressively smaller chunks.

        Runs up to _MAX_RETRY_PASSES additional passes over only the
        units that failed the main pass (provider failure or a rejected
        quality check), using a smaller chunk size each pass
        (_RETRY_CHUNK_SIZES) so the provider has fewer units to juggle at
        once. A unit that succeeds moves from progress.failed to
        progress.done; a unit still failing after the last pass stays
        counted as failed, keeping done + failed == total.

        What is retried is the unit that was sent, never the ones that
        were waiting on its answer: retrying those would be sending the
        same text again, which is what the deduplication exists to avoid.

        Args:
            failed_ids: block_ids to retry, from the main translation pass.
            units_by_id: Every translatable unit in this job, keyed by
                block_id, so retried units can be looked back up.
            followers: Block ids sharing each retried unit's source text.
            provider: The translation provider to use.
            source_lang: Source language code.
            target_lang: Target language code.
        """
        remaining = failed_ids
        for chunk_size in _RETRY_CHUNK_SIZES:
            if not remaining or self._cancelled.is_set():
                break
            self._emit_event(
                i18n.t("job_events.retry_in_progress").format(n=len(remaining))
            )
            retry_units = [units_by_id[block_id] for block_id in remaining]
            remaining = []
            for i in range(0, len(retry_units), chunk_size):
                if self._cancelled.is_set():
                    break
                chunk = retry_units[i : i + chunk_size]
                request = TranslateBatchRequest(
                    units=chunk,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    on_batch_start=self._on_batch_start,
                    is_cancelled=self._cancelled.is_set,
                    on_event=self._emit_event,
                )
                result = provider.translate_batch(request)
                result, events = self._verify_quality(chunk, result)
                for event in events:
                    self._emit_event(event)
                spread = spread_to_followers(result, followers)
                self._on_chunk(spread)
                recovered = len(spread.translations)
                self.progress.done += recovered
                self.progress.failed -= recovered
                remaining.extend(result.failed_ids)
                self._on_progress(self.progress)

    def _run(
        self,
        units: list[TranslationUnitPayload],
        provider: TranslationProvider,
        source_lang: str,
        target_lang: str,
    ) -> None:
        """Main job loop — runs in the background thread.

        Catches any exception raised by the provider so a failure surfaces
        as a JobProgress.error instead of killing the background thread
        silently. TranslationProviderError (a foreseeable failure, e.g. an
        unreachable server) is logged as a warning with its clean message;
        anything else is logged with the full traceback since it points
        to an actual bug.

        Args:
            units: Units to translate, each with block_id, source_text, and
                optionally character_variable.
            provider: The translation provider to use.
            source_lang: Source language code.
            target_lang: Target language code.
        """
        logger.info(
            "Starting translation job: provider=%s units=%d %s->%s",
            provider.id,
            len(units),
            source_lang,
            target_lang,
        )
        try:
            skipped = [u for u in units if not needs_translation(u["source_text"])]
            translatable, followers = group_by_source(
                [u for u in units if needs_translation(u["source_text"])]
            )
            units_by_id = {u["block_id"]: u for u in translatable}
            shared = sum(len(ids) for ids in followers.values())
            if shared:
                logger.info(
                    "%d unit(s) share a source text with another and are not sent",
                    shared,
                )
                self._emit_event(
                    i18n.t("job_events.duplicates_shared").format(n=shared)
                )

            if skipped:
                logger.info(
                    "Skipping %d unit(s) with nothing to translate", len(skipped)
                )
                self._on_chunk(
                    TranslateBatchResult(
                        translations=[
                            {
                                "block_id": u["block_id"],
                                "translated_text": u["source_text"],
                            }
                            for u in skipped
                        ],
                        failed_ids=[],
                    )
                )
                self.progress.done += len(skipped)
                self._emit_event(
                    i18n.t("job_events.skipped_copied").format(n=len(skipped))
                )
                self._on_progress(self.progress)

            failed_ids: list[str] = []
            for i in range(0, len(translatable), _CHUNK_SIZE):
                if self._cancelled.is_set():
                    logger.info("Job cancelled before chunk starting at unit %d", i)
                    break
                chunk = translatable[i : i + _CHUNK_SIZE]
                request = TranslateBatchRequest(
                    units=chunk,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    on_batch_start=self._on_batch_start,
                    is_cancelled=self._cancelled.is_set,
                    on_event=self._emit_event,
                )
                result = provider.translate_batch(request)
                provider_failed = len(result.failed_ids)
                result, events = self._verify_quality(chunk, result)
                logger.debug(
                    "Chunk done: %d translated, %d failed",
                    len(result.translations),
                    len(result.failed_ids),
                )
                if provider_failed:
                    self._emit_event(
                        i18n.t("job_events.provider_failed").format(n=provider_failed)
                    )
                for event in events:
                    self._emit_event(event)
                spread = spread_to_followers(result, followers)
                self._on_chunk(spread)
                self.progress.done += len(spread.translations)
                self.progress.failed += len(spread.failed_ids)
                failed_ids.extend(result.failed_ids)
                self._on_progress(self.progress)

            if failed_ids and not self._cancelled.is_set():
                self._retry_failed_units(
                    failed_ids,
                    units_by_id,
                    followers,
                    provider,
                    source_lang,
                    target_lang,
                )
        except TranslationProviderError as exc:
            logger.warning("Translation job stopped: %s", exc)
            self.progress.error = str(exc)
        except Exception as exc:
            logger.exception("Translation job failed unexpectedly")
            self.progress.error = str(exc)
        finally:
            self.progress.running = False
            self.progress.finished = True
            logger.info(
                "Translation job finished: done=%d failed=%d error=%s",
                self.progress.done,
                self.progress.failed,
                self.progress.error,
            )
            self._on_complete(self.progress)
