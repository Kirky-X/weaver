# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Pipeline API endpoints for triggering and monitoring crawl tasks."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import json_repair
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from starlette.responses import StreamingResponse

from api.dependencies import (
    get_cache_client,
    get_relational_pool,
    get_source_scheduler,
)
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from config.settings import Settings
from container import get_settings
from core.constants import PipelineTaskStatus
from core.observability import get_logger, metrics
from core.protocols import CachePool, RelationalPool
from core.security.safe_echo import safe_echo as _safe_echo
from modules.ingestion import SourceScheduler
from modules.storage import ArticleRepo

log = get_logger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


# ── Request/Response Models ─────────────────────────────────────


class TriggerRequest(BaseModel):
    """Request model for triggering a pipeline run.

    Supports both singular ``source_id`` (legacy) and plural ``source_ids``.
    When both are provided, ``source_ids`` takes precedence. When neither is
    provided, all enabled sources are triggered.
    """

    source_id: str | None = Field(
        default=None,
        description="Specific source ID to crawl. If not provided, crawls all enabled sources.",
    )
    source_ids: list[str] | None = Field(
        default=None,
        description=(
            "List of source IDs to crawl. When provided, takes precedence over "
            "source_id. Must NOT be empty — an empty list returns 400 Bad Request."
        ),
    )
    force: bool = Field(
        default=False,
        description="Force re-crawl even for recently fetched URLs.",
    )
    max_items: int | None = Field(
        default=None,
        description="Maximum number of items to process per source (None for unlimited).",
    )


class TriggerResponse(BaseModel):
    """Response model for pipeline trigger."""

    task_id: str
    status: str = PipelineTaskStatus.QUEUED.value
    queued_at: str


class TaskStatusResponse(BaseModel):
    """Response model for task status query."""

    task_id: str
    status: str
    source_id: str | None = None
    queued_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    progress: int | None = None
    total: int | None = None
    error: str | None = None
    # Progress statistics fields
    total_processed: int = 0
    processing_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    pending_count: int = 0


class ProcessUrlRequest(BaseModel):
    """Request model for single URL processing."""

    url: str = Field(..., description="要处理的资讯网页URL")
    whitelist_mode: bool = Field(default=False, description="是否启用白名单模式")

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        """Validate URL has http/https scheme."""
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError("URL must use http or https protocol")
        if not parsed.hostname:
            raise ValueError("URL must include a hostname")
        return v


class ProcessUrlResponse(BaseModel):
    """Response model for single URL processing."""

    task_id: str
    status: str = PipelineTaskStatus.QUEUED.value
    queued_at: str


# ── Constants ───────────────────────────────────────────────────

TASK_QUEUE_KEY = "pipeline:task_queue"
TASK_STATUS_KEY = "pipeline:task_status"
QUEUE_DEPTH_GAUGE = metrics.pipeline_queue_depth

# SSE concurrency limiter (default 3 concurrent streams)
_sse_semaphore = asyncio.Semaphore(3)

# Per-source timeout for background trigger (5 minutes). Keeps one slow
# source from blocking the entire trigger batch, while still allowing the
# background task to make progress and update task status.
_TRIGGER_SOURCE_TIMEOUT_SECONDS = 300.0

# Strong references to fire-and-forget background tasks so they are not
# garbage-collected before completion (MEDIUM-1: asyncio.create_task GC risk).
# Tasks remove themselves via ``add_done_callback`` upon completion.
_background_tasks: set[asyncio.Task[None]] = set()


# ── Trigger Helpers ─────────────────────────────────────────────


def _collect_all_source_ids(scheduler: SourceScheduler) -> set[str]:
    """Collect the set of enabled source IDs from the scheduler.

    Args:
        scheduler: Source scheduler instance (Protocol-based).

    Returns:
        Set of source ID strings. Empty set if scheduler returns no sources.

    Raises:
        Exception: Re-raises any scheduler error so the caller can translate
            it into an HTTP 500 (database failure must be visible, not
            swallowed — see project rule "失败必须显性化").

    """
    sources = scheduler.list_enabled_sources()
    return {s.id for s in sources}


