"""Tests for core/translation_job.py."""

import logging
import threading
import time
from typing import Any

import pytest

from core.translation.job import JobProgress, TranslationJob
from core.translation.providers.base import (
    TranslateBatchRequest,
    TranslateBatchResult,
    TranslationProviderError,
)


class _FakeProvider:
    """Records each request and returns one translation per unit."""

    id = "fake"
    requires_api_key = False

    def __init__(self) -> None:
        self.requests: list[TranslateBatchRequest] = []

    def test_connection(self) -> bool:
        return True

    def translate_batch(self, request: TranslateBatchRequest) -> TranslateBatchResult:
        self.requests.append(request)
        if request.on_batch_start:
            request.on_batch_start(1, 1)
        translations = [
            {"block_id": u["block_id"], "translated_text": f"{u['source_text']}!"}
            for u in request.units
        ]
        return TranslateBatchResult(translations=translations, failed_ids=[])


def _units(n: int) -> list[dict[str, str]]:
    return [{"block_id": str(i), "source_text": f"text {i}"} for i in range(n)]


def _run_job(job: TranslationJob, provider: _FakeProvider, units: list) -> None:
    done = threading.Event()
    original_complete = job._on_complete

    def _wrap(progress: JobProgress) -> None:
        original_complete(progress)
        done.set()

    job._on_complete = _wrap
    job.start(units, provider, "english", "french")
    assert done.wait(timeout=5)


def test_translate_batch_calls_on_chunk_and_on_progress() -> None:
    chunks: list[TranslateBatchResult] = []
    progresses: list[JobProgress] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda p: progresses.append(JobProgress(**vars(p))),
        on_complete=lambda _p: None,
    )
    provider = _FakeProvider()
    _run_job(job, provider, _units(3))

    assert len(chunks) == 1
    assert len(chunks[0].translations) == 3
    assert progresses[-1].done == 3
    assert progresses[-1].failed == 0


def test_on_complete_reports_finished_state() -> None:
    completions: list[JobProgress] = []
    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=lambda _p: None,
        on_complete=completions.append,
    )
    _run_job(job, _FakeProvider(), _units(2))

    assert completions[-1].finished is True
    assert completions[-1].running is False
    assert completions[-1].error is None


def test_on_batch_start_is_forwarded_to_provider() -> None:
    received: list[tuple[int, int]] = []
    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
        on_batch_start=lambda index, total: received.append((index, total)),
    )
    provider = _FakeProvider()
    _run_job(job, provider, _units(2))

    assert received == [(1, 1)]


def test_start_delegates_to_the_provided_thread_runner() -> None:
    """A custom thread_runner (e.g. Flet's page.run_thread) must be used.

    A bare threading.Thread runs outside a Flet page's session executor,
    so its UI updates can sit unflushed until an unrelated client
    round-trip happens to pump them through. Callers embedding this in a
    UI must be able to supply their own runner instead.
    """
    calls: list[tuple[Any, ...]] = []

    def _immediate_runner(target: Any, *args: Any) -> None:
        calls.append(args)
        target(*args)

    completions: list[JobProgress] = []
    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=lambda _p: None,
        on_complete=completions.append,
        thread_runner=_immediate_runner,
    )
    job.start(_units(2), _FakeProvider(), "english", "french")

    assert len(calls) == 1
    assert completions[-1].finished is True


def test_is_cancelled_is_forwarded_to_provider() -> None:
    class _RecordingProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            assert request.is_cancelled is not None
            assert request.is_cancelled() is False
            return super().translate_batch(request)

    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
    )
    _run_job(job, _RecordingProvider(), _units(2))


def test_implausible_translation_is_rejected_as_failed() -> None:
    """A wildly longer, unrelated translation must not count as done."""

    class _HallucinatingProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            translations = [
                {
                    "block_id": u["block_id"],
                    "translated_text": "<h1>Quick saves</h1>" * 5,
                }
                for u in request.units
            ]
            return TranslateBatchResult(translations=translations, failed_ids=[])

    chunks: list[TranslateBatchResult] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
    )
    _run_job(job, _HallucinatingProvider(), [{"block_id": "a", "source_text": "Save"}])

    assert chunks[0].translations == []
    assert chunks[0].failed_ids == ["a"]
    assert job.progress.done == 0
    assert job.progress.failed == 1


def test_plausible_translation_still_counts_as_done() -> None:
    chunks: list[TranslateBatchResult] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
    )
    _run_job(job, _FakeProvider(), _units(3))

    assert len(chunks[0].translations) == 3
    assert chunks[0].failed_ids == []


