# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph quality metrics API endpoints — unified view-based API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_neo4j_pool
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.cache import get_redis_client
from core.constants import GraphHealthStatus
from core.db.neo4j import Neo4jPool
from modules.knowledge.graph.metrics import GraphQualityMetrics

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


class CommunityMetricsResponse(BaseModel):
    """Response model for community-level metrics."""

    total_communities: int = Field(..., ge=0, description="Total number of communities")
    total_reports: int = Field(..., ge=0, description="Total number of reports")
    levels: int = Field(..., ge=0, description="Number of hierarchy levels")
    average_entity_count: float = Field(..., ge=0, description="Average entities per community")
    average_rank: float = Field(..., ge=0, description="Average community rank")
    modularity_score: float | None = Field(None, description="Overall modularity score")
    level_distribution: list[dict[str, Any]] = Field(
        default_factory=list, description="Community count per level"
    )
    top_communities: list[dict[str, Any]] = Field(
        default_factory=list, description="Top ranked communities"
    )
    health_score: float = Field(..., ge=0, le=100, description="Community structure health score")
    health_status: str = Field(..., description="Health status label")


class CommunityHealthResponse(BaseModel):
    """Response model for community health assessment."""

    score: float = Field(..., ge=0, le=100, description="Health score (0-100)")
    status: str = Field(..., description="Status: healthy, moderate, degraded, critical")
    issues: list[str] = Field(default_factory=list, description="Detected issues")
    recommendations: list[str] = Field(
        default_factory=list, description="Improvement recommendations"
    )
    modularity: float | None = Field(None, description="Modularity score")
    coverage: float = Field(..., ge=0, le=1, description="Entity coverage ratio")
    report_coverage: float = Field(..., ge=0, le=1, description="Report coverage ratio")


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
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
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

    **Migration from deprecated endpoints:**
    - `/graph/metrics/health` → `/graph/metrics?view=health`
    - `/graph/metrics/full` → `/graph/metrics?view=full`
    - `/graph/metrics/community` → `/graph/metrics?view=community`
    - `/graph/metrics/components` → `/graph/metrics?view=full&include=components`
    - `/graph/metrics/orphans` → `/graph/metrics?view=full&include=orphans`
    - `/graph/metrics/high-degree` → `/graph/metrics?view=full&include=high_degree`
    - `/graph/metrics/modularity` → `/graph/metrics?view=full&include=modularity`
    - `/graph/metrics/distributions` → `/graph/metrics?view=full&include=distributions`
    - `/graph/metrics/community/health` → `/graph/metrics?view=community`
    """
    if view == "health":
        return await _get_health_view(neo4j)
    elif view == "full":
        return await _get_full_view(neo4j, include)
    elif view == "community":
        return await _get_community_view(neo4j)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid view: {view}. Valid views: health, full, community",
        )


async def _get_health_view(neo4j: Neo4jPool) -> APIResponse[HealthSummaryResponse]:
    """Get health summary view."""
    metrics = GraphQualityMetrics(neo4j)
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
    neo4j: Neo4jPool, include: str | None
) -> APIResponse[GraphMetricsResponse]:
    """Get full metrics view with optional caching and include filtering."""
    # Parse include parameter
    include_set = _parse_include_param(include)

    # Try to get from cache if no specific include filter
    redis = get_redis_client()
    if redis and include_set is None:
        try:
            cached = await redis.get(GRAPH_METRICS_FULL_CACHE_KEY)
            if cached:
                import json

                cached_data = json.loads(cached)
                return success_response(GraphMetricsResponse(**cached_data))
        except Exception:
            pass  # Fall through to compute

    # Compute metrics — pass include_set to skip expensive calculations
    metrics = GraphQualityMetrics(neo4j)
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

    # Cache if no include filter and Redis available
    if redis and include_set is None:
        try:
            import json

            await redis.set(
                GRAPH_METRICS_FULL_CACHE_KEY,
                json.dumps(response_data.model_dump()),
                ex=GRAPH_METRICS_CACHE_TTL,
            )
        except Exception:
            pass  # Cache failure is not critical

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


async def _get_community_view(neo4j: Neo4jPool) -> APIResponse[CommunityMetricsResponse]:
    """Get community metrics view."""
    from modules.knowledge.graph.community_repo import Neo4jCommunityRepo

    repo = Neo4jCommunityRepo(neo4j)
    total_communities = await repo.count_communities()

    if total_communities == 0:
        return success_response(
            CommunityMetricsResponse(
                total_communities=0,
                total_reports=0,
                levels=0,
                average_entity_count=0.0,
                average_rank=0.0,
                modularity_score=None,
                level_distribution=[],
                top_communities=[],
                health_score=0.0,
                health_status="no_communities",
            )
        )

    metrics = await repo.get_community_metrics()
    level_distribution = await repo.get_level_distribution()
    top_communities = await repo.list_communities(limit=10)
    top_communities_data = [
        {
            "id": c.id,
            "title": c.title,
            "level": c.level,
            "entity_count": c.entity_count,
            "rank": c.rank,
        }
        for c in top_communities
    ]

    modularity = metrics.get("average_modularity", 0.0)
    report_count = metrics.get("report_count", 0)
    report_coverage = report_count / total_communities if total_communities > 0 else 0
    modularity_score = (modularity + 1) / 2 if modularity else 0.5
    health_score = modularity_score * 50 + report_coverage * 50

    if health_score >= 80:
        health_status = GraphHealthStatus.HEALTHY.value
    elif health_score >= 60:
        health_status = GraphHealthStatus.MODERATE.value
    elif health_score >= 40:
        health_status = GraphHealthStatus.DEGRADED.value
    else:
        health_status = GraphHealthStatus.CRITICAL.value

    # Get community health data
    issues: list[str] = []
    recommendations: list[str] = []

    if modularity < 0.0:
        issues.append("Low modularity score indicates poor community structure")
        recommendations.append("Consider adjusting cluster size parameters")

    if report_coverage < 0.5:
        issues.append(f"Only {report_coverage:.1%} of communities have reports")
        recommendations.append("Run POST /api/v1/admin/communities/reports/generate")

    return success_response(
        CommunityMetricsResponse(
            total_communities=total_communities,
            total_reports=report_count,
            levels=len(level_distribution),
            average_entity_count=metrics.get("average_entity_count", 0.0),
            average_rank=metrics.get("average_rank", 0.0),
            modularity_score=modularity,
            level_distribution=level_distribution,
            top_communities=top_communities_data,
            health_score=health_score,
            health_status=health_status,
        )
    )
