# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Admin API endpoints for authority management and LLM failure/usage monitoring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_container, get_source_authority_repo
from api.endpoints._deps import Endpoints
from api.middleware.auth import verify_admin_api_key, verify_api_key
from api.schemas.response import APIResponse, success_response
from api.schemas.types import RoundedFloat, RoundedFloatOpt
from core.observability import get_logger
from modules.storage import SourceAuthorityRepo

if TYPE_CHECKING:
    from modules.analytics import LLMFailureRepo, LLMUsageRepo

log = get_logger(__name__)

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
    authority: RoundedFloat
    tier: int
    description: str | None
    needs_review: bool
    auto_score: RoundedFloatOpt
    updated_at: str


class UpdateAuthorityRequest(BaseModel):
    """Request model for updating authority."""

    authority: RoundedFloatOpt = Field(None, ge=0, le=1)
    tier: int | None = Field(None, ge=1, le=5)
    description: str | None = None


class UpdateAuthorityResponse(BaseModel):
    """Response for authority update."""

    host: str
    authority: RoundedFloatOpt
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
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
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
        description=request.description,
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


@router.get(
    "/llm-usage",
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
    _: str = Depends(verify_api_key),
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

    raise HTTPException(status_code=400, detail=f"Invalid group_by: {group_by}")


# ── Article Management ───────────────────────────────────────────


class DeduplicateResponse(BaseModel):
    """Response model for article deduplication."""

    removed: int
    kept: int


@router.post("/articles/deduplicate", response_model=APIResponse[DeduplicateResponse])
async def deduplicate_articles(
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
) -> APIResponse[DeduplicateResponse]:
    """Remove duplicate articles, keeping the most recent one per source_url.

    This is a cleanup operation for existing data that has duplicates
    due to DuckDB not enforcing unique constraints.

    Args:
        _: Verified API key.

    Returns:
        Deduplication statistics.

    """
    from modules.storage.postgres.article_repo import ArticleRepo

    pool = Endpoints.get_relational_pool_optional()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    repo = ArticleRepo(pool)
    result = await repo.deduplicate_articles()

    log.info("article_deduplication_complete", removed=result["removed"], kept=result["kept"])

    return success_response(
        DeduplicateResponse(
            removed=result["removed"],
            kept=result["kept"],
        )
    )


# ── Memory System Diagnostics ─────────────────────────────────────


class MemoryDiagnosticResponse(BaseModel):
    """Response model for memory system diagnostics."""

    memory_service_initialized: bool
    temporal_event_count: int
    causal_link_count: int
    pending_consolidation: int
    slow_path_enabled: bool
    scheduler_job_registered: bool


@router.get("/memory/diagnostics", response_model=APIResponse[MemoryDiagnosticResponse])
async def memory_diagnostics(
    _: str = Depends(verify_api_key),
    container: Any = Depends(get_container),
) -> APIResponse[MemoryDiagnosticResponse]:
    """Diagnostic endpoint for memory system health.

    Returns status of memory service initialization, event counts,
    and scheduler registration for troubleshooting.

    Args:
        _: Verified API key.
        container: Application container.

    Returns:
        Memory system diagnostic data.

    """
    ms = container.memory_service
    service_initialized = ms is not None

    temporal_count = 0
    causal_count = 0
    pending_count = 0
    slow_path_enabled = False
    scheduler_registered = False

    if service_initialized and ms is not None:
        try:
            temporal_count = await ms._temporal_repo.count_events()
            causal_count = await ms._causal_repo.count_causal_links()
            pending_count = await ms._consolidation_queue.length()
            slow_path_enabled = ms._config.slow_path_enabled
        except Exception as exc:
            log.warning("memory_diagnostic_query_failed", error=str(exc))

    try:
        scheduler = container._scheduler
        if scheduler is not None:
            jobs = scheduler.get_jobs()
            scheduler_registered = any(j.id == "memory_consolidation" for j in jobs)
    except Exception:
        pass

    return success_response(
        MemoryDiagnosticResponse(
            memory_service_initialized=service_initialized,
            temporal_event_count=temporal_count,
            causal_link_count=causal_count,
            pending_consolidation=pending_count,
            slow_path_enabled=slow_path_enabled,
            scheduler_job_registered=scheduler_registered,
        )
    )


class ConsolidationResult(BaseModel):
    """Response model for consolidation trigger."""

    processed: int
    event_ids: list[str]


@router.post(
    "/memory/trigger-consolidation",
    response_model=APIResponse[ConsolidationResult],
)
async def trigger_consolidation(
    batch_size: int = Query(10, ge=1, le=100),
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
    container: Any = Depends(get_container),
) -> APIResponse[ConsolidationResult]:
    """Manually trigger memory consolidation (slow path).

    Forces the slow path worker to process pending events for
    causal inference. Useful when scheduler has not run yet.

    Args:
        batch_size: Number of events to process (1-100).
        _: Verified API key.
        container: Application container.

    Returns:
        Consolidation results with processed event IDs.

    """
    ms = container.memory_service
    if ms is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")

    results = await ms.consolidate(batch_size=batch_size)

    return success_response(
        ConsolidationResult(
            processed=len(results),
            event_ids=[r.event_id for r in results if hasattr(r, "event_id")],
        )
    )


# ── Authority Auto Score Refresh ─────────────────────────────────


class AutoScoreRefreshResponse(BaseModel):
    """Response model for auto_score refresh."""

    sources_updated: int
    triggered_at: str


@router.post(
    "/authorities/refresh-auto-scores",
    response_model=APIResponse[AutoScoreRefreshResponse],
)
async def refresh_auto_scores(
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
    container: Any = Depends(get_container),
) -> APIResponse[AutoScoreRefreshResponse]:
    """Manually trigger source auto_score recalculation.

    Computes auto_score from historical article credibility scores
    for all sources. Updates needs_review=False for auto-scored sources.

    Args:
        _: Verified API key.
        container: Application container.

    Returns:
        Number of sources updated.

    """
    from sqlalchemy import func, select

    from core.db.models import Article

    pool = Endpoints.get_relational_pool_optional()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    repo = container.source_authority_repo()
    update_count = 0

    async with pool.session() as session:
        # Get all sources with articles
        stmt = select(Article.source_host).distinct()
        result = await session.execute(stmt)
        hosts = [row[0] for row in result if row[0]]

        if not hosts:
            return success_response(
                AutoScoreRefreshResponse(
                    sources_updated=0,
                    triggered_at=datetime.now(UTC).isoformat(),
                )
            )

        # Performance fix: Use single aggregate query instead of N+1 queries
        # Before: N queries (one per host)
        # After: 1 query with GROUP BY
        avg_stmt = (
            select(
                Article.source_host,
                func.avg(Article.credibility_score).label("avg_credibility"),
            )
            .where(
                Article.source_host.in_(hosts),
                Article.credibility_score.isnot(None),
            )
            .group_by(Article.source_host)
        )

        avg_result = await session.execute(avg_stmt)
        # Filter out NULL hosts to avoid issues with dirty data
        credibility_by_host = {row[0]: float(row[1]) for row in avg_result if row[0] is not None}

        # Update all sources in batch
        for host, avg_score in credibility_by_host.items():
            try:
                await repo.update_auto_score(host, avg_score)
                update_count += 1
            except Exception as exc:
                log.warning("auto_score_update_failed", host=host, error=str(exc))

    return success_response(
        AutoScoreRefreshResponse(
            sources_updated=update_count,
            triggered_at=datetime.now(UTC).isoformat(),
        )
    )


# ── Causal Inference ─────────────────────────────────


class CausalInferenceRequest(BaseModel):
    """Request model for causal inference."""

    entity_names: list[str] | None = Field(
        None, description="Optional filter for specific entities"
    )
    relation_types: list[str] | None = Field(
        None, description="Optional filter for relation types (e.g., INVESTS_IN, 合资)"
    )


class CausalInferenceResponse(BaseModel):
    """Response model for causal inference."""

    edges_created: int
    edges_filtered: int
    errors: int
    relations_analyzed: int


@router.post(
    "/causal/infer",
    response_model=APIResponse[CausalInferenceResponse],
    summary="Trigger causal edge inference",
)
async def trigger_causal_inference(
    request: CausalInferenceRequest | None = None,
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
    container: Any = Depends(get_container),
) -> APIResponse[CausalInferenceResponse]:
    """Trigger LLM-based causal inference from entity relationships.

    Analyzes existing entity relationships (INVESTS_IN, 合资, ACQUIRES, etc.)
    and infers causal edges (CAUSES, ENABLES, PREVENTS) using LLM semantic analysis.

    Args:
        request: Optional filter parameters for entity names or relation types.
        _: Verified admin API key.
        container: Application container.

    Returns:
        Statistics of the inference process.

    """
    # Initialize causal inference service
    service = await container.init_causal_inference_service()
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Causal inference service unavailable (missing graph pool or LLM client)",
        )

    # Run inference
    entity_names = request.entity_names if request else None
    relation_types = request.relation_types if request else None

    stats = await service.infer_and_create_causal_edges(
        entity_names=entity_names,
        relation_types=relation_types,
    )

    return success_response(
        CausalInferenceResponse(
            edges_created=stats.get("edges_created", 0),
            edges_filtered=stats.get("edges_filtered", 0),
            errors=stats.get("errors", 0),
            relations_analyzed=stats.get("relations_analyzed", 0),
        )
    )


@router.get(
    "/causal/stats",
    response_model=APIResponse[dict],
    summary="Get causal graph statistics",
)
async def get_causal_stats(
    _: str = Depends(verify_api_key),
    container: Any = Depends(get_container),
) -> APIResponse[dict]:
    """Get statistics about the causal graph.

    Returns count of causal edges (CAUSES, ENABLES, PREVENTS).

    Args:
        _: Verified API key.
        container: Application container.

    Returns:
        Causal graph statistics.

    """
    causal_repo = container.causal_repo()
    if causal_repo is None:
        raise HTTPException(
            status_code=503,
            detail="Causal graph repository unavailable",
        )

    count = await causal_repo.count_causal_links()

    return success_response(
        {
            "causal_edges": count,
            "edge_types": ["CAUSES", "ENABLES", "PREVENTS"],
        }
    )
