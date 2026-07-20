# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for fallback_orchestrator (web search module).

TDD Red phase: tests fail until ``detect_three_tier_empty``,
``trigger_web_search``, and ``schedule_pipeline_background`` are
implemented in ``src/modules/search/web/fallback_orchestrator.py``
(T008/T010/T012 Green).

These three functions form the Bing fallback orchestration layer:
    1. ``detect_three_tier_empty``: checks if all three search layers
       (entities / sources / answer) returned empty — triggers Bing.
    2. ``trigger_web_search``: invokes BingSearcher.search with graceful
       degradation (never raises, returns [] on any failure).
    3. ``schedule_pipeline_background``: fire-and-forget pipeline tasks
       for each Bing result URL, using the project's _background_tasks GC
       pattern (add + add_done_callback(discard)).

HIGH-1 fix verification: ``schedule_pipeline_background`` now creates
a SINGLE background task that processes URLs SEQUENTIALLY (not N
concurrent tasks). This matches the DuckDB write-lock serialization
convention in ``src/api/endpoints/content/pipeline.py:285``
(``_execute_trigger_background``). Tests verify:
    - Empty urls → no task created.
    - 1 URL → 1 task created, pipeline called once.
    - N URLs → 1 task created, pipeline called N times sequentially.
    - One URL's failure does NOT abort the for-loop.
    - Sequential (not concurrent) execution verified via ordering.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.search.web.bing_searcher import BingSearcher
from modules.search.web.fallback_orchestrator import (
    _PIPELINE_BATCH_TOTAL_TIMEOUT_SECONDS,
    _PIPELINE_URL_TIMEOUT_SECONDS,
    ScheduleResult,
    detect_three_tier_empty,
    schedule_pipeline_background,
    trigger_web_search,
)
from modules.search.web.protocol import BingSearchResult


def _make_search_result(
    *,
    answer: str = "",
    entities: list[str] | None = None,
    sources: list[dict] | None = None,
) -> SimpleNamespace:
    """Build a duck-typed SearchResult stand-in.

    Mirrors modules.knowledge.search.engines.local_search.SearchResult
    without importing it (avoids pulling engine dependencies into unit
    tests). fallback_orchestrator uses duck typing on these three fields.
    """
    return SimpleNamespace(
        answer=answer,
        entities=entities if entities is not None else [],
        sources=sources if sources is not None else [],
    )


def _make_bing_result(
    title: str = "T", url: str = "https://example.com/x", snippet: str = "S"
) -> BingSearchResult:
    """Build a BingSearchResult for test assertions."""
    return BingSearchResult(title=title, url=url, snippet=snippet)


class TestDetectThreeTierEmpty:
    """Tests for detect_three_tier_empty (R-web-search-004)."""

    def test_all_three_empty_returns_true(self) -> None:
        """All three layers empty (entities=[], sources=[], answer='') → True."""
        result = _make_search_result(answer="", entities=[], sources=[])
        assert detect_three_tier_empty(result) is True

    def test_entities_non_empty_returns_false(self) -> None:
        """entities non-empty → False (any layer non-empty disqualifies)."""
        result = _make_search_result(answer="", entities=["apple"], sources=[])
        assert detect_three_tier_empty(result) is False

    def test_sources_non_empty_returns_false(self) -> None:
        """sources non-empty → False."""
        result = _make_search_result(answer="", entities=[], sources=[{"title": "x"}])
        assert detect_three_tier_empty(result) is False

    def test_answer_non_empty_returns_false(self) -> None:
        """answer non-empty (after strip) → False."""
        result = _make_search_result(answer="Some meaningful answer", entities=[], sources=[])
        assert detect_three_tier_empty(result) is False

    def test_answer_whitespace_only_treated_as_empty(self) -> None:
        """answer with only whitespace should be treated as empty (stripped)."""
        result = _make_search_result(answer="   \n\t  ", entities=[], sources=[])
        assert detect_three_tier_empty(result) is True

    def test_dict_input_all_empty_returns_true(self) -> None:
        """Dict input (alternative engine return format) must be supported."""
        result_dict = {"answer": "", "entities": [], "sources": []}
        assert detect_three_tier_empty(result_dict) is True

    def test_dict_input_sources_non_empty_returns_false(self) -> None:
        """Dict input with non-empty sources → False."""
        result_dict = {"answer": "", "entities": [], "sources": [{"x": 1}]}
        assert detect_three_tier_empty(result_dict) is False

    def test_dict_input_missing_fields_treated_as_empty(self) -> None:
        """Dict missing some fields should treat them as empty (defensive)."""
        result_dict = {"answer": ""}
        # entities / sources missing → treated as [] → all empty → True
        assert detect_three_tier_empty(result_dict) is True

    def test_none_input_returns_false(self) -> None:
        """None input must return False (conservative: don't trigger Bing)."""
        assert detect_three_tier_empty(None) is False  # type: ignore[arg-type]

    def test_unexpected_type_returns_false(self) -> None:
        """Unexpected input type (int/str/list) must return False."""
        assert detect_three_tier_empty(42) is False  # type: ignore[arg-type]
        assert detect_three_tier_empty("string") is False  # type: ignore[arg-type]
        assert detect_three_tier_empty([1, 2, 3]) is False  # type: ignore[arg-type]


