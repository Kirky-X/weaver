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
