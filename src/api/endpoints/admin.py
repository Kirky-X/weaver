# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Admin API endpoints for authority management and LLM failure/usage monitoring."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_source_authority_repo
from api.endpoints._deps import Endpoints
from api.middleware.auth import verify_api_key
from api.schemas.llm_usage import (
    LLMUsageByCallPoint,
    LLMUsageByModel,
    LLMUsageByProvider,
    LLMUsageRecord,
    LLMUsageResponse,
    LLMUsageSummary,
)
from api.schemas.response import APIResponse, success_response
from core.observability.logging import get_logger
from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo

if TYPE_CHECKING:
    from modules.analytics.llm_failure.repo import LLMFailureRepo
    from modules.analytics.llm_usage.repo import LLMUsageRepo

log = get_logger("admin_api")

router = APIRouter(prefix="/admin", tags=["admin"])


def get_llm_failure_repo() -> LLMFailureRepo:
    """Get the LLM failure repo instance."""
    return Endpoints.get_llm_failure_repo()


def get_llm_usage_repo() -> LLMUsageRepo:
    """Get the LLM usage repo instance."""
    return Endpoints.get_llm_usage_repo()


# ── Request/Response Models ─────────────────────────────────────


class AuthorityResponse(BaseModel):
    """Response model for source authority."""

    id: int
    host: str
    authority: float
    tier: int
    description: str | None
    needs_review: bool
    auto_score: float | None
    updated_at: str


class UpdateAuthorityRequest(BaseModel):
    """Request model for updating authority."""

    authority: float | None = Field(None, ge=0, le=1)
    tier: int | None = Field(None, ge=1, le=5)
    description: str | None = None


class UpdateAuthorityResponse(BaseModel):
    """Response for authority update."""

    host: str
    authority: float | None
    tier: int | None
    description: str | None


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


# ── Authority Endpoints ─────────────────────────────────────────


@router.get("/authorities", response_model=APIResponse[list[AuthorityResponse]])
async def list_authorities(
    needs_review_only: bool = False,
    _: str = Depends(verify_api_key),
    repo: SourceAuthorityRepo = Depends(get_source_authority_repo),
) -> APIResponse[list[AuthorityResponse]]:
    """Get source authorities, optionally filtered by those needing review.

    **Migration:** `/admin/sources/authorities` → `/admin/authorities`

    Args:
        needs_review_only: If True, only return authorities that need review.
        _: Verified API key.
        repo: Source authority repository.

    Returns:
        List of source authorities.

    """
    if needs_review_only:
        authorities = await repo.get_needs_review()
    else:
        authorities = await repo.list_all()

    return success_response(
        [
            AuthorityResponse(
                id=a.id,
                host=a.host,
                authority=float(a.authority),
                tier=a.tier,
                description=a.description,
                needs_review=a.needs_review,
                auto_score=float(a.auto_score) if a.auto_score else None,
                updated_at=a.updated_at.isoformat(),
            )
            for a in authorities
        ]
    )


@router.patch("/authorities/{host}", response_model=APIResponse[UpdateAuthorityResponse])
async def update_authority(
    host: str,
    request: UpdateAuthorityRequest,
    _: str = Depends(verify_api_key),
    repo: SourceAuthorityRepo = Depends(get_source_authority_repo),
) -> APIResponse[UpdateAuthorityResponse]:
    """Update authority score for a source host.

    **Migration:** `PATCH /admin/sources/{host}/authority` → `PATCH /admin/authorities/{host}`

    Args:
        host: The source hostname.
        request: Authority update data.
        _: Verified API key.
        repo: Source authority repository.

    Returns:
        Updated authority information.

    Raises:
        HTTPException: If no updates provided.

    """
    if request.authority is None and request.tier is None and request.description is None:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be updated",
        )

    # Get current authority to preserve values
    authority = await repo.get_or_create(host)
    new_authority = (
        request.authority if request.authority is not None else float(authority.authority)
    )
    new_tier = request.tier if request.tier is not None else authority.tier

    # Update
    await repo.update_authority(
        host=host,
        authority=new_authority,
        tier=new_tier,
        needs_review=False,  # Mark as reviewed
    )

    log.info(
        "authority_updated",
        host=host,
        authority=new_authority,
        tier=new_tier,
    )

    return success_response(
        UpdateAuthorityResponse(
            host=host,
            authority=request.authority,
            tier=request.tier,
            description=request.description,
        )
    )


# ── LLM Failure Endpoints ───────────────────────────────────────