class TestTriggerWebSearch:
    """Tests for trigger_web_search (R-web-search-005)."""

    @pytest.mark.asyncio
    async def test_bing_searcher_none_returns_empty_list(self) -> None:
        """bing_searcher=None (container disabled) → [] without raising."""
        results = await trigger_web_search("query", None)
        assert results == []

    @pytest.mark.asyncio
    async def test_bing_searcher_returns_results(self) -> None:
        """Normal path: bing_searcher.search() returns list of BingSearchResult."""
        expected = [
            _make_bing_result(title="A", url="https://a.com"),
            _make_bing_result(title="B", url="https://b.com"),
        ]
        bing_searcher = MagicMock(spec=BingSearcher)
        bing_searcher.search = AsyncMock(return_value=expected)
        results = await trigger_web_search("query", bing_searcher)
        assert results == expected
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_bing_searcher_raises_returns_empty_list(self) -> None:
        """If bing_searcher.search() raises, return [] (not propagate).

        R-web-search-005: must not block main search flow.
        """
        bing_searcher = MagicMock(spec=BingSearcher)
        bing_searcher.search = AsyncMock(side_effect=RuntimeError("network down"))
        results = await trigger_web_search("query", bing_searcher)
        assert results == []

    @pytest.mark.asyncio
    async def test_bing_searcher_raises_timeout_returns_empty_list(self) -> None:
        """TimeoutError from bing_searcher.search() must also degrade to []."""
        bing_searcher = MagicMock(spec=BingSearcher)
        bing_searcher.search = AsyncMock(side_effect=TimeoutError())
        results = await trigger_web_search("query", bing_searcher)
        assert results == []

    @pytest.mark.asyncio
    async def test_bing_searcher_returns_empty_list_passes_through(self) -> None:
        """If bing_searcher.search() returns [], pass through (no Bing results)."""
        bing_searcher = MagicMock(spec=BingSearcher)
        bing_searcher.search = AsyncMock(return_value=[])
        results = await trigger_web_search("query", bing_searcher)
        assert results == []

    @pytest.mark.asyncio
    async def test_trigger_web_search_passes_query_to_searcher(self) -> None:
        """The query string must be forwarded to bing_searcher.search()."""
        bing_searcher = MagicMock(spec=BingSearcher)
        bing_searcher.search = AsyncMock(return_value=[])
        await trigger_web_search("specific query text", bing_searcher)
        bing_searcher.search.assert_awaited_once_with("specific query text")


