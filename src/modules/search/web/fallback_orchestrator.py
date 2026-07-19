# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Fallback orchestrator for Bing web search integration.

When the unified search endpoint returns all three layers empty (entities,
sources, answer), this module kicks in to:

1. **Detect** the three-tier empty state (``detect_three_tier_empty``).
2. **Trigger** Bing web search via the injected ``BingSearchProtocol``
   implementation, with full graceful degradation
   (``trigger_web_search``).
3. **Schedule** a single background task that runs the full pipeline for
   each Bing result URL **sequentially**, so the article enters the
   normal ingestion → processing → knowledge graph flow
   (``schedule_pipeline_background``).

The orchestrator is intentionally stateless — all state lives in the
caller (``background_tasks`` set owned by the search endpoint module).
This keeps the orchestrator trivially testable and reusable.

Architecture:
    - Reuses ``core.protocols.services.PipelineService`` directly instead
      of declaring a narrow duplicate Protocol (DRY). The orchestrator
      only invokes ``run_full_pipeline`` on it; other methods on the
      Protocol are unused but harmless.
    - ``BingSearchProtocol | None`` is accepted explicitly so the
      orchestrator can degrade to [] when Bing is disabled at the
      container level (``settings.bing.enabled == False``).
    - ``detect_three_tier_empty`` is sync (pure check),
      ``trigger_web_search`` is async (awaits ``bing_searcher.search``),
      ``schedule_pipeline_background`` is sync (fire-and-forget task
      creation).

DuckDB Write Lock Convention (HIGH-1):
    ``schedule_pipeline_background`` creates a SINGLE background task
    that processes URLs SEQUENTIALLY (for-loop with per-URL timeout),
    matching the project convention in
    ``src/api/endpoints/content/pipeline.py:285`` (_execute_trigger_background).
    Each ``run_full_pipeline`` call performs bulk_insert_raw which holds
    a write lock on DuckDB; concurrent calls would contend on the same
    lock and trigger exponential backoff retries that are slower than
    serializing. Per-URL timeout (300s) still applies so one slow URL
    cannot block the entire batch.

Security:
    - Bing result URLs are NOT re-validated here — the downstream
      ``run_full_pipeline`` is responsible for invoking the project's
      URL safety checks (SSRF / PhishTank / URLhaus) via the normal
      ingestion pipeline path. This layer treats URLs as opaque strings.
    - ``trigger_web_search`` never raises; all exceptions are caught
      and logged via ``log.warning("web_search_failed", error=...)``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from core.protocols.services import PipelineService
from modules.search.web.protocol import BingSearchProtocol, BingSearchResult

if TYPE_CHECKING:
    from collections.abc import Iterable

log = get_logger(__name__)


# Per-URL timeout for background pipeline execution (5 minutes). Keeps one
# slow URL (e.g., slow source site, hung fetcher) from blocking the entire
# batch, while still allowing the background task to make progress.
# Matches _TRIGGER_SOURCE_TIMEOUT_SECONDS in src/api/endpoints/content/pipeline.py.
_PIPELINE_URL_TIMEOUT_SECONDS = 300.0


def detect_three_tier_empty(result: Any) -> bool:
    """Return True iff all three search layers are empty.

    Three layers (R-web-search-004):
        - ``entities``: list[str] — entity neighborhood from local search
        - ``sources``: list[dict] — article sources used to build the answer
        - ``answer``: str — LLM-synthesized narrative (or empty string)

    Args:
        result: ``SearchResult`` instance (duck-typed) or dict with the
            same keys. ``None`` or unexpected types return ``False``
            (conservative: do NOT trigger Bing on uncertain inputs).

    Returns:
        True iff all three layers are empty (after stripping ``answer``).
        False if any layer is non-empty OR the input is invalid.
    """
    # Conservative: None or unexpected type → False (don't trigger Bing).
    if result is None:
        return False
    if isinstance(result, dict):
        entities = result.get("entities", []) or []
        sources = result.get("sources", []) or []
        answer = result.get("answer", "") or ""
    elif hasattr(result, "entities") and hasattr(result, "sources") and hasattr(result, "answer"):
        entities = result.entities or []
        sources = result.sources or []
        answer = result.answer or ""
    else:
        # Unexpected type → conservative False.
        return False

    # All three must be empty. answer is stripped to catch whitespace-only.
    return len(entities) == 0 and len(sources) == 0 and not str(answer).strip()


