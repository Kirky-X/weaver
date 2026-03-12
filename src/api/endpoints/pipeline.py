"""Pipeline API endpoints for triggering and monitoring crawl tasks."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import verify_api_key
from core.cache.redis import RedisClient
from core.observability.metrics import metrics
from modules.source.scheduler import SourceScheduler
from modules.collector.models import ArticleRaw

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


# ── Dependency for Redis Client ─────────────────────────────────

_redis_client: "RedisClient | None" = None
_source_scheduler: "SourceScheduler | None" = None


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


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_pipeline(
    request: TriggerRequest,
    _: str = Depends(verify_api_key),
    redis: RedisClient = Depends(get_redis_client),
    scheduler: SourceScheduler = Depends(get_source_scheduler),
) -> TriggerResponse:
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
    now = datetime.now(timezone.utc).isoformat()

    task_data = {
        "task_id": task_id,
        "source_id": request.source_id,
        "force": request.force,
        "queued_at": now,
        "status": "running",
    }

    # Update task status to running
    await redis.client.hset(
        TASK_STATUS_KEY,
        task_id,
        json.dumps({
            "task_id": task_id,
            "status": "running",
            "source_id": request.source_id,
            "queued_at": now,
            "started_at": now,
        }),
    )

    # Trigger the source scheduler to crawl
    try:
        if request.source_id:
            # Crawl specific source
            await scheduler.trigger_now(request.source_id)
        else:
            # Crawl all enabled sources
            for source in scheduler._registry.list_sources(enabled_only=True):
                await scheduler.trigger_now(source.id)

        # Update task status to completed
        await redis.client.hset(
            TASK_STATUS_KEY,
            task_id,
            json.dumps({
                "task_id": task_id,
                "status": "completed",
                "source_id": request.source_id,
                "queued_at": now,
                "started_at": now,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }),
        )

    except Exception as exc:
        # Update task status to failed
        await redis.client.hset(
            TASK_STATUS_KEY,
            task_id,
            json.dumps({
                "task_id": task_id,
                "status": "failed",
                "source_id": request.source_id,
                "queued_at": now,
                "started_at": now,
                "error": str(exc),
            }),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline trigger failed: {str(exc)}",
        )

    return TriggerResponse(task_id=task_id, queued_at=now)


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    _: str = Depends(verify_api_key),
    redis: RedisClient = Depends(get_redis_client),
) -> TaskStatusResponse:
    """Query the status of a pipeline task.

    Args:
        task_id: The task ID to query.
        _: Verified API key.
        redis: Redis client for task status.

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

    data = json.loads(status_data)
    return TaskStatusResponse(
        task_id=data.get("task_id", task_id),
        status=data.get("status", "unknown"),
        source_id=data.get("source_id"),
        queued_at=data.get("queued_at"),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        progress=data.get("progress"),
        total=data.get("total"),
        error=data.get("error"),
    )


@router.get("/queue/stats")
async def get_queue_stats(
    _: str = Depends(verify_api_key),
    redis: RedisClient = Depends(get_redis_client),
) -> dict[str, Any]:
    """Get pipeline queue statistics.

    Args:
        _: Verified API key.
        redis: Redis client.

    Returns:
        Queue statistics.
    """
    queue_depth = await redis.client.llen(TASK_QUEUE_KEY)

    # Count tasks by status
    all_tasks = await redis.client.hgetall(TASK_STATUS_KEY)
    status_counts: dict[str, int] = {}
    for task_data in all_tasks.values():
        try:
            data = json.loads(task_data)
            status = data.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        "queue_depth": queue_depth,
        "status_counts": status_counts,
        "total_tasks": len(all_tasks),
    }
