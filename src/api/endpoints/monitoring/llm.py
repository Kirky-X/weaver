# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM monitoring endpoints for failure tracking and usage statistics."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.endpoints._deps import Endpoints
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response

if TYPE_CHECKING:
    from modules.analytics import LLMFailureRepo, LLMUsageRepo

router = APIRouter(prefix="/monitoring/llm", tags=["monitoring", "llm"])


def get_llm_failure_repo() -> LLMFailureRepo:
    """Get the LLM failure repo instance."""
    return Endpoints.get_llm_failure_repo()


def get_llm_usage_repo() -> LLMUsageRepo:
    """Get the LLM usage repo instance."""
    return Endpoints.get_llm_usage_repo()


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
    if group_by == "summary":
        summary = await repo.get_summary(
            start_time=from_,
            end_time=to,
            provider=provider,
            model=model,
            llm_type=llm_type,
            call_point=call_point,
        )
        return success_response(
            {
                "group_by": "summary",
                "total_calls": summary["total_calls"],
                "total_input_tokens": summary["total_input_tokens"],
                "total_output_tokens": summary["total_output_tokens"],
                "total_tokens": summary["total_tokens"],
                "avg_latency_ms": summary["avg_latency_ms"],
                "max_latency_ms": summary.get("max_latency_ms", 0.0),
                "min_latency_ms": summary.get("min_latency_ms", 0.0),
                "success_rate": summary["success_rate"],
                "error_types": summary.get("error_types", {}),
            }
        )

    elif group_by == "time":
        records = await repo.query_hourly(
            start_time=from_,
            end_time=to,
            granularity=granularity,
            provider=provider,
            model=model,
            llm_type=llm_type,
            call_point=call_point,
        )
        usage_records = [
            {
                "time_bucket": (
                    datetime.fromisoformat(r["time_bucket"])
                    if isinstance(r["time_bucket"], str)
                    else r["time_bucket"]
                ),
                "label": r.get("label", ""),
                "call_point": r.get("call_point", ""),
                "llm_type": r.get("llm_type", ""),
                "provider": r.get("provider", ""),
                "model": r.get("model", ""),
                "call_count": r["call_count"],
                "input_tokens": r.get("input_tokens_sum", 0),
                "output_tokens": r.get("output_tokens_sum", 0),
                "total_tokens": r.get("total_tokens_sum", 0),
                "latency_avg_ms": r["latency_avg_ms"],
                "success_count": r["success_count"],
                "failure_count": r["failure_count"],
            }
            for r in records
        ]
        return success_response(
            {"group_by": "time", "records": usage_records, "total": len(usage_records)}
        )

    elif group_by == "provider":
        records = await repo.get_by_provider(
            start_time=from_,
            end_time=to,
            llm_type=llm_type,
        )
        return success_response(
            {
                "group_by": "provider",
                "records": [
                    {
                        "provider": r["provider"],
                        "call_count": r["call_count"],
                        "input_tokens": r.get("input_tokens", 0),
                        "output_tokens": r.get("output_tokens", 0),
                        "total_tokens": r["total_tokens"],
                        "avg_latency_ms": r.get("avg_latency_ms", 0.0),
                        "success_rate": r.get("success_rate", 1.0),
                    }
                    for r in records
                ],
            }
        )

    elif group_by == "model":
        records = await repo.get_by_model(
            start_time=from_,
            end_time=to,
            provider=provider,
        )
        return success_response(
            {
                "group_by": "model",
                "records": [
                    {
                        "model": r["model"],
                        "provider": r["provider"],
                        "call_count": r["call_count"],
                        "input_tokens": r.get("input_tokens", 0),
                        "output_tokens": r.get("output_tokens", 0),
                        "total_tokens": r["total_tokens"],
                        "avg_latency_ms": r.get("avg_latency_ms", 0.0),
                        "success_rate": r.get("success_rate", 1.0),
                    }
                    for r in records
                ],
            }
        )

    elif group_by == "call_point":
        records = await repo.get_by_call_point(
            start_time=from_,
            end_time=to,
        )
        return success_response(
            {
                "group_by": "call_point",
                "records": [
                    {
                        "call_point": r["call_point"],
                        "call_count": r["call_count"],
                        "total_tokens": r["total_tokens"],
                        "avg_latency_ms": r.get("avg_latency_ms", 0.0),
                        "success_rate": r.get("success_rate", 1.0),
                    }
                    for r in records
                ],
            }
        )

    from fastapi import HTTPException

    raise HTTPException(status_code=400, detail=f"Invalid group_by: {group_by}")