def _build_trigger_status_payload(
    task_id: str,
    status: str,
    **fields: Any,
) -> str:
    """Build a JSON task status payload for ``cache.hset``.

    Centralizes task status construction so RUNNING / COMPLETED / FAILED
    updates share a consistent shape (``task_id`` + ``status`` + extra
    fields) without duplicating the ``json.dumps`` boilerplate at every
    call site (LOW-2 performance: avoid repeating dict construction).

    Args:
        task_id: Task UUID string.
        status: ``PipelineTaskStatus`` value (queued/running/completed/failed).
        **fields: Additional fields to include in the payload (e.g.
            ``source_id``, ``queued_at``, ``error``).

    Returns:
        JSON string ready for ``cache.hset(TASK_STATUS_KEY, task_id, ...)``.

    """
    payload: dict[str, Any] = {"task_id": task_id, "status": status}
    payload.update(fields)
    return json.dumps(payload)


async def _execute_trigger_background(
    task_id: str,
    target_source_ids: list[str] | None,
    source_id_field: str | None,
    source_ids_field: list[str] | None,
    max_items: int | None,
    force: bool,
    cache: CachePool,
    scheduler: SourceScheduler,
    queued_at: str,
) -> None:
    """Background coroutine that actually triggers crawls.

    Designed to run via ``asyncio.create_task`` so the HTTP request returns
    immediately. All exceptions are caught and logged — the process MUST NOT
    crash regardless of scheduler / cache / database failures.

    Uses ``cache.hset`` directly (rather than ``_update_task_status``) so the
    status payload is self-contained and does not require a preceding ``hget``
    round-trip — this keeps the background task resilient even if the cache
    entry was evicted between queue time and run time.

    Source triggers are executed **sequentially** rather than via
    ``asyncio.gather``: each ``scheduler.trigger_now`` call performs
    ``bulk_insert_raw`` which holds a write lock on DuckDB. Concurrent
    triggers would contend on the same lock and rely on exponential backoff
    retries, which is slower than serializing (HIGH-1: DuckDB concurrent
    write conflict). Per-source timeout still applies so one slow source
    cannot block the entire batch.

    Args:
        task_id: UUID task identifier (string form).
        target_source_ids: Explicit list of source IDs to trigger, or ``None``
            to trigger all enabled sources (backward-compatible behaviour).
        source_id_field: Original ``source_id`` from request (for status
            payload; ``None`` if not provided).
        source_ids_field: Original ``source_ids`` list from request (for
            status payload; ``None`` if not provided). Passed in explicitly
            to avoid recomputing from the request inside the background
            task (LOW-1: avoid dual data paths).
        max_items: Per-source item limit (``None`` for unlimited).
        force: Force re-crawl even for recently fetched URLs.
        cache: Cache client for task status updates.
        scheduler: Source scheduler for triggering crawls.
        queued_at: ISO timestamp captured at queue time.

    """
    started_at = datetime.now(UTC).isoformat()
    try:
        # Update status to RUNNING
        await cache.hset(
            TASK_STATUS_KEY,
            task_id,
            _build_trigger_status_payload(
                task_id=task_id,
                status=PipelineTaskStatus.RUNNING.value,
                source_id=source_id_field,
                source_ids=source_ids_field,
                queued_at=queued_at,
                started_at=started_at,
            ),
        )

        if target_source_ids is None:
            # Trigger all enabled sources (backward compat)
            sources = scheduler.list_enabled_sources()
            ids_to_trigger: list[str] = [source.id for source in sources]
        else:
            ids_to_trigger = list(target_source_ids)

        if not ids_to_trigger:
            # No sources to trigger — complete with a clear status
            await cache.hset(
                TASK_STATUS_KEY,
                task_id,
                _build_trigger_status_payload(
                    task_id=task_id,
                    status=PipelineTaskStatus.COMPLETED.value,
                    queued_at=queued_at,
                    started_at=started_at,
                    completed_at=datetime.now(UTC).isoformat(),
                    note="no_sources_to_trigger",
                ),
            )
            return

        task_uuid = uuid.UUID(task_id)
        # Sequential execution: see HIGH-1 docstring note above. Each
        # ``trigger_now`` performs bulk_insert_raw (DuckDB write lock);
        # concurrent writes contend and trigger backoff retries that are
        # slower than serializing. Per-source timeout still applies.
        #
        # ``return_exceptions=True`` semantics from the previous gather
        # are preserved: one failing source does NOT abort the batch —
        # the exception is recorded and the next source is attempted.
        results: list[BaseException | None] = []
        for sid in ids_to_trigger:
            try:
                await asyncio.wait_for(
                    scheduler.trigger_now(
                        sid,
                        max_items=max_items,
                        task_id=task_uuid,
                        force=force,
                    ),
                    timeout=_TRIGGER_SOURCE_TIMEOUT_SECONDS,
                )
                results.append(None)
            except asyncio.CancelledError as exc:
                # CancelledError inherits BaseException (not Exception), so
                # the ``failures`` filter below would miss it. Track
                # separately for accurate shutdown statistics (LOW-2).
                # Stop further triggering — cancellation typically indicates
                # shutdown or explicit task cancellation.
                results.append(exc)
                break
            except Exception as exc:
                # Record and continue so one failing source doesn't abort
                # the entire batch.
                results.append(exc)

        # CancelledError is BaseException, not Exception, so the ``failures``
        # filter naturally excludes it. Keep them in a separate ``cancelled``
        # list so shutdown statistics are accurate (LOW-2).
        failures = [r for r in results if isinstance(r, Exception)]
        cancelled = [r for r in results if isinstance(r, asyncio.CancelledError)]
        for idx, result in enumerate(results):
            if isinstance(result, asyncio.CancelledError):
                cancelled_sid = ids_to_trigger[idx] if idx < len(ids_to_trigger) else "<unknown>"
                log.warning(
                    "pipeline_trigger_source_cancelled",
                    task_id=task_id,
                    source_id=cancelled_sid,
                )
            elif isinstance(result, Exception):
                failing_sid = ids_to_trigger[idx] if idx < len(ids_to_trigger) else "<unknown>"
                log.warning(
                    "pipeline_trigger_source_failed",
                    task_id=task_id,
                    source_id=failing_sid,
                    error=str(result),
                    error_type=type(result).__name__,
                )

        completed_at = datetime.now(UTC).isoformat()
        if failures or cancelled:
            error_parts: list[str] = []
            if failures:
                error_parts.append(
                    f"{len(failures)}/{len(ids_to_trigger)} source(s) failed; "
                    f"first error: {failures[0]!s}"
                )
            if cancelled:
                error_parts.append(f"{len(cancelled)}/{len(ids_to_trigger)} source(s) cancelled")
            error_summary = "; ".join(error_parts)
            await cache.hset(
                TASK_STATUS_KEY,
                task_id,
                _build_trigger_status_payload(
                    task_id=task_id,
                    status=PipelineTaskStatus.FAILED.value,
                    source_id=source_id_field,
                    source_ids=source_ids_field,
                    queued_at=queued_at,
                    started_at=started_at,
                    completed_at=completed_at,
                    error=error_summary,
                ),
            )
            log.warning(
                "pipeline_trigger_partial_failure",
                task_id=task_id,
                failure_count=len(failures),
                cancelled_count=len(cancelled),
                total_count=len(ids_to_trigger),
            )
        else:
            await cache.hset(
                TASK_STATUS_KEY,
                task_id,
                _build_trigger_status_payload(
                    task_id=task_id,
                    status=PipelineTaskStatus.COMPLETED.value,
                    source_id=source_id_field,
                    source_ids=source_ids_field,
                    queued_at=queued_at,
                    started_at=started_at,
                    completed_at=completed_at,
                    triggered_count=len(ids_to_trigger),
                ),
            )
    except Exception as exc:
        # Last-resort safety net: never let the background task propagate an
        # exception out of asyncio.create_task (which would log "Task exception
        # was never retrieved" and, in some configurations, tear down the loop).
        log.error(
            "pipeline_trigger_background_failed",
            task_id=task_id,
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        try:
            await cache.hset(
                TASK_STATUS_KEY,
                task_id,
                _build_trigger_status_payload(
                    task_id=task_id,
                    status=PipelineTaskStatus.FAILED.value,
                    source_id=source_id_field,
                    source_ids=source_ids_field,
                    queued_at=queued_at,
                    completed_at=datetime.now(UTC).isoformat(),
                    error=f"Background task error: {exc!s}",
                ),
            )
        except Exception:
            log.error(
                "pipeline_trigger_status_update_failed",
                task_id=task_id,
                exc_info=True,
            )


# ── Endpoints ───────────────────────────────────────────────────


@router.post("/trigger", response_model=APIResponse[TriggerResponse])
async def trigger_pipeline(
    request: TriggerRequest,
    _: str = Depends(verify_api_key),
    cache: CachePool = Depends(get_cache_client),
    scheduler: SourceScheduler = Depends(get_source_scheduler),
) -> APIResponse[TriggerResponse]:
    """Trigger a pipeline run to crawl news sources.

    Args:
        request: Pipeline trigger configuration. Supports both ``source_id``
            (singular, legacy) and ``source_ids`` (plural, takes precedence).
            An empty ``source_ids`` list returns 400 Bad Request.
        _: Verified API key.
        cache: Cache client for task queue.
        scheduler: Source scheduler for triggering crawls.

    Returns:
        Task ID and initial QUEUED status. The actual crawl runs in the
        background — poll ``GET /pipeline/tasks/{task_id}`` for progress.

    Raises:
        HTTPException: 400 if ``source_ids`` is an empty list; 404 if the
            requested source(s) do not exist; 500 on database / scheduler
            lookup failure.

    """
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # ── Synchronous input validation (fail fast before queueing) ──
    # Determine the target source IDs to trigger.
    # ``target_source_ids`` semantics:
    #   - None  → trigger all enabled sources (backward-compatible default)
    #   - list  → trigger exactly these source IDs (after validation)
    target_source_ids: list[str] | None = None

    # source_ids (plural) takes precedence over source_id (singular) when
    # explicitly provided as a list. The isinstance check keeps this robust
    # against MagicMock-style test doubles that don't go through pydantic.
    source_ids_provided = isinstance(request.source_ids, list)
    if source_ids_provided:
        if len(request.source_ids) == 0:
            # CRITICAL: empty source_ids MUST return 400, never silently
            # fall through to "trigger all" — that previously crashed the
            # server by concurrently crawling 18 sources.
            raise HTTPException(
                status_code=400,
                detail="source_ids cannot be empty",
            )
        try:
            all_source_ids = _collect_all_source_ids(scheduler)
        except HTTPException:
            raise
        except Exception as exc:
            log.error(
                "pipeline_trigger_source_lookup_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline trigger failed during source lookup: {exc!s}",
            ) from exc

        # Validate each requested source_id; collect missing for diagnostics.
        # Use dict.fromkeys for order-preserving deduplication.
        seen: dict[str, None] = {}
        missing: list[str] = []
        for sid in request.source_ids:
            if sid in seen:
                continue
            seen[sid] = None
            if sid in all_source_ids:
                target_source_ids = (target_source_ids or []) + [sid]
            else:
                missing.append(sid)
                log.warning(
                    "source_id_not_found_skipping",
                    source_id=_safe_echo(sid),
                    task_id=task_id,
                )

        if not target_source_ids:
            raise HTTPException(
                status_code=404,
                detail=(
                    "None of the provided source_ids exist"
                    + (f": missing={missing}" if missing else "")
                ),
            )
    elif request.source_id:
        # Backward-compatible single source_id path
        try:
            all_source_ids = _collect_all_source_ids(scheduler)
        except HTTPException:
            raise
        except Exception as exc:
            log.error(
                "pipeline_trigger_source_lookup_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline trigger failed during source lookup: {exc!s}",
            ) from exc

        if request.source_id not in all_source_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Source '{_safe_echo(request.source_id)}' not found",
            )
        target_source_ids = [request.source_id]
    else:
        # Neither source_id nor source_ids provided → trigger all enabled
        # sources (preserves the original "crawl everything" behaviour).
        target_source_ids = None

    # ── Queue the task (initial status = QUEUED) ──
    # ``source_ids_field`` is computed once and threaded through to the
    # background task to avoid recomputing it from ``request`` later
    # (LOW-1: avoid dual data paths between ``target_source_ids`` and
    # ``request.source_ids``).
    source_ids_field: list[str] | None = request.source_ids if source_ids_provided else None
    await cache.hset(
        TASK_STATUS_KEY,
        task_id,
        _build_trigger_status_payload(
            task_id=task_id,
            status=PipelineTaskStatus.QUEUED.value,
            source_id=request.source_id,
            source_ids=source_ids_field,
            queued_at=now,
        ),
    )

    # ── Launch background processing (fire-and-forget) ──
    # The HTTP request returns immediately with the task_id. The actual crawl
    # happens in the background; all exceptions are caught in
    # ``_execute_trigger_background`` so the server process cannot crash.
    #
    # The task is added to ``_background_tasks`` so the event loop does not
    # garbage-collect it before completion (MEDIUM-1: asyncio.create_task GC
    # risk). ``add_done_callback`` removes the entry automatically when the
    # task finishes, so the set does not grow unboundedly.
    background_task = asyncio.create_task(
        _execute_trigger_background(
            task_id=task_id,
            target_source_ids=target_source_ids,
            source_id_field=request.source_id,
            source_ids_field=source_ids_field,
            max_items=request.max_items,
            force=request.force,
            cache=cache,
            scheduler=scheduler,
            queued_at=now,
        )
    )
    _background_tasks.add(background_task)
    background_task.add_done_callback(_background_tasks.discard)

    return success_response(TriggerResponse(task_id=task_id, queued_at=now))