class TestSchedulePipelineBackground:
    """Tests for schedule_pipeline_background (R-web-search-006).

    HIGH-1 fix: N URLs → SINGLE background task that processes URLs
    SEQUENTIALLY (not N concurrent tasks). This matches the DuckDB
    write-lock serialization convention in
    ``src/api/endpoints/content/pipeline.py:285``.
    """

    @pytest.mark.asyncio
    async def test_empty_urls_creates_no_tasks(self) -> None:
        """Empty urls list must not create any asyncio.Task."""
        pipeline_service = MagicMock()
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background([], pipeline_service, background_tasks)
        assert len(background_tasks) == 0
        # No task should have been scheduled.
        assert not pipeline_service.run_full_pipeline.called

    @pytest.mark.asyncio
    async def test_single_url_creates_one_task(self) -> None:
        """One URL → one asyncio.Task added to background_tasks set."""
        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value={"status": "ok"})

        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(
            ["https://example.com/article1"], pipeline_service, background_tasks
        )

        # Task should be added to the set immediately (before await).
        assert len(background_tasks) == 1

        # Wait for the task to complete (allow pipeline to be called).
        await asyncio.gather(*background_tasks)

        # After completion, the done_callback should have removed it from set.
        assert len(background_tasks) == 0
        pipeline_service.run_full_pipeline.assert_awaited_once_with("https://example.com/article1")

    @pytest.mark.asyncio
    async def test_multiple_urls_create_single_task_sequential(self) -> None:
        """HIGH-1: N URLs → SINGLE task, pipeline called N times sequentially.

        Old behavior (N concurrent tasks) caused DuckDB write-lock
        contention. New behavior: 1 task, for-loop, matches
        pipeline.py:285 convention.
        """
        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value={"status": "ok"})

        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(urls, pipeline_service, background_tasks)

        # HIGH-1 fix: only ONE task should be created (not 3).
        assert len(background_tasks) == 1

        # Wait for completion.
        await asyncio.gather(*background_tasks)

        # Task removed by done_callback.
        assert len(background_tasks) == 0
        # Pipeline called 3 times (sequentially within the single task).
        assert pipeline_service.run_full_pipeline.await_count == 3
        # Verify each URL was passed.
        awaited_urls = [call.args[0] for call in pipeline_service.run_full_pipeline.await_args_list]
        assert awaited_urls == urls

    @pytest.mark.asyncio
    async def test_task_calls_run_full_pipeline_with_url(self) -> None:
        """Each task must call pipeline_service.run_full_pipeline(url)."""
        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value={"status": "ok"})

        url = "https://example.com/specific"
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background([url], pipeline_service, background_tasks)
        await asyncio.gather(*background_tasks)

        pipeline_service.run_full_pipeline.assert_awaited_once_with(url)

    @pytest.mark.asyncio
    async def test_function_does_not_await_tasks(self) -> None:
        """schedule_pipeline_background must be fire-and-forget (not await tasks).

        Verify by making run_full_pipeline block on an event; the function
        must return before the task completes.
        """
        call_event = asyncio.Event()

        async def slow_pipeline(url: str) -> dict:
            await call_event.wait()
            return {"status": "ok"}

        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = slow_pipeline

        background_tasks: set[asyncio.Task] = set()
        # This should return immediately (fire-and-forget).
        schedule_pipeline_background(
            ["https://example.com/slow"], pipeline_service, background_tasks
        )

        # Task should be in set but not yet complete (pipeline is blocked).
        assert len(background_tasks) == 1
        task = next(iter(background_tasks))
        assert not task.done()

        # Release the pipeline.
        call_event.set()
        await task
        # done_callback should have removed it.
        assert len(background_tasks) == 0

    @pytest.mark.asyncio
    async def test_url_exception_does_not_abort_sequential_batch(self) -> None:
        """HIGH-1: one URL's failure must NOT abort the sequential for-loop.

        Old test (N tasks) verified exception isolation via separate
        asyncio tasks. New test verifies the same guarantee via
        per-URL try/except inside the single sequential task.
        """
        call_count = {"fail": 0, "ok": 0}

        async def pipeline_with_failure(url: str) -> dict:
            if "fail" in url:
                call_count["fail"] += 1
                raise RuntimeError("pipeline failure")
            call_count["ok"] += 1
            return {"status": "ok"}

        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = pipeline_with_failure

        urls = ["https://example.com/ok1", "https://example.com/fail", "https://example.com/ok2"]
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(urls, pipeline_service, background_tasks)

        # HIGH-1: only one task created.
        assert len(background_tasks) == 1

        # Wait for the single task to complete (no exception propagates
        # because per-URL exceptions are caught inside the for-loop).
        await asyncio.gather(*background_tasks)

        # Task removed by done_callback.
        assert len(background_tasks) == 0
        # All 3 URLs attempted (fail did NOT abort the for-loop).
        assert call_count["ok"] == 2
        assert call_count["fail"] == 1

    @pytest.mark.asyncio
    async def test_urls_processed_sequentially_not_concurrently(self) -> None:
        """HIGH-1: URLs must be processed SEQUENTIALLY (no overlap).

        Verify by recording start/finish timestamps for each URL's
        pipeline call. Sequential → timestamps do NOT overlap.
        Concurrent → timestamps would overlap.
        """
        # Track active pipeline calls; sequential execution → max 1 active
        # at any time. Concurrent execution → could be >1.
        active_count = 0
        max_active = 0
        call_order: list[str] = []

        async def tracking_pipeline(url: str) -> dict:
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            call_order.append(f"start:{url}")
            # Yield to event loop to allow other tasks to run if scheduled.
            await asyncio.sleep(0.01)
            call_order.append(f"end:{url}")
            active_count -= 1
            return {"status": "ok"}

        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = tracking_pipeline

        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(urls, pipeline_service, background_tasks)

        # Only one task created.
        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)

        # HIGH-1 assertion: max 1 active pipeline call at any time
        # (sequential execution, no overlap).
        assert (
            max_active == 1
        ), f"Expected sequential execution (max_active=1), got max_active={max_active}"
        # All 3 URLs processed.
        assert len(call_order) == 6  # 3 starts + 3 ends
        # Verify order: start:a, end:a, start:b, end:b, start:c, end:c
        assert call_order == [
            "start:https://example.com/a",
            "end:https://example.com/a",
            "start:https://example.com/b",
            "end:https://example.com/b",
            "start:https://example.com/c",
            "end:https://example.com/c",
        ]

    @pytest.mark.asyncio
    async def test_invalid_urls_filtered_silently(self) -> None:
        """Non-string or empty-string URLs must be filtered out silently."""
        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value={"status": "ok"})

        # Mix of valid + invalid URLs.
        urls = [
            "https://example.com/valid1",
            "",  # empty string → filtered
            None,  # None → filtered
            42,  # non-string → filtered
            "https://example.com/valid2",
        ]
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(urls, pipeline_service, background_tasks)  # type: ignore[arg-type]

        # One task created for the 2 valid URLs.
        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)

        # Only 2 valid URLs reached the pipeline.
        assert pipeline_service.run_full_pipeline.await_count == 2
        awaited_urls = [call.args[0] for call in pipeline_service.run_full_pipeline.await_args_list]
        assert awaited_urls == [
            "https://example.com/valid1",
            "https://example.com/valid2",
        ]

    @pytest.mark.asyncio
    async def test_single_generator_iterable_consumed_once(self) -> None:
        """Single-use generator as urls iterable must be materialized correctly.

        Regression: if the function passed the iterable directly to
        asyncio.create_task without materializing, the generator would
        be exhausted by the time the task runs.
        """
        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value={"status": "ok"})

        def url_generator():
            yield "https://example.com/gen1"
            yield "https://example.com/gen2"

        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(url_generator(), pipeline_service, background_tasks)

        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)

        # Both URLs from the generator must have been processed.
        assert pipeline_service.run_full_pipeline.await_count == 2


