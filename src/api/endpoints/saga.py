# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Saga management API endpoints.

Provides endpoints for querying saga status, triggering manual compensation,
and listing failed sagas.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_saga_orchestrator
from core.observability import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/saga", tags=["saga"])


@router.get("/{saga_id}", summary="Get saga status")
async def get_saga_status(
    saga_id: uuid.UUID,
    orchestrator: Any = Depends(get_saga_orchestrator),
) -> dict[str, Any]:
    """Get the status of a saga by its ID.

    Args:
        saga_id: UUID of the saga.
        orchestrator: Saga orchestrator instance.

    Returns:
        Dict with saga status, step details, and error information.

    Raises:
        HTTPException: 404 if saga not found.

    """
    status = await orchestrator.get_saga_status(saga_id)

    if status.get("status") == "unknown":
        raise HTTPException(status_code=404, detail=f"Saga {saga_id} not found")

    return status


@router.post("/{saga_id}/compensate", summary="Trigger manual compensation")
async def compensate_saga(
    saga_id: uuid.UUID,
    orchestrator: Any = Depends(get_saga_orchestrator),
) -> dict[str, Any]:
    """Manually trigger compensation for a saga.

    Used for manual intervention when automatic compensation fails
    or when an operator needs to roll back a completed saga.

    Args:
        saga_id: UUID of the saga to compensate.
        orchestrator: Saga orchestrator instance.

    Returns:
        Dict with compensation result.

    Raises:
        HTTPException: 404 if saga not found, 500 if compensation fails.

    """
    # Check saga existence first (consistent with retry_saga endpoint)
    status_info = await orchestrator.get_saga_status(saga_id)
    if status_info.get("status") == "unknown":
        raise HTTPException(
            status_code=404,
            detail=f"Saga {saga_id} not found",
        )

    result = await orchestrator.compensate_saga(saga_id)

    if result.status.value == "failed":
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Compensation failed",
                "failed_steps": (
                    result.compensation_result.failed_steps if result.compensation_result else []
                ),
            },
        )

    return {
        "saga_id": str(result.saga_id),
        "status": result.status.value,
        "compensation_completed": (
            result.compensation_result.completed_steps if result.compensation_result else []
        ),
    }


@router.post("/{saga_id}/retry", summary="Retry a failed saga")
async def retry_saga(
    saga_id: uuid.UUID,
    orchestrator: Any = Depends(get_saga_orchestrator),
) -> dict[str, Any]:
    """Retry a failed saga by re-processing the associated article.

    Looks up the saga's article_id from logs and returns it so the caller
    can re-trigger pipeline processing. The actual step re-execution is
    handled by the pipeline service.

    Args:
        saga_id: UUID of the failed saga to retry.
        orchestrator: Saga orchestrator instance.

    Returns:
        Dict with article_id for re-processing.

    Raises:
        HTTPException: 404 if saga not found.

    """
    status = await orchestrator.get_saga_status(saga_id)

    if status.get("status") == "unknown":
        raise HTTPException(status_code=404, detail=f"Saga {saga_id} not found")

    # Extract article_id from the first log entry
    steps = status.get("steps", [])
    if not steps:
        raise HTTPException(status_code=404, detail=f"No log entries found for saga {saga_id}")

    # Get article_id from the saga logs
    logs = await orchestrator.get_saga_logs(saga_id)
    if not logs:
        raise HTTPException(status_code=404, detail=f"No logs found for saga {saga_id}")

    article_id = str(logs[0].article_id)

    log.info(
        "saga_retry_requested",
        saga_id=str(saga_id),
        article_id=article_id,
    )

    return {
        "saga_id": str(saga_id),
        "article_id": article_id,
        "previous_status": status.get("status"),
        "message": "Article identified for re-processing via pipeline",
    }


@router.get("/article/{article_id}", summary="Get sagas for article")
async def get_article_sagas(
    article_id: uuid.UUID,
    orchestrator: Any = Depends(get_saga_orchestrator),
) -> dict[str, Any]:
    """Get all saga log entries for an article.

    Args:
        article_id: UUID of the article.
        orchestrator: Saga orchestrator instance.

    Returns:
        Dict with list of saga log entries.

    """
    logs = await orchestrator.get_saga_logs_by_article(article_id)

    entries = []
    for entry in logs:
        entries.append(
            {
                "id": str(entry.id),
                "saga_id": str(entry.saga_id),
                "step_name": entry.step_name,
                "step_status": entry.step_status,
                "started_at": entry.started_at.isoformat() if entry.started_at else None,
                "completed_at": entry.completed_at.isoformat() if entry.completed_at else None,
                "error_message": entry.error_message,
                "retry_count": entry.retry_count,
            }
        )

    return {"article_id": str(article_id), "saga_logs": entries}


@router.get("/failed/list", summary="List failed sagas")
async def list_failed_sagas(
    limit: int = 50,
    orchestrator: Any = Depends(get_saga_orchestrator),
) -> dict[str, Any]:
    """List saga log entries with failed status.

    Args:
        limit: Maximum number of entries to return (default 50, max 200).
        orchestrator: Saga orchestrator instance.

    Returns:
        Dict with list of failed saga log entries.

    """
    limit = min(limit, 200)

    failed_logs = await orchestrator.get_failed_saga_logs(limit=limit)

    entries = []
    for entry in failed_logs:
        entries.append(
            {
                "id": str(entry.id),
                "saga_id": str(entry.saga_id),
                "article_id": str(entry.article_id),
                "step_name": entry.step_name,
                "step_status": entry.step_status,
                "error_message": entry.error_message,
                "retry_count": entry.retry_count,
            }
        )

    return {"failed_count": len(entries), "entries": entries}
