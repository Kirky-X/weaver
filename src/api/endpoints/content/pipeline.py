# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline API endpoints for triggering and monitoring crawl tasks."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import json_repair
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.dependencies import (
    get_cache_client,
    get_relational_pool,
)
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from config.settings import Settings
from container import get_settings
from core.constants import PipelineTaskStatus
from core.observability import metrics
from core.observability.logging import get_logger
from core.protocols import CachePool, RelationalPool
from modules.storage import ArticleRepo

log = get_logger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


# ── Request/Response Models ─────────────────────────────────────


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


# ── Endpoints ───────────────────────────────────────────────────


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
            detail=f"Task '{task_id}' not found",
        )

    data = json_repair.loads(status_data)

    # Get article progress statistics for this task
    article_repo = ArticleRepo(relational_pool)
    try:
        task_uuid = uuid.UUID(task_id)
        stats = await article_repo.get_task_progress_stats(task_uuid)
    except Exception:
        # If stats retrieval fails, use defaults
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
    from core.db.models import Article, PersistStatus

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
                            Article.persist_status.in_(
                                [PersistStatus.NEO4J_DONE, PersistStatus.PG_DONE]
                            ),
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
    def _on_task_done(task: asyncio.Task) -> None:
        """Handle background task completion."""
        if task.exception() is not None:
            log.error("background_task_failed", task_id=task_id, error=str(task.exception()))

    background_task = asyncio.create_task(_process_single_url(request.url, task_id, cache))
    background_task.add_done_callback(_on_task_done)

    return success_response(ProcessUrlResponse(task_id=task_id, queued_at=now))


# ── SSE Streaming API ──────────────────────────────────────────


# Semaphore for limiting concurrent SSE connections
_sse_semaphore = asyncio.Semaphore(3)


class SSEEvent(BaseModel):
    """Server-Sent Event data model."""

    type: str  # "log", "result", "error", "heartbeat"
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    level: str | None = None  # For log events: "debug", "info", "warning", "error"
    message: str | None = None
    data: dict | None = None  # For result events


async def emit_event(queue: asyncio.Queue, event: SSEEvent) -> None:
    """Emit an SSE event to the queue.

    Args:
        queue: Event queue.
        event: Event to emit.

    """
    await queue.put(event.model_dump(exclude_none=True))