@router.get("/llm-failures", response_model=APIResponse[list[LLMFailureResponse]])
async def list_llm_failures(
    call_point: str | None = Query(
        None, description="Filter by call point (e.g., classifier, analyzer)"
    ),
    status: str | None = Query(None, description="Filter by error type/status"),
    since: datetime | None = Query(None, description="ISO timestamp, only records after this time"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    _: str = Depends(verify_api_key),
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
        _: Verified API key.
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


@router.get("/llm-failures/stats", response_model=APIResponse[LLMFailureStatsResponse])
async def get_llm_failure_stats(
    since: datetime | None = Query(
        None, description="ISO timestamp, only count records after this time"
    ),
    _: str = Depends(verify_api_key),
    repo: LLMFailureRepo = Depends(get_llm_failure_repo),
) -> APIResponse[LLMFailureStatsResponse]:
    """Get LLM failure statistics summary.

    Returns aggregate statistics of LLM failures grouped by call point and error type.

    Args:
        since: ISO timestamp string, only count records after this time.
        _: Verified API key.
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


@router.get("/llm-usage", response_model=APIResponse[LLMUsageResponse])
async def get_llm_usage(
    from_: datetime = Query(..., alias="from", description="Start of time range (ISO format)"),
    to: datetime = Query(..., description="End of time range (ISO format)"),
    granularity: str = Query(
        "hourly",
        pattern="^(hourly|daily|monthly)$",
        description="Time granularity: hourly, daily, or monthly",
    ),
    provider: str | None = Query(None, description="Filter by provider name"),
    model: str | None = Query(None, description="Filter by model name"),
    llm_type: str | None = Query(None, description="Filter by LLM type (chat/embedding/rerank)"),
    call_point: str | None = Query(None, description="Filter by call point"),
    _: str = Depends(verify_api_key),
    repo: LLMUsageRepo = Depends(get_llm_usage_repo),
) -> APIResponse[LLMUsageResponse]:
    """Get LLM usage statistics with time-based aggregation.

    Query aggregated LLM usage statistics for monitoring and analysis.
    Supports different time granularities and optional filters.

    Args:
        from_: Start of time range (ISO format).
        to: End of time range (ISO format).
        granularity: Time granularity - "hourly", "daily", or "monthly".
        provider: Optional filter by provider name.
        model: Optional filter by model name.
        llm_type: Optional filter by LLM type (chat/embedding/rerank).
        call_point: Optional filter by call point.
        _: Verified API key.
        repo: LLM usage repository.

    Returns:
        Aggregated LLM usage records with total count.

    """
    records = await repo.query_hourly(
        start_time=from_,
        end_time=to,
        granularity=granularity,
        provider=provider,
        model=model,
        llm_type=llm_type,
        call_point=call_point,
    )

    # Convert to response models
    usage_records = [
        LLMUsageRecord(
            time_bucket=(
                datetime.fromisoformat(r["time_bucket"])
                if isinstance(r["time_bucket"], str)
                else r["time_bucket"]
            ),
            label=r.get("label", ""),
            call_point=r.get("call_point", ""),
            llm_type=r.get("llm_type", ""),
            provider=r.get("provider", ""),
            model=r.get("model", ""),
            call_count=r["call_count"],
            input_tokens=r.get("input_tokens_sum", 0),
            output_tokens=r.get("output_tokens_sum", 0),
            total_tokens=r.get("total_tokens_sum", 0),
            latency_avg_ms=r["latency_avg_ms"],
            latency_min_ms=r.get("latency_min_ms", 0.0),
            latency_max_ms=r.get("latency_max_ms", 0.0),
            success_count=r["success_count"],
            failure_count=r["failure_count"],
        )
        for r in records
    ]

    return success_response(
        LLMUsageResponse(
            records=usage_records,
            total=len(usage_records),
        )
    )


@router.get("/llm-usage/summary", response_model=APIResponse[LLMUsageSummary])
async def get_llm_usage_summary(
    from_: datetime = Query(..., alias="from", description="Start of time range (ISO format)"),
    to: datetime = Query(..., description="End of time range (ISO format)"),
    provider: str | None = Query(None, description="Filter by provider name"),
    model: str | None = Query(None, description="Filter by model name"),
    llm_type: str | None = Query(None, description="Filter by LLM type (chat/embedding/rerank)"),
    call_point: str | None = Query(None, description="Filter by call point"),
    _: str = Depends(verify_api_key),
    repo: LLMUsageRepo = Depends(get_llm_usage_repo),
) -> APIResponse[LLMUsageSummary]:
    """Get summary statistics for LLM usage.

    Returns aggregate statistics including total calls, tokens, and success rate.

    Args:
        from_: Start of time range (ISO format).
        to: End of time range (ISO format).
        provider: Optional filter by provider name.
        model: Optional filter by model name.
        llm_type: Optional filter by LLM type (chat/embedding/rerank).
        call_point: Optional filter by call point.
        _: Verified API key.
        repo: LLM usage repository.

    Returns:
        Summary statistics for the specified time range and filters.

    """
    summary = await repo.get_summary(
        start_time=from_,
        end_time=to,
        provider=provider,
        model=model,
        llm_type=llm_type,
        call_point=call_point,
    )

    return success_response(
        LLMUsageSummary(
            total_calls=summary["total_calls"],
            total_input_tokens=summary["total_input_tokens"],
            total_output_tokens=summary["total_output_tokens"],
            total_tokens=summary["total_tokens"],
            avg_latency_ms=summary["avg_latency_ms"],
            max_latency_ms=summary.get("max_latency_ms", 0.0),
            min_latency_ms=summary.get("min_latency_ms", 0.0),
            success_rate=summary["success_rate"],
            error_types=summary.get("error_types", {}),
        )
    )


@router.get("/llm-usage/by-provider", response_model=APIResponse[list[LLMUsageByProvider]])
async def get_llm_usage_by_provider(
    from_: datetime = Query(..., alias="from", description="Start of time range (ISO format)"),
    to: datetime = Query(..., description="End of time range (ISO format)"),
    llm_type: str | None = Query(None, description="Filter by LLM type (chat/embedding/rerank)"),
    _: str = Depends(verify_api_key),
    repo: LLMUsageRepo = Depends(get_llm_usage_repo),
) -> APIResponse[list[LLMUsageByProvider]]:
    """Get LLM usage statistics grouped by provider.

    Returns aggregated usage statistics for each LLM provider.

    Args:
        from_: Start of time range (ISO format).
        to: End of time range (ISO format).
        llm_type: Optional filter by LLM type (chat/embedding/rerank).
        _: Verified API key.
        repo: LLM usage repository.

    Returns:
        List of provider-level usage statistics.

    """
    records = await repo.get_by_provider(
        start_time=from_,
        end_time=to,
        llm_type=llm_type,
    )

    return success_response(
        [
            LLMUsageByProvider(
                provider=r["provider"],
                call_count=r["call_count"],
                input_tokens=r.get("input_tokens", 0),
                output_tokens=r.get("output_tokens", 0),
                total_tokens=r["total_tokens"],
                avg_latency_ms=r.get("avg_latency_ms", 0.0),
                success_rate=r.get("success_rate", 1.0),
            )
            for r in records
        ]
    )


@router.get("/llm-usage/by-model", response_model=APIResponse[list[LLMUsageByModel]])
async def get_llm_usage_by_model(
    from_: datetime = Query(..., alias="from", description="Start of time range (ISO format)"),
    to: datetime = Query(..., description="End of time range (ISO format)"),
    provider: str | None = Query(None, description="Filter by provider name"),
    _: str = Depends(verify_api_key),
    repo: LLMUsageRepo = Depends(get_llm_usage_repo),
) -> APIResponse[list[LLMUsageByModel]]:
    """Get LLM usage statistics grouped by model.

    Returns aggregated usage statistics for each LLM model.

    Args:
        from_: Start of time range (ISO format).
        to: End of time range (ISO format).
        provider: Optional filter by provider name.
        _: Verified API key.
        repo: LLM usage repository.

    Returns:
        List of model-level usage statistics.

    """
    records = await repo.get_by_model(
        start_time=from_,
        end_time=to,
        provider=provider,
    )

    return success_response(
        [
            LLMUsageByModel(
                model=r["model"],
                provider=r["provider"],
                call_count=r["call_count"],
                input_tokens=r.get("input_tokens", 0),
                output_tokens=r.get("output_tokens", 0),
                total_tokens=r["total_tokens"],
                avg_latency_ms=r.get("avg_latency_ms", 0.0),
                success_rate=r.get("success_rate", 1.0),
            )
            for r in records
        ]
    )


@router.get("/llm-usage/by-call-point", response_model=APIResponse[list[LLMUsageByCallPoint]])
async def get_llm_usage_by_call_point(
    from_: datetime = Query(..., alias="from", description="Start of time range (ISO format)"),
    to: datetime = Query(..., description="End of time range (ISO format)"),
    _: str = Depends(verify_api_key),
    repo: LLMUsageRepo = Depends(get_llm_usage_repo),
) -> APIResponse[list[LLMUsageByCallPoint]]:
    """Get LLM usage statistics grouped by call point.

    Returns aggregated usage statistics for each call point
    (e.g., classifier, analyzer, entity_extractor).

    Args:
        from_: Start of time range (ISO format).
        to: End of time range (ISO format).
        _: Verified API key.
        repo: LLM usage repository.

    Returns:
        List of call point level usage statistics.

    """
    records = await repo.get_by_call_point(
        start_time=from_,
        end_time=to,
    )

    return success_response(
        [
            LLMUsageByCallPoint(
                call_point=r["call_point"],
                call_count=r["call_count"],
                total_tokens=r["total_tokens"],
                avg_latency_ms=r.get("avg_latency_ms", 0.0),
                success_rate=r.get("success_rate", 1.0),
            )
            for r in records
        ]
    )