class TestSchedulePipelineBackgroundConcurrencyCap:
    """Tests for MEDIUM-1 fix: concurrency cap on background pipeline tasks.

    When ``len(background_tasks) >= max_concurrent``, the next call must
    drop (not spawn), log a warning, and return ``ScheduleResult.THROTTLED``.
    The ``background_tasks`` set itself is the registry of in-flight tasks
    (each task auto-removes via ``add_done_callback(set.discard)``), so
    ``len(set)`` is the live concurrency counter. This is functionally
    equivalent to an ``asyncio.Semaphore`` for the "drop at cap" use case
    (Rule 2: Simplicity First) and avoids the issue that
    ``asyncio.Semaphore.acquire`` is a coroutine (cannot be awaited from
    sync ``schedule_pipeline_background``).
    """

    @pytest.mark.asyncio
    async def test_at_cap_drops_ninth_task_returns_throttled(self) -> None:
        """8 tasks running → 9th call returns THROTTLED, no task spawned.

        Setup: pre-populate ``background_tasks`` with 8 placeholder tasks
        that block on an event (so they stay "running" for the test's
        duration). Then call ``schedule_pipeline_background`` with
        ``max_concurrent=8`` and assert it returns THROTTLED without
        adding to the set.
        """
        release_event = asyncio.Event()

        async def blocking_pipeline(url: str) -> dict:
            await release_event.wait()
            return {"status": "ok"}

        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = blocking_pipeline

        background_tasks: set[asyncio.Task] = set()
        # Pre-spawn 8 blocking tasks to fill the cap.
        for i in range(8):
            task = asyncio.create_task(blocking_pipeline(f"https://example.com/{i}"))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        # Yield to let tasks start running (so len() reflects in-flight count).
        await asyncio.sleep(0)
        assert len(background_tasks) == 8

        # 9th call must be throttled.
        result = schedule_pipeline_background(
            ["https://example.com/9th"],
            pipeline_service,
            background_tasks,
            max_concurrent=8,
        )
        assert result is ScheduleResult.THROTTLED
        # No new task added.
        assert len(background_tasks) == 8
        # pipeline_service.run_full_pipeline NOT called for the 9th URL
        # (the existing 8 calls are running; 9th was dropped before spawn).
        # Total await_count is still 8 (the 8 pre-spawned blocking calls).
        # We can't easily assert "9th not called" because the 8 are still
        # running — but we can verify no NEW task was added to the set.

        # Cleanup: release the event and let all tasks complete.
        release_event.set()
        await asyncio.gather(*background_tasks)

    @pytest.mark.asyncio
    async def test_below_cap_schedules_normally(self) -> None:
        """Fewer than max_concurrent tasks running → SCHEDULED returned.

        Verifies the non-throttled path still works after the cap logic
        was added (regression guard).
        """
        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value={"status": "ok"})

        background_tasks: set[asyncio.Task] = set()
        result = schedule_pipeline_background(
            ["https://example.com/1"],
            pipeline_service,
            background_tasks,
            max_concurrent=8,
        )
        assert result is ScheduleResult.SCHEDULED
        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)
        assert len(background_tasks) == 0  # auto-removed by done_callback

    @pytest.mark.asyncio
    async def test_cap_releases_on_task_completion(self) -> None:
        """After a task completes, len(background_tasks) decreases, allowing new tasks.

        Setup: spawn 8 blocking tasks, then release one, then verify the
        next ``schedule_pipeline_background`` call returns SCHEDULED.
        """
        release_event = asyncio.Event()

        async def blocking_pipeline(url: str) -> dict:
            await release_event.wait()
            return {"status": "ok"}

        pipeline_service_blocking = MagicMock()
        pipeline_service_blocking.run_full_pipeline = blocking_pipeline

        background_tasks: set[asyncio.Task] = set()
        # Fill the cap with 8 blocking tasks.
        for i in range(8):
            task = asyncio.create_task(blocking_pipeline(f"https://example.com/{i}"))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        await asyncio.sleep(0)
        assert len(background_tasks) == 8

        # 9th call → THROTTLED.
        result = schedule_pipeline_background(
            ["https://example.com/9th"],
            pipeline_service_blocking,
            background_tasks,
            max_concurrent=8,
        )
        assert result is ScheduleResult.THROTTLED

        # Release ONE task: set the event, all 8 will complete (they share
        # the same event), and the set will be drained to 0. We only need
        # one slot to free up — but since all 8 share the event, all 8
        # complete together. After they finish, the cap is fully released.
        release_event.set()
        await asyncio.gather(*background_tasks)
        assert len(background_tasks) == 0

        # Now scheduling again must succeed.
        pipeline_service_ok = MagicMock()
        pipeline_service_ok.run_full_pipeline = AsyncMock(return_value={"status": "ok"})
        result = schedule_pipeline_background(
            ["https://example.com/new"],
            pipeline_service_ok,
            background_tasks,
            max_concurrent=8,
        )
        assert result is ScheduleResult.SCHEDULED
        await asyncio.gather(*background_tasks)

    @pytest.mark.asyncio
    async def test_empty_urls_returns_skipped_empty(self) -> None:
        """No URLs (after filtering) → SKIPPED_EMPTY, no task spawned."""
        pipeline_service = MagicMock()
        background_tasks: set[asyncio.Task] = set()
        result = schedule_pipeline_background(
            [],
            pipeline_service,
            background_tasks,
            max_concurrent=8,
        )
        assert result is ScheduleResult.SKIPPED_EMPTY
        assert len(background_tasks) == 0

    @pytest.mark.asyncio
    async def test_at_cap_with_default_max_concurrent(self) -> None:
        """Default max_concurrent=8 → 9th task throttled without explicit arg.

        Regression: ensures the default value is applied when the caller
        does not pass ``max_concurrent`` (matches the production call
        site in ``search.py::search_unified``).
        """
        release_event = asyncio.Event()

        async def blocking_pipeline(url: str) -> dict:
            await release_event.wait()
            return {"status": "ok"}

        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = blocking_pipeline

        background_tasks: set[asyncio.Task] = set()
        for i in range(8):
            task = asyncio.create_task(blocking_pipeline(f"https://example.com/{i}"))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        await asyncio.sleep(0)

        # Call WITHOUT max_concurrent — must default to 8 and throttle.
        result = schedule_pipeline_background(
            ["https://example.com/9th"],
            pipeline_service,
            background_tasks,
        )
        assert result is ScheduleResult.THROTTLED

        release_event.set()
        await asyncio.gather(*background_tasks)