async def trigger_web_search(
    query: str,
    bing_searcher: BingSearchProtocol | None,
) -> list[BingSearchResult]:
    """Invoke BingSearcher.search with full graceful degradation.

    R-web-search-005: Bing must NEVER block the main search flow. All
    failure paths return ``[]`` rather than raising.

    Args:
        query: User search query (already validated by caller).
        bing_searcher: ``BingSearchProtocol`` implementation, or ``None``
            if Bing is disabled at the container level
            (``settings.bing.enabled == False``).

    Returns:
        List of ``BingSearchResult`` (possibly empty). Empty list on:
        - ``bing_searcher is None`` (Bing disabled)
        - ``bing_searcher.search()`` raises any exception (TimeoutError,
          RuntimeError, network errors, parser bugs)
        - Bing returns zero results
    """
    if bing_searcher is None:
        log.info("web_search_skipped_bing_disabled")
        return []

    try:
        results = await bing_searcher.search(query)
    except Exception as exc:
        # Catch all — Bing is a fallback path; any failure degrades to [].
        # Includes TimeoutError, RuntimeError, network errors, parser bugs.
        log.warning(
            "web_search_failed",
            query_prefix=query[:50] if isinstance(query, str) else "",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return []

    # BingSearchProtocol.search may return None in degenerate cases —
    # normalize to [] for caller convenience.
    if results is None:
        return []
    return list(results)


def schedule_pipeline_background(
    urls: Iterable[str],
    pipeline_service: PipelineService,
    background_tasks: set[asyncio.Task],
) -> None:
    """Fire-and-forget background task that ingests all URLs sequentially.

    R-web-search-006: URLs are processed by ``pipeline_service.run_full_pipeline``
    inside a SINGLE background task. URLs are processed SEQUENTIALLY (not
    concurrently) to avoid DuckDB write lock contention — matches the
    convention in ``src/api/endpoints/content/pipeline.py:285``
    (``_execute_trigger_background``).

    Each ``run_full_pipeline`` performs bulk_insert_raw which holds a
    write lock on DuckDB; concurrent calls would contend on the same
    lock and trigger exponential backoff retries that are slower than
    serializing (HIGH-1: DuckDB concurrent write conflict). Per-URL
    timeout (300s) still applies so one slow URL cannot block the batch.

    Args:
        urls: Iterable of URL strings to ingest. Empty iterable → no-op
            (returns immediately without creating a task).
        pipeline_service: ``PipelineService`` implementation (typically
            ``PipelineServiceImpl`` from the container).
        background_tasks: Set owned by the caller (e.g., the search
            endpoint module's ``_background_tasks: set[asyncio.Task]``).
            Mutated in-place: task added on entry, removed on completion.

    Notes:
        - This function is sync and returns immediately (fire-and-forget).
        - Single task processes all URLs sequentially with per-URL timeout
          (300s) so one slow URL cannot block the batch.
        - Per-URL exceptions are isolated: a failure on one URL does NOT
          abort the for-loop; the next URL is still attempted.
        - URL safety (SSRF/PhishTank/URLhaus) is enforced downstream by
          the pipeline's ingestion layer, NOT here.
    """
    # Materialize and filter URLs eagerly so the background task works
    # on a stable list (avoid "iterable exhausted" issues if caller's
    # generator is single-use, and skip invalid entries upfront).
    url_list = [u for u in urls if isinstance(u, str) and u]
    if not url_list:
        return

    task = asyncio.create_task(_run_pipelines_sequentially(pipeline_service, url_list))
    background_tasks.add(task)
    # GC protection: remove from set when done (success or failure).
    task.add_done_callback(background_tasks.discard)
    # Exception isolation safety net: log uncaught exceptions.
    task.add_done_callback(_log_pipeline_task_exception)


async def _run_pipelines_sequentially(
    pipeline_service: PipelineService,
    urls: list[str],
) -> None:
    """Run pipeline for each URL sequentially with per-URL timeout.

    Sequential execution (not ``asyncio.gather``): each
    ``run_full_pipeline`` performs bulk_insert_raw which holds a write
    lock on DuckDB. Concurrent calls would contend on the same lock and
    trigger exponential backoff retries that are slower than serializing
    (HIGH-1: DuckDB concurrent write conflict). Per-URL timeout still
    applies so one slow URL cannot block the entire batch.

    Matches the convention in ``src/api/endpoints/content/pipeline.py:285``
    (``_execute_trigger_background``).

    Per-URL exception isolation: each URL's failure is caught and logged;
    the for-loop continues to the next URL. This achieves the same
    isolation guarantee as separate asyncio tasks, but without write-lock
    contention.

    Args:
        pipeline_service: ``PipelineService`` implementation.
        urls: List of URL strings (already filtered for non-empty str).
    """
    for url in urls:
        try:
            await asyncio.wait_for(
                pipeline_service.run_full_pipeline(url),
                timeout=_PIPELINE_URL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log.warning(
                "pipeline_background_task_timeout",
                url=url[:200],  # truncate to avoid log explosion on huge URLs
                timeout=_PIPELINE_URL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            # Catch all — one URL's failure must NOT abort the batch.
            # Includes RuntimeError, network errors, pipeline-internal
            # exceptions. CancelledError is BaseException (not caught
            # here) so task cancellation still propagates correctly.
            log.warning(
                "pipeline_background_task_failed",
                url=url[:200],
                error=str(exc),
                error_type=type(exc).__name__,
            )


def _log_pipeline_task_exception(task: asyncio.Task) -> None:
    """Done callback: log uncaught exceptions as a safety net.

    ``_run_pipelines_sequentially`` already catches and logs per-URL
    exceptions, but if a future refactor bypasses that wrapper (e.g.,
    raises CancelledError unexpectedly, or an unknown BaseException),
    this callback ensures no exception is silently swallowed.
    ``task.exception()`` returns None for successful tasks or
    CancelledError for cancelled ones.
    """
    if task.cancelled():
        log.info("pipeline_background_task_cancelled")
        return
    exc = task.exception()
    if exc is not None:
        # _run_pipelines_sequentially already logged per-URL; this is a
        # safety net for unexpected exceptions that escape the wrapper
        # (shouldn't happen but defense-in-depth).
        log.error(
            "pipeline_background_task_uncaught_exception",
            error=str(exc),
            error_type=type(exc).__name__,
        )
