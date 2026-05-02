# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community health monitoring endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_graph_pool
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response
from api.schemas.types import RoundedFloat
from core.observability import get_logger
from core.protocols import GraphPool
from modules.knowledge.graph import CommunityHealthChecker

log = get_logger(__name__)

router = APIRouter(prefix="/monitoring/communities", tags=["monitoring", "communities"])


# ── Response Models ───────────────────────────────────────────


class HealthOverviewResponse(BaseModel):
    """Response model for community health overview."""

    status: str
    score: RoundedFloat
    total_communities: int
    communities_with_reports: int
    stale_reports: int
    empty_communities: int
    hierarchy_issues: int
    last_check_at: str | None


# ── Health Check Endpoints ───────────────────────────────────────


@router.get("/health", response_model=APIResponse[HealthOverviewResponse])
async def get_health_overview(
    _: str = Depends(verify_admin_api_key),
    pool: GraphPool = Depends(get_graph_pool),
) -> APIResponse[HealthOverviewResponse]:
    """Get community health overview.

    Returns a quick summary of community health status without full diagnosis.

    Args:
        _: Verified admin API key.
        pool: GraphPool connection pool.

    Returns:
        Health overview with status and key metrics.

    """
    checker = CommunityHealthChecker(pool)

    try:
        # Quick metrics check
        metrics = await checker._repo.get_overall_metrics()

        # Determine basic status from metrics
        total = metrics.get("total_communities", 0)
        empty = metrics.get("empty_community_count", 0)
        with_reports = metrics.get("communities_with_reports", 0)
        stale = metrics.get("stale_report_count", 0)

        if total == 0:
            status = "critical"
            score = 0.0
        else:
            empty_ratio = empty / total if total > 0 else 0
            report_ratio = with_reports / total if total > 0 else 0

            # Quick score calculation
            score = 100.0
            if empty_ratio > 0.10:
                score -= 30
            elif empty_ratio > 0.05:
                score -= 15
            if report_ratio < 0.7:
                score -= 10
            if stale > 0:
                score -= 5

            score = max(0.0, min(100.0, score))

            if score >= 80:
                status = "healthy"
            elif score >= 60:
                status = "moderate"
            elif score >= 40:
                status = "degraded"
            else:
                status = "critical"

        # Get hierarchy breaks count
        hierarchy_breaks = await checker._repo.find_hierarchy_breaks()

        return success_response(
            HealthOverviewResponse(
                status=status,
                score=score,
                total_communities=total,
                communities_with_reports=with_reports,
                stale_reports=stale,
                empty_communities=empty,
                hierarchy_issues=len(hierarchy_breaks),
                last_check_at=None,  # No persistent last check time yet
            )
        )

    except Exception as exc:
        log.error("get_health_overview_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Health check failed")