async def heartbeat_task(queue: asyncio.Queue, stop_event: asyncio.Event) -> None:
    """Send heartbeat events every 0.5 seconds.

    Args:
        queue: Event queue.
        stop_event: Stop signal.

    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.5)
        except TimeoutError:
            await emit_event(queue, SSEEvent(type="heartbeat"))


async def sse_event_generator(
    request: ProcessUrlRequest,
    task_id: str,
    stop_event: asyncio.Event,
    event_queue: asyncio.Queue,
    cache: CachePool,
) -> None:
    """Generate SSE events from pipeline execution.

    Args:
        request: URL processing request.
        task_id: Task ID.
        stop_event: Stop signal.
        event_queue: Event queue.
        cache: Cache client.

    """
    from container import get_container
    from modules.ingestion.domain.models import NewsItem
    from modules.ingestion.fetching.exceptions import FetchError

    container = get_container()

    try:
        # Emit start event
        await emit_event(
            event_queue,
            SSEEvent(
                type="log",
                level="info",
                message=f"Starting pipeline for URL: {request.url}",
            ),
        )

        crawler = container.crawler()
        pipeline = container.pipeline()

        # Emit log: crawling
        await emit_event(
            event_queue,
            SSEEvent(type="log", level="info", message="Fetching URL content..."),
        )

        # Create NewsItem and crawl
        item = NewsItem(
            url=request.url,
            title="",
            source="url_endpoint_stream",
            source_host=urlparse(request.url).netloc,
        )
        results = await crawler.crawl_batch([item])

        # Check for fetch error
        if results and isinstance(results[0], FetchError):
            raise results[0]

        if not results:
            raise RuntimeError("Crawler returned no results")

        article = results[0]

        # Emit log: pipeline processing
        await emit_event(
            event_queue,
            SSEEvent(type="log", level="info", message="Running pipeline phases..."),
        )

        # Run through pipeline
        states = await pipeline.process_batch(
            [article],
            task_id=uuid.UUID(task_id),
        )

        state = states[0] if states else {}

        # Emit result event
        await emit_event(
            event_queue,
            SSEEvent(
                type="result",
                data={
                    "article_id": state.get("article_id", ""),
                    "title": state.get("cleaned", {}).get("title", ""),
                    "score": state.get("score", 0),
                    "url": request.url,
                },
            ),
        )

        # Emit completion log
        await emit_event(
            event_queue,
            SSEEvent(type="log", level="info", message="Pipeline completed successfully"),
        )

        # Update task status
        await _update_task_status(
            cache,
            task_id,
            PipelineTaskStatus.COMPLETED.value,
            completed_at=datetime.now(UTC).isoformat(),
            article_id=state.get("article_id", ""),
        )

    except Exception as exc:
        # Emit error event
        await emit_event(
            event_queue,
            SSEEvent(type="error", message=str(exc)),
        )

        # Update task status
        await _update_task_status(
            cache,
            task_id,
            PipelineTaskStatus.FAILED.value,
            error=str(exc),
            completed_at=datetime.now(UTC).isoformat(),
        )

    finally:
        stop_event.set()


async def sse_response_generator(
    fastapi_request: Request,
    event_queue: asyncio.Queue,
    stop_event: asyncio.Event,
    task_id: str,
) -> None:
    """Generate SSE response stream.

    Args:
        fastapi_request: FastAPI request for disconnect detection.
        event_queue: Event queue.
        stop_event: Stop signal.
        task_id: Task ID for X-Request-Id header.

    """

    async def event_stream():
        try:
            while not stop_event.is_set():
                # Check for client disconnect
                if await fastapi_request.is_disconnected():
                    log.info("sse_client_disconnected", task_id=task_id)
                    stop_event.set()
                    break

                try:
                    # Wait for event with timeout
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except TimeoutError:
                    # No event, continue loop (heartbeat handles keep-alive)
                    continue

        except asyncio.CancelledError:
            log.info("sse_stream_cancelled", task_id=task_id)
        finally:
            stop_event.set()

    return event_stream()


@router.post("/url/stream")
async def process_single_url_stream(
    request: ProcessUrlRequest,
    fastapi_request: Request,
    _: str = Depends(verify_api_key),
    cache: CachePool = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Process a single URL through the pipeline with SSE streaming.

    Returns real-time progress events via Server-Sent Events.

    Args:
        request: URL processing request.
        fastapi_request: FastAPI request for disconnect detection.
        _: Verified API key.
        cache: Cache client for task status.
        settings: Application settings.

    Returns:
        StreamingResponse with text/event-stream media type.

    Raises:
        HTTPException: If URL is invalid or blocked.

    """
    # Validate URL
    await _validate_url_for_processing(
        request.url,
        request.whitelist_mode,
        settings,
    )

    # Acquire semaphore (limit concurrent connections)
    async with _sse_semaphore:
        task_id = str(uuid.uuid4())

        # Store initial task status
        await cache.hset(
            TASK_STATUS_KEY,
            task_id,
            json.dumps(
                {
                    "task_id": task_id,
                    "status": PipelineTaskStatus.QUEUED.value,
                    "url": request.url,
                    "queued_at": datetime.now(UTC).isoformat(),
                }
            ),
        )

        # Create event queue and stop signal
        event_queue: asyncio.Queue = asyncio.Queue()
        stop_event = asyncio.Event()

        async def event_stream():
            """SSE event stream generator."""
            # Start heartbeat task
            heartbeat = asyncio.create_task(heartbeat_task(event_queue, stop_event))

            # Start pipeline processing task
            pipeline_task = asyncio.create_task(
                sse_event_generator(request, task_id, stop_event, event_queue, cache)
            )

            try:
                while not stop_event.is_set():
                    # Check for client disconnect
                    if await fastapi_request.is_disconnected():
                        log.info("sse_client_disconnected", task_id=task_id)
                        stop_event.set()
                        pipeline_task.cancel()
                        break

                    try:
                        # Wait for event with timeout
                        event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                        yield f"data: {json.dumps(event)}\n\n"
                    except TimeoutError:
                        # No event, continue loop
                        continue

            except asyncio.CancelledError:
                log.info("sse_stream_cancelled", task_id=task_id)
            finally:
                stop_event.set()
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Accel-Buffering": "no",
                "X-Request-Id": task_id,
                "Connection": "keep-alive",
            },
        )