def test_length_warning_alone_does_not_reject_the_translation() -> None:
    """A short source text legitimately expanding a lot in French must pass.

    French is naturally longer than English, and that ratio is highly
    volatile on short strings (menu labels, buttons) — length_warning
    alone should never block an AI suggestion, only a warning shown
    during manual validation.
    """

    class _ShortStringProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            translations = [
                {"block_id": u["block_id"], "translated_text": "D'accord"}
                for u in request.units
            ]
            return TranslateBatchResult(translations=translations, failed_ids=[])

    chunks: list[TranslateBatchResult] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
    )
    _run_job(job, _ShortStringProvider(), [{"block_id": "a", "source_text": "OK"}])

    assert chunks[0].translations == [{"block_id": "a", "translated_text": "D'accord"}]
    assert chunks[0].failed_ids == []


def test_missing_tag_is_accepted_with_a_warning_event() -> None:
    """A dropped Ren'Py tag must not discard an otherwise good translation.

    Small models reliably drop tags they don't recognize even when told
    to preserve them — rejecting the whole suggestion over that throws
    away translations that are largely correct. It should land as
    ai_suggested with a warning event instead, so the review UI can flag
    it for a quick manual fix.
    """

    class _DroppedTagProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            translations = [
                {"block_id": u["block_id"], "translated_text": "Continuer"}
                for u in request.units
            ]
            return TranslateBatchResult(translations=translations, failed_ids=[])

    chunks: list[TranslateBatchResult] = []
    events: list[str] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
        on_event=events.append,
    )
    _run_job(
        job, _DroppedTagProvider(), [{"block_id": "a", "source_text": "{p}Continue"}]
    )

    assert chunks[0].translations == [{"block_id": "a", "translated_text": "Continuer"}]
    assert chunks[0].failed_ids == []
    assert any("warning" in e for e in events)


def test_missing_variable_is_rejected_as_failed() -> None:
    """Unlike a missing tag, a missing interpolated variable must reject.

    A dropped [variable_name] would break at runtime or lose information,
    unlike a cosmetic Ren'Py tag — this must still block the suggestion.
    """

    class _DroppedVarProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            translations = [
                {"block_id": u["block_id"], "translated_text": "Bonjour !"}
                for u in request.units
            ]
            return TranslateBatchResult(translations=translations, failed_ids=[])

    chunks: list[TranslateBatchResult] = []
    _run_job(
        TranslationJob(
            on_chunk=chunks.append,
            on_progress=lambda _p: None,
            on_complete=lambda _p: None,
        ),
        _DroppedVarProvider(),
        [{"block_id": "a", "source_text": "Hello [player_name]!"}],
    )

    assert chunks[0].translations == []
    assert chunks[0].failed_ids == ["a"]


def test_units_with_only_special_chars_skip_the_provider() -> None:
    chunks: list[TranslateBatchResult] = []
    events: list[str] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
        on_event=events.append,
    )
    provider = _FakeProvider()
    units = [
        {"block_id": "a", "source_text": "..."},
        {"block_id": "b", "source_text": "Hello"},
    ]
    _run_job(job, provider, units)

    assert len(provider.requests) == 1
    assert [u["block_id"] for u in provider.requests[0].units] == ["b"]
    assert chunks[0].translations == [{"block_id": "a", "translated_text": "..."}]
    assert job.progress.done == 2
    assert any("automatically" in e for e in events)


def test_units_with_tag_wrapped_special_chars_skip_the_provider() -> None:
    chunks: list[TranslateBatchResult] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
    )
    provider = _FakeProvider()
    units = [
        {"block_id": "a", "source_text": "...{w=0.5}"},
        {"block_id": "b", "source_text": "Hello"},
    ]
    _run_job(job, provider, units)

    assert [u["block_id"] for u in provider.requests[0].units] == ["b"]
    assert chunks[0].translations == [
        {"block_id": "a", "translated_text": "...{w=0.5}"}
    ]


def test_translation_identical_to_source_is_rejected() -> None:
    class _EchoProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            translations = [
                {"block_id": u["block_id"], "translated_text": u["source_text"]}
                for u in request.units
            ]
            return TranslateBatchResult(translations=translations, failed_ids=[])

    chunks: list[TranslateBatchResult] = []
    events: list[str] = []
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
        on_event=events.append,
    )
    _run_job(job, _EchoProvider(), [{"block_id": "a", "source_text": "Hello world"}])

    assert chunks[0].translations == []
    assert chunks[0].failed_ids == ["a"]
    assert any("identical" in e for e in events)


