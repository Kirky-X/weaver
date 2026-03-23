# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline API endpoints for triggering and monitoring crawl tasks."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import json_repair
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.cache.redis import RedisClient
from core.db.postgres import PostgresPool
from core.observability.metrics import metrics
from modules.source.scheduler import SourceScheduler
from modules.storage.article_repo import ArticleRepo

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
    status: str = "queued"
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


# ── Dependency for Redis Client ─────────────────────────────────

_redis_client: RedisClient | None = None
_postgres_pool: PostgresPool | None = None
_source_scheduler: SourceScheduler | None = None


def set_redis_client(client: RedisClient) -> None:
    """Set the global Redis client instance."""
    global _redis_client
    _redis_client = client


def get_redis_client() -> RedisClient:
    """Get the Redis client instance."""
    if _redis_client is None:
        raise HTTPException(
            status_code=503,
            detail="Redis client not initialized",
        )
    return _redis_client


def set_postgres_pool(pool: PostgresPool) -> None:
    """Set the global PostgresPool instance."""
    global _postgres_pool
    _postgres_pool = pool


def get_postgres_pool() -> PostgresPool:
    """Get the PostgresPool instance."""
    if _postgres_pool is None:
        raise HTTPException(
            status_code=503,
            detail="PostgresPool not initialized",
        )
    return _postgres_pool


def set_source_scheduler(scheduler: SourceScheduler) -> None:
    """Set the global source scheduler instance."""
    global _source_scheduler
    _source_scheduler = scheduler


def get_source_scheduler() -> SourceScheduler:
    """Get the source scheduler instance."""
    if _source_scheduler is None:
        raise HTTPException(
            status_code=503,
            detail="Source scheduler not initialized",
        )
    return _source_scheduler


# ── Constants ───────────────────────────────────────────────────

TASK_QUEUE_KEY = "pipeline:task_queue"
TASK_STATUS_KEY = "pipeline:task_status"
QUEUE_DEPTH_GAUGE = metrics.pipeline_queue_depth


# ── Endpoints ───────────────────────────────────────────────────


@router.post("/trigger", response_model=APIResponse[TriggerResponse])
async def trigger_pipeline(
    request: TriggerRequest,
    _: str = Depends(verify_api_key),
    redis: RedisClient = Depends(get_redis_client),
    scheduler: SourceScheduler = Depends(get_source_scheduler),
) -> APIResponse[TriggerResponse]:
    """Trigger a pipeline run to crawl news sources.

    Args:
        request: Pipeline trigger configuration.
        _: Verified API key.
        redis: Redis client for task queue.
        scheduler: Source scheduler for triggering crawls.

    Returns:
        Task ID and initial status.
    """
    print(f"[DEBUG] trigger_pipeline called, redis id={id(redis)}")
    task_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Update task status to running
    await redis.client.hset(
        TASK_STATUS_KEY,
        task_id,
        json.dumps(
            {
                "task_id": task_id,
                "status": "running",
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
        await redis.client.hset(
            TASK_STATUS_KEY,
            task_id,
            json.dumps(
                {
                    "task_id": task_id,
                    "status": "completed",
                    "source_id": request.source_id,
                    "queued_at": now,
                    "started_at": now,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            ),
        )

    except Exception as exc:
        # Update task status to failed
        await redis.client.hset(
            TASK_STATUS_KEY,
            task_id,
            json.dumps(
                {
                    "task_id": task_id,
                    "status": "failed",
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
    redis: RedisClient = Depends(get_redis_client),
    postgres_pool: PostgresPool = Depends(get_postgres_pool),
) -> APIResponse[TaskStatusResponse]:
    """Query the status of a pipeline task.

    Args:
        task_id: The task ID to query.
        _: Verified API key.
        redis: Redis client for task status.
        postgres_pool: PostgreSQL pool for article stats.

    Returns:
        Task status information.

    Raises:
        HTTPException: If task not found.
    """
    status_data = await redis.client.hget(TASK_STATUS_KEY, task_id)

    if status_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_id}' not found",
        )

    data = json_repair.loads(status_data)

    # Get article progress statistics for this task
    article_repo = ArticleRepo(postgres_pool)
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
    redis: RedisClient = Depends(get_redis_client),
    postgres_pool: PostgresPool = Depends(get_postgres_pool),
) -> APIResponse[dict]:
    """Get pipeline queue statistics.

    Args:
        _: Verified API key.
        redis: Redis client.
        postgres_pool: PostgreSQL pool for article stats.

    Returns:
        Queue statistics including article-level stats.
    """
    from sqlalchemy import case, func, select

    queue_depth = await redis.client.llen(TASK_QUEUE_KEY)

    # Count tasks by status
    all_tasks = await redis.client.hgetall(TASK_STATUS_KEY)
    status_counts: dict[str, int] = {}
    for task_data in all_tasks.values():
        try:
            data = json_repair.loads(task_data)
            status = data.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue

    # Get article-level statistics from PostgreSQL
    from core.db.models import Article, PersistStatus

    async with postgres_pool.session() as session:
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
