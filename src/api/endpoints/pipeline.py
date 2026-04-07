# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline API endpoints for triggering and monitoring crawl tasks."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import json_repair
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

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
from core.observability.metrics import metrics
from core.protocols import CachePool, RelationalPool
from core.security import URLValidationError, URLValidator
from modules.ingestion.scheduling.scheduler import SourceScheduler
from modules.storage import ArticleRepo

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


# ── Request/Response Models ─────────────────────────────────────


class TriggerRequest(BaseModel):
    """Request model for triggering a pipeline run."""

    source_id: str | None = Field(
        default=None,
        description="Specific source ID to crawl. If not provided, crawls all enabled sources.",
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
        request: Pipeline trigger configuration.
        _: Verified API key.
        cache: Cache client for task queue.
        scheduler: Source scheduler for triggering crawls.

    Returns:
        Task ID and initial status.

    """
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Update task status to running
    await cache.hset(
        TASK_STATUS_KEY,
        task_id,
        json.dumps(
            {
                "task_id": task_id,
                "status": PipelineTaskStatus.RUNNING.value,
                "source_id": request.source_id,
                "queued_at": now,
                "started_at": now,
            }
        ),
    )

    # Trigger the source scheduler to crawl
    try:
        if request.source_id:
            await scheduler.trigger_now(
                request.source_id, max_items=request.max_items, task_id=uuid.UUID(task_id)
            )
        else:
            sources = scheduler._registry.list_sources(enabled_only=True)
            tasks = [
                scheduler.trigger_now(
                    source.id, max_items=request.max_items, task_id=uuid.UUID(task_id)
                )
                for source in sources
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Update task status to completed
        await cache.hset(
            TASK_STATUS_KEY,
            task_id,
            json.dumps(
                {
                    "task_id": task_id,
                    "status": PipelineTaskStatus.COMPLETED.value,
                    "source_id": request.source_id,
                    "queued_at": now,
                    "started_at": now,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            ),
        )

    except Exception as exc:
        # Update task status to failed
        await cache.hset(
            TASK_STATUS_KEY,
            task_id,
            json.dumps(
                {
                    "task_id": task_id,
                    "status": PipelineTaskStatus.FAILED.value,
                    "source_id": request.source_id,
                    "queued_at": now,
                    "started_at": now,
                    "error": str(exc),
                }
            ),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline trigger failed: {exc!s}",
        )

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


# URL validator instance (reused across requests)
_url_validator: URLValidator | None = None


def _get_url_validator() -> URLValidator:
    """Get or create URL validator instance."""
    global _url_validator
    if _url_validator is None:
        _url_validator = URLValidator()
    return _url_validator


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
    validator = _get_url_validator()

    # SSRF validation
    try:
        await validator.validate(url)
    except URLValidationError as e:
        raise HTTPException(
            status_code=403,
            detail=f"SSRF risk: {e.message}",
        ) from e

    # Whitelist validation
    if whitelist_mode:
        allowed_domains = settings.pipeline_url_endpoint.allowed_domains
        parsed = urlparse(url)
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