def test_provider_failure_emits_an_event() -> None:
    class _FailingProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            return TranslateBatchResult(
                translations=[], failed_ids=[u["block_id"] for u in request.units]
            )

    events: list[str] = []
    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
        on_event=events.append,
    )
    _run_job(job, _FailingProvider(), _units(2))

    assert any("failed" in e for e in events)


def test_provider_error_sets_clean_message_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A foreseeable failure (e.g. unreachable server) must not dump a
    traceback to the console — only truly unexpected exceptions should.
    """

    class _UnreachableProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            raise TranslationProviderError("Impossible de contacter le serveur.")

    completions: list[JobProgress] = []
    with caplog.at_level(logging.WARNING, logger="core.translation.job"):
        job = TranslationJob(
            on_chunk=lambda _r: None,
            on_progress=lambda _p: None,
            on_complete=completions.append,
        )
        _run_job(job, _UnreachableProvider(), _units(2))

    assert completions[-1].error == "Impossible de contacter le serveur."
    assert not any(record.exc_info for record in caplog.records)


def test_retry_recovers_units_that_failed_the_main_pass() -> None:
    """A unit failing the main pass but succeeding on retry must count as done."""

    class _FailsOnceProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            self.requests.append(request)
            if len(self.requests) == 1:
                return TranslateBatchResult(
                    translations=[],
                    failed_ids=[u["block_id"] for u in request.units],
                )
            translations = [
                {"block_id": u["block_id"], "translated_text": f"{u['source_text']}!"}
                for u in request.units
            ]
            return TranslateBatchResult(translations=translations, failed_ids=[])

    chunks: list[TranslateBatchResult] = []
    events: list[str] = []
    provider = _FailsOnceProvider()
    job = TranslationJob(
        on_chunk=chunks.append,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
        on_event=events.append,
    )
    _run_job(job, provider, _units(3))

    assert job.progress.done == 3
    assert job.progress.failed == 0
    assert len(chunks) == 2
    assert chunks[0].failed_ids == ["0", "1", "2"]
    assert {t["block_id"] for t in chunks[1].translations} == {"0", "1", "2"}
    assert any("Retrying" in e for e in events)


def test_retry_exhausts_passes_then_reports_still_failing_units() -> None:
    """Units failing every retry pass must stay counted as failed, not lost."""

    class _AlwaysFailingProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            self.requests.append(request)
            return TranslateBatchResult(
                translations=[], failed_ids=[u["block_id"] for u in request.units]
            )

    events: list[str] = []
    provider = _AlwaysFailingProvider()
    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=lambda _p: None,
        on_complete=lambda _p: None,
        on_event=events.append,
    )
    _run_job(job, provider, _units(2))

    assert job.progress.done == 0
    assert job.progress.failed == 2
    # main pass (1 request) + retry pass with chunk_size=8 (1 request) +
    # retry pass with chunk_size=1 (1 request per unit, 2 requests).
    assert len(provider.requests) == 4
    assert sum("Retrying" in e for e in events) == 2


def test_retry_stops_when_cancelled_between_retry_chunks() -> None:
    """Cancellation mid-retry must stop further attempts, keeping counts sane."""

    class _RecoverAfterFirstRetryChunk(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            self.requests.append(request)
            if len(self.requests) == 1:
                return TranslateBatchResult(
                    translations=[],
                    failed_ids=[u["block_id"] for u in request.units],
                )
            translations = [
                {"block_id": u["block_id"], "translated_text": f"{u['source_text']}!"}
                for u in request.units
            ]
            return TranslateBatchResult(translations=translations, failed_ids=[])

    provider = _RecoverAfterFirstRetryChunk()
    progress_calls = [0]

    def _cancel_on_second_progress(_p: JobProgress) -> None:
        progress_calls[0] += 1
        if progress_calls[0] == 2:
            job.cancel()

    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=_cancel_on_second_progress,
        on_complete=lambda _p: None,
    )
    _run_job(job, provider, _units(10))

    assert job.progress.done == 8
    assert job.progress.failed == 2
    assert job.progress.done + job.progress.failed == 10
    # main pass (1 request) + one retry sub-chunk of 8 before cancellation stops it.
    assert len(provider.requests) == 2


def test_cancel_stops_before_next_chunk() -> None:
    class _SlowProvider(_FakeProvider):
        def translate_batch(
            self, request: TranslateBatchRequest
        ) -> TranslateBatchResult:
            result = super().translate_batch(request)
            time.sleep(0.05)
            return result

    completions: list[JobProgress] = []
    job = TranslationJob(
        on_chunk=lambda _r: None,
        on_progress=lambda _p: job.cancel(),
        on_complete=completions.append,
    )
    provider = _SlowProvider()
    _run_job(job, provider, _units(150))

    assert completions[-1].done < 150
