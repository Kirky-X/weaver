# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph quality metrics API endpoints — unified view-based API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_cache_client, get_graph_pool
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.observability import get_logger
from core.protocols import GraphPool
from modules.knowledge.graph import GraphQualityMetrics

log = get_logger(__name__)

router = APIRouter(prefix="/graph/metrics", tags=["graph-metrics"])

# Cache key and TTL for full metrics view
GRAPH_METRICS_FULL_CACHE_KEY = "cache:graph_metrics:full"
GRAPH_METRICS_CACHE_TTL = 300  # 5 minutes


# ── Response Models ─────────────────────────────────────────────


class HealthSummaryResponse(BaseModel):
    """Response model for graph health summary."""

    health_score: float = Field(..., ge=0, le=100, description="Overall health score (0-100)")
    status: str = Field(..., description="Health status: healthy, moderate, degraded, critical")
    entity_count: int = Field(..., ge=0, description="Total number of entities")
    relationship_count: int = Field(..., ge=0, description="Total number of relationships")
    orphan_ratio: float = Field(..., ge=0, le=1, description="Ratio of orphan entities")
    connectedness: float = Field(
        ..., ge=0, le=1, description="Ratio of entities in largest component"
    )
    average_degree: float = Field(..., ge=0, description="Average entity degree")
    recommendations: list[str] = Field(default_factory=list, description="Health recommendations")


class GraphMetricsResponse(BaseModel):
    """Response model for full graph metrics."""

    total_entities: int = Field(..., ge=0)
    total_articles: int = Field(..., ge=0)
    total_relationships: int = Field(..., ge=0)
    total_mentions: int = Field(..., ge=0)
    connected_components: int = Field(..., ge=0)
    largest_component_size: int = Field(..., ge=0)
    average_degree: float = Field(..., ge=0)
    modularity_score: float | None = Field(None, ge=-1, le=1)
    orphan_entities: int = Field(..., ge=0)
    high_degree_entities: list[dict[str, Any]] = Field(default_factory=list)
    entity_type_distribution: dict[str, int] = Field(default_factory=dict)
    relationship_type_distribution: dict[str, int] = Field(default_factory=dict)
    computed_at: str = Field(..., description="ISO timestamp of metrics computation")


# ── Unified Metrics Endpoint ────────────────────────────────────


@router.get("", response_model=APIResponse[Any])
async def get_graph_metrics(
    view: str = Query(
        "health",
        description="Metrics view: health (summary), full (complete), community (communities)",
    ),
    include: str | None = Query(
        None,
        description="Comma-separated list for full view: components,orphans,high_degree,modularity,distributions",
    ),
    _: str = Depends(verify_api_key),
    graph_pool: GraphPool = Depends(get_graph_pool),
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
        return await _get_health_view(graph_pool)
    elif view == "full":
        return await _get_full_view(graph_pool, include)
    elif view == "community":
        raise HTTPException(
            status_code=400,
            detail="Community view has been moved to GET /api/v1/admin/communities/health",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid view: {view}. Valid views: health, full",
        )


async def _get_health_view(graph_pool: GraphPool) -> APIResponse[HealthSummaryResponse]:
    """Get health summary view."""
    metrics = GraphQualityMetrics(graph_pool)
    summary = await metrics.get_health_summary()

    return success_response(
        HealthSummaryResponse(
            health_score=summary["health_score"],
            status=summary["status"],
            entity_count=summary["entity_count"],
            relationship_count=summary["relationship_count"],
            orphan_ratio=summary["orphan_ratio"],
            connectedness=summary["connectedness"],
            average_degree=summary["average_degree"],
            recommendations=summary["recommendations"],
        )
    )


async def _get_full_view(
    graph_pool: GraphPool, include: str | None
) -> APIResponse[GraphMetricsResponse]:
    """Get full metrics view with optional caching and include filtering."""
    # Parse include parameter
    include_set = _parse_include_param(include)

    # Try to get from cache if no specific include filter
    cache = get_cache_client()
    if cache and include_set is None:
        try:
            cached = await cache.get(GRAPH_METRICS_FULL_CACHE_KEY)
            if cached:
                import json

                cached_data = json.loads(cached)
                return success_response(GraphMetricsResponse(**cached_data))
        except Exception as exc:
            log.warning("cache_lookup_failed", error=str(exc))  # Fall through to compute

    # Compute metrics — pass include_set to skip expensive calculations
    metrics = GraphQualityMetrics(graph_pool)
    result = await metrics.calculate_all_metrics(include=include_set)

    # Build response
    response_data = GraphMetricsResponse(
        total_entities=result.total_entities,
        total_articles=result.total_articles,
        total_relationships=result.total_relationships,
        total_mentions=result.total_mentions,
        connected_components=result.connected_components,
        largest_component_size=result.largest_component_size,
        average_degree=result.average_degree,
        modularity_score=result.modularity_score,
        orphan_entities=result.orphan_entities,
        high_degree_entities=(
            result.high_degree_entities if _should_include("high_degree", include_set) else []
        ),
        entity_type_distribution=(
            result.entity_type_distribution if _should_include("distributions", include_set) else {}
        ),
        relationship_type_distribution=(
            result.relationship_type_distribution
            if _should_include("distributions", include_set)
            else {}
        ),
        computed_at=result.computed_at.isoformat(),
    )

    # Cache if no include filter and cache available
    if cache and include_set is None:
        try:
            import json

            await cache.set(
                GRAPH_METRICS_FULL_CACHE_KEY,
                json.dumps(response_data.model_dump()),
                ex=GRAPH_METRICS_CACHE_TTL,
            )
        except Exception as exc:
            log.warning("cache_write_failed", error=str(exc))  # Cache failure is not critical

    return success_response(response_data)


def _parse_include_param(include: str | None) -> set[str] | None:
    """Parse the include query parameter.

    Returns:
        - None if include is None or 'all' (include everything)
        - Set of specific includes otherwise

    """
    if include is None or include.lower() == "all":
        return None
    return {item.strip().lower() for item in include.split(",")}


def _should_include(item: str, include_set: set[str] | None) -> bool:
    """Check if an item should be included based on include_set.

    Args:
        item: The item to check
        include_set: Set of includes, or None for all

    Returns:
        True if item should be included

    """
    if include_set is None:
        return True
    return item.lower() in include_set