class TestRunPipelinesSequentiallyTotalTimeout:
    """Tests for MEDIUM-2 fix: total timeout on the sequential batch.

    Per-URL timeout (300s) bounds one slow URL, but with N URLs the
    total wall time was unbounded (N * 300s). The fix wraps the whole
    for-loop in ``asyncio.wait_for(total_timeout)`` (default 600s,
    configurable via ``WEAVER_SEARCH__BACKGROUND_TASK_TOTAL_TIMEOUT``).
    On timeout, pending URLs are cancelled (CancelledError propagates
    out of the for-loop, escaping the per-URL ``except Exception``).
    """

    @pytest.mark.asyncio
    async def test_total_timeout_cancels_pending_urls(self) -> None:
        """total_timeout fires → pending URLs NOT processed, task completes.

        Setup: 3 URLs, each takes 0.5s. Set total_timeout=0.1s so only
        the first URL (or none) starts; pending URLs must be cancelled.
        """
        started_urls: list[str] = []
        completed_urls: list[str] = []

        async def slow_pipeline(url: str) -> dict:
            started_urls.append(url)
            await asyncio.sleep(0.5)
            completed_urls.append(url)
            return {"status": "ok"}

        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = slow_pipeline

        background_tasks: set[asyncio.Task] = set()
        # Schedule with very short total_timeout so the batch is cancelled
        # before all 3 URLs complete.
        schedule_pipeline_background(
            [
                "https://example.com/url1",
                "https://example.com/url2",
                "https://example.com/url3",
            ],
            pipeline_service,
            background_tasks,
            max_concurrent=8,
            total_timeout=0.1,
        )

        # Wait for the task to complete (it must NOT hang).
        await asyncio.gather(*background_tasks, return_exceptions=True)

        # The task completed within the timeout (did not hang until 1.5s).
        # At most 1 URL was started (the first one); 2nd and 3rd must NOT
        # have been started because the total_timeout cancelled the batch.
        assert (
            len(started_urls) <= 1
        ), f"Expected at most 1 URL started before timeout, got {started_urls}"
        # No URL completed (each takes 0.5s, timeout fires at 0.1s).
        assert len(completed_urls) == 0

    @pytest.mark.asyncio
    async def test_total_timeout_does_not_fire_on_fast_batch(self) -> None:
        """Fast batch (each URL 0.01s, 3 URLs) → all complete, no timeout.

        Regression: ensures the total_timeout doesn't accidentally fire
        on batches that complete well within the budget.
        """
        pipeline_service = MagicMock()
        pipeline_service.run_full_pipeline = AsyncMock(return_value={"status": "ok"})

        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(
            [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
            ],
            pipeline_service,
            background_tasks,
            max_concurrent=8,
            total_timeout=10.0,  # generous budget
        )
        await asyncio.gather(*background_tasks)

        # All 3 URLs processed (no timeout cancellation).
        assert pipeline_service.run_full_pipeline.await_count == 3

    @pytest.mark.asyncio
    async def test_per_url_timeout_still_applies_inside_total(self) -> None:
        """Per-URL timeout (300s) still isolates slow URLs inside the total budget.

        Scenario: 2 URLs — first hangs longer than per-URL timeout, second
        is fast. Per-URL timeout fires for the first URL (logs warning,
        continues); second URL completes normally. Total budget is
        generous so the batch timeout does NOT fire.

        To keep the test fast, monkeypatch ``_PIPELINE_URL_TIMEOUT_SECONDS``
        to a small value via direct module attribute reassignment (the
        constant is read at call time inside ``_run_pipelines_sequentially``,
        so reassigning the module attribute takes effect for the duration
        of the test).
        """
        from modules.search.web import fallback_orchestrator as fo

        original = fo._PIPELINE_URL_TIMEOUT_SECONDS
        fo._PIPELINE_URL_TIMEOUT_SECONDS = 0.1  # type: ignore[attr-defined]
        try:
            call_log: list[str] = []

            async def pipeline_with_one_hang(url: str) -> dict:
                call_log.append(url)
                if "hang" in url:
                    await asyncio.sleep(1.0)  # exceeds per-URL timeout (0.1s)
                return {"status": "ok"}

            pipeline_service = MagicMock()
            pipeline_service.run_full_pipeline = pipeline_with_one_hang

            background_tasks: set[asyncio.Task] = set()
            schedule_pipeline_background(
                ["https://example.com/hang", "https://example.com/ok"],
                pipeline_service,
                background_tasks,
                max_concurrent=8,
                total_timeout=10.0,  # generous total budget
            )
            await asyncio.gather(*background_tasks)

            # Both URLs attempted (per-URL timeout did not abort the batch).
            assert len(call_log) == 2
            # The hang URL was attempted first; the ok URL was attempted
            # second (after per-URL timeout cancelled the hang URL).
            assert call_log == ["https://example.com/hang", "https://example.com/ok"]
        finally:
            fo._PIPELINE_URL_TIMEOUT_SECONDS = original

    @pytest.mark.asyncio
    async def test_total_timeout_default_value(self) -> None:
        """Default total_timeout == _PIPELINE_BATCH_TOTAL_TIMEOUT_SECONDS (600s).

        Regression: ensures the default value is exposed as a module
        constant and matches the documented default (Rule 21: docs
        and code must stay in sync).
        """
        assert _PIPELINE_BATCH_TOTAL_TIMEOUT_SECONDS == 600.0
        assert _PIPELINE_URL_TIMEOUT_SECONDS == 300.0