@router.get("/tasks/{task_id}", response_model=APIResponse[TaskStatusResponse])
async def get_task_status(
    task_id: str,
    _: str = Depends(verify_api_key),
    cache: CachePool = Depends(get_cache_client),
    relational_pool: RelationalPool = Depends(get_relational_pool),
) -> APIResponse[TaskStatusResponse]:
    """Query the status of a pipeline task.

    Args:
        task_id: The task ID to query.
        _: Verified API key.
        cache: Cache client for task status.
        relational_pool: Relational database pool for article stats.

    Returns:
        Task status information.

    Raises:
        HTTPException: If task not found.

    """
    status_data = await cache.hget(TASK_STATUS_KEY, task_id)

    if status_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{_safe_echo(task_id)}' not found",
        )

    data = json_repair.loads(status_data)

    # Get article progress statistics for this task
    article_repo = ArticleRepo(relational_pool)
    try:
        task_uuid = uuid.UUID(task_id)
        stats = await article_repo.get_task_progress_stats(task_uuid)
    except Exception:
        # If stats retrieval fails, use defaults
        log.warning("task_progress_stats_query_failed", exc_info=True)
        stats = {
            "total_processed": 0,
            "processing_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "pending_count": 0,
        }

    return success_response(
        TaskStatusResponse(
            task_id=data.get("task_id", task_id),
            status=data.get("status", "unknown"),
            source_id=data.get("source_id"),
            queued_at=data.get("queued_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            progress=data.get("progress"),
            total=data.get("total"),
            error=data.get("error"),
            total_processed=stats["total_processed"],
            processing_count=stats["processing_count"],
            completed_count=stats["completed_count"],
            failed_count=stats["failed_count"],
            pending_count=stats["pending_count"],
        )
    )


@router.get("/queue/stats", response_model=APIResponse[dict])
async def get_queue_stats(
    _: str = Depends(verify_api_key),
    cache: CachePool = Depends(get_cache_client),
    relational_pool: RelationalPool = Depends(get_relational_pool),
) -> APIResponse[dict]:
    """Get pipeline queue statistics.

    Args:
        _: Verified API key.
        cache: Cache client.
        relational_pool: Relational database pool for article stats.

    Returns:
        Queue statistics including article-level stats.

    """
    from sqlalchemy import case, func, select

    queue_depth = await cache.llen(TASK_QUEUE_KEY)

    # Count tasks by status
    all_tasks = await cache.hgetall(TASK_STATUS_KEY)
    status_counts: dict[str, int] = {}
    for task_data in all_tasks.values():
        try:
            data = json_repair.loads(task_data)
            status = data.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue

    # Get article-level statistics from relational database
    from core.db import Article, PersistStatus

    async with relational_pool.session() as session:
        result = await session.execute(
            select(
                func.count(Article.id).label("total_articles"),
                func.sum(
                    case((Article.persist_status == PersistStatus.PROCESSING, 1), else_=0)
                ).label("processing_count"),
                func.sum(
                    case(
                        (
                            Article.persist_status.in_(list(PersistStatus.completed_statuses())),
                            1,
                        ),
                        else_=0,
                    )
                ).label("completed_count"),
                func.sum(case((Article.persist_status == PersistStatus.FAILED, 1), else_=0)).label(
                    "failed_count"
                ),
                func.sum(case((Article.persist_status == PersistStatus.PENDING, 1), else_=0)).label(
                    "pending_count"
                ),
            )
        )
        row = result.one()

    return success_response(
        {
            "queue_depth": queue_depth,
            "status_counts": status_counts,
            "total_tasks": len(all_tasks),
            "article_stats": {
                "total_articles": row.total_articles or 0,
                "processing_count": int(row.processing_count or 0),
                "completed_count": int(row.completed_count or 0),
                "failed_count": int(row.failed_count or 0),
                "pending_count": int(row.pending_count or 0),
            },
        }
    )


@router.get("/status", response_model=APIResponse[dict])
async def pipeline_status(
    _: str = Depends(verify_api_key),
    relational_pool: RelationalPool = Depends(get_relational_pool),
) -> APIResponse[dict]:
    """Get overall pipeline status.

    Returns current pipeline state, queue stats, and recent activity.

    Args:
        _: Verified API key.
        relational_pool: Relational database pool for article stats.

    Returns:
        Pipeline status with queue stats and recent article count.

    """
    from sqlalchemy import case, func, select

    from core.db import Article, PersistStatus

    # Determine pipeline state from article-level processing counts
    async with relational_pool.session() as session:
        result = await session.execute(
            select(
                func.sum(
                    case((Article.persist_status == PersistStatus.PROCESSING, 1), else_=0)
                ).label("processing_count"),
                func.sum(case((Article.persist_status == PersistStatus.PENDING, 1), else_=0)).label(
                    "pending_count"
                ),
                func.count(Article.id).label("total_articles"),
            )
        )
        row = result.one()

    processing_count = int(row.processing_count or 0)
    pending_count = int(row.pending_count or 0)
    total_articles = int(row.total_articles or 0)

    # Pipeline is "running" when articles are actively being processed
    status = "running" if processing_count > 0 else "idle"

    return success_response(
        {
            "status": status,
            "queue": {
                "pending": pending_count,
                "processing": processing_count,
            },
            "recent_articles": total_articles,
        }
    )


# ── Single URL Processing ─────────────────────────────────────


async def _validate_url_for_processing(
    url: str,
    whitelist_mode: bool,
    settings: Settings,
) -> str:
    """Validate URL for SSRF and whitelist.

    Args:
        url: URL to validate.
        whitelist_mode: Whether to check whitelist.
        settings: Application settings.

    Returns:
        Validated URL.

    Raises:
        HTTPException: If URL is invalid or blocked.

    """
    # SSRF validation using basic URL parsing (no external dependencies needed)
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=403,
            detail="URL must use http or https protocol",
        )

    # Block internal/private IP ranges using ipaddress module for proper validation
    import ipaddress

    hostname = parsed.hostname or ""

    # First check simple string prefixes for obvious cases
    blocked_prefixes = ("localhost", "127.", "0.", "::1", "169.254.")
    if any(hostname.lower().startswith(prefix) for prefix in blocked_prefixes):
        raise HTTPException(
            status_code=403,
            detail=f"Access to internal host '{hostname}' is blocked",
        )

    # Try to parse as IP address and check if private/internal
    try:
        # Handle IPv6 brackets
        ip_str = hostname.replace("[", "").replace("]", "")
        ip_obj = ipaddress.ip_address(ip_str)

        # Block private, loopback, link-local, and reserved addresses
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
            raise HTTPException(
                status_code=403,
                detail=f"Access to internal IP '{hostname}' is blocked",
            )
    except ValueError:
        # Not an IP address, likely a domain name
        # Check for numeric prefixes that could be IP-like
        if hostname.replace(".", "").isdigit():
            # All digits with dots - looks like IP, validate
            try:
                ip_obj = ipaddress.ip_address(hostname)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Access to internal IP '{hostname}' is blocked",
                    )
            except ValueError:
                pass

    # Whitelist validation
    if whitelist_mode:
        allowed_domains = settings.pipeline_url_endpoint.allowed_domains
        hostname = parsed.hostname or ""

        if not allowed_domains:
            raise HTTPException(
                status_code=403,
                detail="Whitelist mode enabled but no allowed domains configured",
            )

        # Check if hostname matches any allowed domain (supports subdomains)
        is_allowed = any(
            hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains
        )

        if not is_allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Domain '{hostname}' is not in the allowed list",
            )

    return url


