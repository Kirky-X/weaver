# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LLM monitoring endpoints for failure tracking and usage statistics."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.dependencies import get_llm_failure_repo, get_llm_usage_repo
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response

if TYPE_CHECKING:
    from modules.analytics import LLMFailureRepo, LLMUsageRepo

router = APIRouter(prefix="/monitoring/llm", tags=["monitoring", "llm"])


# ── Response Models ─────────────────────────────────────────────


class LLMFailureResponse(BaseModel):
    """Response model for LLM failure record."""

    id: int
    article_id: str | None
    task_id: str | None
    call_point: str
    provider: str
    error_type: str
    error_message: str | None
    status: str
    attempt: int
    fallback_tried: bool
    created_at: str


class LLMFailureStatsResponse(BaseModel):
    """Response model for LLM failure statistics."""

    total_failures: int
    by_call_point: dict[str, int]
    by_status: dict[str, int]
    last_failure_at: str | None = None


# ── LLM Failure Endpoints ───────────────────────────────────────


@router.get("/failures", response_model=APIResponse[list[LLMFailureResponse]])
async def list_llm_failures(
    call_point: str | None = Query(
        None, description="Filter by call point (e.g., classifier, analyzer)"
    ),
    status: str | None = Query(None, description="Filter by error type/status"),
    since: datetime | None = Query(None, description="ISO timestamp, only records after this time"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    _: str = Depends(verify_admin_api_key),
    repo: LLMFailureRepo = Depends(get_llm_failure_repo),
) -> APIResponse[list[LLMFailureResponse]]:
    """Get LLM failure records with optional filtering.

    Query LLM failure records for monitoring and debugging purposes.
    Supports filtering by call point, status, and time range.

    Args:
        call_point: Filter by call point (e.g., 'classifier', 'analyzer', 'entity_extractor').
        status: Filter by error type/status.
        since: ISO timestamp string, only return records after this time.
        limit: Maximum number of records to return (default 50, max 200).
        _: Verified admin API key.
        repo: LLM failure repository.

    Returns:
        List of LLM failure records ordered by creation time (newest first).

    """
    failures = await repo.query(
        call_point=call_point,
        status=status,
        since=since,
        limit=limit,
    )

    return success_response(
        [
            LLMFailureResponse(
                id=f.id,
                call_point=f.call_point,
                provider=f.provider,
                error_type=f.error_type,
                error_message=f.error_detail,
                status=f.error_type,
                article_id=str(f.article_id) if f.article_id else None,
                task_id=f.task_id,
                attempt=f.attempt,
                fallback_tried=f.fallback_tried,
                created_at=f.created_at.isoformat() if f.created_at else "",
            )
            for f in failures
        ]
    )


@router.get("/failures/stats", response_model=APIResponse[LLMFailureStatsResponse])
async def get_llm_failure_stats(
    since: datetime | None = Query(
        None, description="ISO timestamp, only count records after this time"
    ),
    _: str = Depends(verify_admin_api_key),
    repo: LLMFailureRepo = Depends(get_llm_failure_repo),
) -> APIResponse[LLMFailureStatsResponse]:
    """Get LLM failure statistics summary.

    Returns aggregate statistics of LLM failures grouped by call point and error type.

    Args:
        since: ISO timestamp string, only count records after this time.
        _: Verified admin API key.
        repo: LLM failure repository.

    Returns:
        Statistics summary including total count and breakdowns.

    """
    stats = await repo.get_stats(since=since)

    return success_response(
        LLMFailureStatsResponse(
            total_failures=stats["total"],
            by_call_point=stats["by_call_point"],
            by_status=stats["by_error_type"],
            last_failure_at=stats.get("last_failure_at"),
        )
    )


# ── LLM Usage Endpoints ─────────────────────────────────────────


@router.get(
    "/usage",
    response_model=APIResponse[dict],
    summary="Unified LLM usage statistics",
)
async def get_llm_usage_unified(
    from_: datetime = Query(..., alias="from", description="Start of time range (ISO format)"),
    to: datetime = Query(..., description="End of time range (ISO format)"),
    group_by: str = Query(
        "summary",
        pattern="^(summary|time|provider|model|call_point)$",
        description="Grouping dimension: summary, time, provider, model, or call_point",
    ),
    granularity: str = Query(
        "hourly",
        pattern="^(hourly|daily|monthly)$",
        description="Time granularity (only used when group_by=time)",
    ),
    provider: str | None = Query(None, description="Filter by provider name"),
    model: str | None = Query(None, description="Filter by model name"),
    llm_type: str | None = Query(None, description="Filter by LLM type (chat/embedding/rerank)"),
    call_point: str | None = Query(None, description="Filter by call point"),
    _: str = Depends(verify_admin_api_key),
    repo: LLMUsageRepo = Depends(get_llm_usage_repo),
) -> APIResponse[dict]:
    """Unified LLM usage statistics endpoint.

    Supports different grouping dimensions via the `group_by` parameter.
    """
    from api.endpoints._llm_usage_shared import query_llm_usage

    return await query_llm_usage(
        repo=repo,
        from_=from_,
        to=to,
        group_by=group_by,
        granularity=granularity,
        provider=provider,
        model=model,
        llm_type=llm_type,
        call_point=call_point,
    )
