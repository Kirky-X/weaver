# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Graph quality monitoring endpoints — unified view-based API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_cache_client_optional, get_graph_pool, get_graph_pool_type
from api.endpoints._graph_metrics_shared import (
    get_full_metrics_view,
    get_health_summary_view,
)
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse
from api.schemas.types import RoundedFloat, RoundedFloatOpt
from core.observability import get_logger
from core.protocols import CachePool, GraphPool

log = get_logger(__name__)

router = APIRouter(prefix="/monitoring/graph", tags=["monitoring", "graph"])

# Relationship type mapping: English -> Chinese
RELATION_TYPE_ZH = {
    "WORKS_AT": "工作于",
    "PUBLISHES": "发布",
    "CONTROLS": "控制",
    "PARTICIPATES_IN": "参与",
    "SUPPORTS": "支持",
    "LOCATED_IN": "位于",
    "COMPETES_WITH": "竞争",
    "PARTNERS_WITH": "合作",
    "SUPPLIES": "供应",
    "AFFILIATED_WITH": "关联",
    "INFLUENCES": "影响",
}


# ── Response Models ─────────────────────────────────────────────


class HealthSummaryResponse(BaseModel):
    """Response model for graph health summary."""

    health_score: RoundedFloat = Field(
        ..., ge=0, le=100, description="Overall health score (0-100)"
    )
    status: str = Field(..., description="Health status: healthy, moderate, degraded, critical")
    entity_count: int = Field(..., ge=0, description="Total number of entities")
    relationship_count: int = Field(..., ge=0, description="Total number of relationships")
    orphan_ratio: RoundedFloat = Field(..., ge=0, le=1, description="Ratio of orphan entities")
    connectedness: RoundedFloat = Field(
        ..., ge=0, le=1, description="Ratio of entities in largest component"
    )
    average_degree: RoundedFloat = Field(..., ge=0, description="Average entity degree")
    recommendations: list[str] = Field(default_factory=list, description="Health recommendations")


class GraphMetricsResponse(BaseModel):
    """Response model for full graph metrics."""

    total_entities: int = Field(..., ge=0)
    total_articles: int = Field(..., ge=0)
    total_relationships: int = Field(..., ge=0)
    total_mentions: int = Field(..., ge=0)
    # Nullable when the caller excluded the item via ?include= — computation
    # was skipped, so a 0 would be misleading.
    connected_components: int | None = Field(None, ge=0)
    largest_component_size: int | None = Field(None, ge=0)
    average_degree: RoundedFloat = Field(..., ge=0)
    modularity_score: RoundedFloatOpt = Field(None, ge=-1, le=1)
    orphan_entities: int | None = Field(None, ge=0)
    high_degree_entities: list[dict[str, Any]] = Field(default_factory=list)
    entity_type_distribution: dict[str, int] = Field(default_factory=dict)
    relationship_type_distribution: dict[str, int] = Field(default_factory=dict)
    computed_at: str = Field(..., description="ISO timestamp of metrics computation")


# ── Unified Metrics Endpoint ────────────────────────────────────


@router.get("/metrics", response_model=APIResponse[Any])
async def get_graph_metrics(
    view: str = Query(
        "health",
        description="Metrics view: health (summary), full (complete), community (communities)",
    ),
    include: str | None = Query(
        None,
        description="Comma-separated list for full view: components,orphans,high_degree,modularity,distributions",
    ),
    _: str = Depends(verify_admin_api_key),
    graph_pool: GraphPool = Depends(get_graph_pool),
    pool_type: str = Depends(get_graph_pool_type),
    cache: CachePool | None = Depends(get_cache_client_optional),
) -> APIResponse[Any]:
    """Get graph metrics with view-based routing.

    **Views:**
    - `health` (default): Quick health summary with score and recommendations.
      Fast, suitable for dashboards and health checks.
    - `full`: Complete metrics including all subsets (components, orphans, etc.).
      Cached for 5 minutes due to expensive calculations.
    - `community`: Community-level metrics and health assessment.

    **Full view include parameter:**
    Control which expensive calculations to include:
    - `components`: Connected component analysis
    - `orphans`: Orphan entity detection
    - `high_degree`: High-degree entity identification
    - `modularity`: Modularity score calculation
    - `distributions`: Entity/relationship type distributions

    Omit `include` to get all metrics (same as `include=all`).
    """
    if view == "health":
        return await get_health_summary_view(graph_pool, HealthSummaryResponse, db_type=pool_type)
    elif view == "full":
        return await get_full_metrics_view(
            graph_pool,
            include,
            cache,
            GraphMetricsResponse,
            db_type=pool_type,
            rel_type_map=RELATION_TYPE_ZH,
        )
    elif view == "community":
        raise HTTPException(
            status_code=400,
            detail="Community view has been moved to GET /api/v1/monitoring/communities/health",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid view: {view}. Valid views: health, full",
        )