async def _update_task_status(
    cache: CachePool,
    task_id: str,
    status: str,
    **extra: str,
) -> None:
    """Update task status in cache.

    Args:
        cache: Cache client.
        task_id: Task ID.
        status: New status.
        **extra: Additional fields to store.

    """
    existing = await cache.hget(TASK_STATUS_KEY, task_id)
    data = json.loads(existing) if existing else {"task_id": task_id}
    data["status"] = status
    data.update(extra)
    await cache.hset(TASK_STATUS_KEY, task_id, json.dumps(data))


async def _process_single_url(
    url: str,
    task_id: str,
    cache: CachePool,
) -> None:
    """Background task to process a single URL through the pipeline.

    Args:
        url: URL to process.
        task_id: Task ID for tracking.
        cache: Cache client for status updates.

    """
    from container import get_container
    from modules.ingestion.domain.models import NewsItem
    from modules.ingestion.fetching.exceptions import FetchError

    container = get_container()
    crawler = container.crawler()
    pipeline = container.pipeline()

    try:
        # Update status to running
        await _update_task_status(
            cache,
            task_id,
            PipelineTaskStatus.RUNNING.value,
            started_at=datetime.now(UTC).isoformat(),
        )

        # Create NewsItem and crawl
        item = NewsItem(
            url=url,
            title="",
            source="url_endpoint",
            source_host=urlparse(url).netloc,
        )
        results = await crawler.crawl_batch([item])

        # Check for fetch error
        if results and isinstance(results[0], FetchError):
            raise results[0]

        if not results:
            raise RuntimeError("Crawler returned no results")

        article = results[0]

        # Run through pipeline
        states = await pipeline.process_batch(
            [article],
            task_id=uuid.UUID(task_id),
        )

        # Update status to completed
        state = states[0] if states else {}
        await _update_task_status(
            cache,
            task_id,
            PipelineTaskStatus.COMPLETED.value,
            completed_at=datetime.now(UTC).isoformat(),
            article_id=state.get("article_id", ""),
        )

    except Exception as exc:
        # Update status to failed
        await _update_task_status(
            cache,
            task_id,
            PipelineTaskStatus.FAILED.value,
            error=str(exc),
            completed_at=datetime.now(UTC).isoformat(),
        )


@router.post("/url", response_model=APIResponse[ProcessUrlResponse])
async def process_single_url(
    request: ProcessUrlRequest,
    _: str = Depends(verify_api_key),
    cache: CachePool = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> APIResponse[ProcessUrlResponse]:
    """Process a single URL through the full pipeline.

    Args:
        request: URL processing request.
        _: Verified API key.
        cache: Cache client for task status.
        settings: Application settings.

    Returns:
        Task ID and initial status.

    Raises:
        HTTPException: If URL is invalid or blocked.

    """
    # Validate URL
    await _validate_url_for_processing(
        request.url,
        request.whitelist_mode,
        settings,
    )

    # Create task
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Store initial task status
    await cache.hset(
        TASK_STATUS_KEY,
        task_id,
        json.dumps(
            {
                "task_id": task_id,
                "status": PipelineTaskStatus.QUEUED.value,
                "url": request.url,
                "queued_at": now,
            }
        ),
    )

    # Launch background processing
    _ = asyncio.create_task(_process_single_url(request.url, task_id, cache))  # noqa: RUF006

    return success_response(ProcessUrlResponse(task_id=task_id, queued_at=now))


# ── SSE Streaming ──────────────────────────────────────────────


def _sse_event(event: str, data: dict) -> str:
    """Format a single SSE event.

    Args:
        event: Event type name.
        data: Event payload.

    Returns:
        Formatted SSE string.

    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_url_processing(
    url: str,
    task_id: str,
    cache: CachePool,
) -> AsyncIterator[str]:
    """Async generator that yields SSE events for URL pipeline processing.

    Yields log, heartbeat, result, and error events while processing a URL.

    Args:
        url: URL to process.
        task_id: Task ID for tracking.
        cache: Cache client for status updates.

    """
    from container import get_container

    container = get_container()
    crawler = container.crawler()
    pipeline = container.pipeline()

    # Heartbeat task runs concurrently
    heartbeat_stop = asyncio.Event()

    async def _heartbeat() -> None:
        """Emit heartbeat events at 0.5s intervals until stopped."""
        while not heartbeat_stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(heartbeat_stop.wait(), timeout=0.5)
            if not heartbeat_stop.is_set():
                yield _sse_event(
                    "heartbeat", {"task_id": task_id, "ts": datetime.now(UTC).isoformat()}
                )

    try:
        # Update status to running
        await _update_task_status(
            cache,
            task_id,
            PipelineTaskStatus.RUNNING.value,
            started_at=datetime.now(UTC).isoformat(),
        )
        yield _sse_event(
            "log", {"task_id": task_id, "message": "Pipeline started", "status": "running"}
        )

        # Run heartbeat and processing concurrently
        heartbeat_gen = _heartbeat()
        processing_task = asyncio.ensure_future(_do_process(url, task_id, crawler, pipeline))

        # Alternate between heartbeat and processing
        heartbeat_iter = heartbeat_gen.__aiter__()
        while not processing_task.done():
            try:
                event = await asyncio.wait_for(heartbeat_iter.__anext__(), timeout=0.5)
                yield event
            except (StopAsyncIteration, TimeoutError):
                pass
            await asyncio.sleep(0)

        # Stop heartbeat
        heartbeat_stop.set()

        # Get result from processing
        result = processing_task.result()
        yield result

        # Update cache status
        if result_event := _parse_result_event(result):
            await _update_task_status(cache, task_id, **result_event)
        else:
            await _update_task_status(
                cache,
                task_id,
                PipelineTaskStatus.COMPLETED.value,
                completed_at=datetime.now(UTC).isoformat(),
            )

    except Exception as exc:
        heartbeat_stop.set()
        log.warning("sse_pipeline_error", task_id=task_id, error=str(exc))
        await _update_task_status(
            cache,
            task_id,
            PipelineTaskStatus.FAILED.value,
            error=str(exc),
            completed_at=datetime.now(UTC).isoformat(),
        )
        yield _sse_event("error", {"task_id": task_id, "error": str(exc)})


async def _do_process(
    url: str,
    task_id: str,
    crawler: object,
    pipeline: object,
) -> str:
    """Execute the pipeline processing and return the final SSE event string.

    Args:
        url: URL to process.
        task_id: Task ID for tracking.
        crawler: Crawler instance.
        pipeline: Pipeline instance.

    Returns:
        SSE event string (result or error).

    """
    from modules.ingestion.domain.models import NewsItem
    from modules.ingestion.fetching.exceptions import FetchError

    try:
        item = NewsItem(
            url=url,
            title="",
            source="url_endpoint",
            source_host=urlparse(url).netloc,
        )
        results = await crawler.crawl_batch([item])

        if results and isinstance(results[0], FetchError):
            raise results[0]

        if not results:
            raise RuntimeError("Crawler returned no results")

        article = results[0]

        states = await pipeline.process_batch(
            [article],
            task_id=uuid.UUID(task_id),
        )

        state = states[0] if states else {}
        return _sse_event(
            "result",
            {
                "task_id": task_id,
                "status": PipelineTaskStatus.COMPLETED.value,
                "article_id": state.get("article_id", ""),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )

    except Exception as exc:
        return _sse_event("error", {"task_id": task_id, "error": str(exc)})


def _parse_result_event(sse_str: str) -> dict | None:
    """Extract status fields from a result SSE event for cache update.

    Args:
        sse_str: Raw SSE event string.

    Returns:
        Dict with status fields, or None if not a result event.

    """
    try:
        for line in sse_str.strip().split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("status") and data.get("completed_at"):
                    return {
                        "status": data["status"],
                        "completed_at": data["completed_at"],
                        "article_id": data.get("article_id", ""),
                    }
    except (json.JSONDecodeError, KeyError):
        pass
    return None


@router.post("/url/stream")
async def process_url_stream(
    request: ProcessUrlRequest,
    _: str = Depends(verify_api_key),
    cache: CachePool = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Process a single URL through the pipeline with SSE streaming.

    Streams real-time progress events (log, heartbeat, result, error).
    Default concurrency limit: 3 simultaneous streams.

    Args:
        request: URL processing request.
        _: Verified API key.
        cache: Cache client for task status.
        settings: Application settings.

    Returns:
        StreamingResponse with SSE events.

    Raises:
        HTTPException: If URL is invalid, blocked, or concurrency limit reached.

    """
    # Validate URL
    await _validate_url_for_processing(
        request.url,
        request.whitelist_mode,
        settings,
    )

    # Check concurrency
    if _sse_semaphore.locked():
        raise HTTPException(
            status_code=429,
            detail="Too many concurrent stream requests. Please retry later.",
        )

    # Create task
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Store initial task status
    await cache.hset(
        TASK_STATUS_KEY,
        task_id,
        json.dumps(
            {
                "task_id": task_id,
                "status": PipelineTaskStatus.QUEUED.value,
                "url": request.url,
                "queued_at": now,
            }
        ),
    )

    async def _stream_with_semaphore() -> AsyncIterator[str]:
        """Wrap the stream generator with semaphore acquisition."""
        async with _sse_semaphore:
            async for event in _stream_url_processing(request.url, task_id, cache):
                yield event

    return StreamingResponse(
        _stream_with_semaphore(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
