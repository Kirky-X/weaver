"""Graph quality metrics API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.middleware.auth import verify_api_key
from core.db.neo4j import Neo4jPool
from modules.graph_store.metrics import (
    GraphQualityMetrics,
    GraphMetrics,
    ConnectedComponent,
)

router = APIRouter(prefix="/graph/metrics", tags=["graph-metrics"])


_neo4j_pool: "Neo4jPool | None" = None


def set_neo4j_pool(pool: Neo4jPool) -> None:
    """Set the global Neo4j pool instance."""
    global _neo4j_pool
    _neo4j_pool = pool


def get_neo4j_pool() -> Neo4jPool:
    """Get the Neo4j pool instance."""
    if _neo4j_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Neo4j pool not initialized",
        )
    return _neo4j_pool


class HealthSummaryResponse(BaseModel):
    """Response model for graph health summary."""

    health_score: float = Field(..., ge=0, le=100, description="Overall health score (0-100)")
    status: str = Field(..., description="Health status: healthy, moderate, degraded, critical")
    entity_count: int = Field(..., ge=0, description="Total number of entities")
    relationship_count: int = Field(..., ge=0, description="Total number of relationships")
    orphan_ratio: float = Field(..., ge=0, le=1, description="Ratio of orphan entities")
    connectedness: float = Field(..., ge=0, le=1, description="Ratio of entities in largest component")
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


class ConnectedComponentResponse(BaseModel):
    """Response model for connected component."""

    component_id: int
    size: int
    node_ids: list[str]
    entity_types: dict[str, int]


class OrphanEntitiesResponse(BaseModel):
    """Response model for orphan entities."""

    count: int
    entities: list[dict[str, Any]]


class HighDegreeEntitiesResponse(BaseModel):
    """Response model for high-degree entities."""

    min_degree: int
    count: int
    entities: list[dict[str, Any]]


class ComponentsListResponse(BaseModel):
    """Response model for components list."""

    total_components: int
    largest_size: int
    smallest_size: int
    components: list[ConnectedComponentResponse]


@router.get("/health", response_model=HealthSummaryResponse)
async def get_graph_health(
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> HealthSummaryResponse:
    """Get a quick health summary of the knowledge graph.

    Returns:
        Health summary with score, status, and recommendations.
    """
    metrics = GraphQualityMetrics(neo4j)
    summary = await metrics.get_health_summary()

    return HealthSummaryResponse(
        health_score=summary["health_score"],
        status=summary["status"],
        entity_count=summary["entity_count"],
        relationship_count=summary["relationship_count"],
        orphan_ratio=summary["orphan_ratio"],
        connectedness=summary["connectedness"],
        average_degree=summary["average_degree"],
        recommendations=summary["recommendations"],
    )


@router.get("/full", response_model=GraphMetricsResponse)
async def get_full_metrics(
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> GraphMetricsResponse:
    """Get comprehensive graph quality metrics.

    Returns:
        Complete metrics snapshot including counts, distributions, and degree analysis.
    """
    metrics = GraphQualityMetrics(neo4j)
    result = await metrics.calculate_all_metrics()

    return GraphMetricsResponse(
        total_entities=result.total_entities,
        total_articles=result.total_articles,
        total_relationships=result.total_relationships,
        total_mentions=result.total_mentions,
        connected_components=result.connected_components,
        largest_component_size=result.largest_component_size,
        average_degree=result.average_degree,
        modularity_score=result.modularity_score,
        orphan_entities=result.orphan_entities,
        high_degree_entities=result.high_degree_entities,
        entity_type_distribution=result.entity_type_distribution,
        relationship_type_distribution=result.relationship_type_distribution,
        computed_at=result.computed_at.isoformat(),
    )


@router.get("/components", response_model=ComponentsListResponse)
async def get_connected_components(
    limit: int = Query(10, ge=1, le=100, description="Max components to return"),
    min_size: int = Query(1, ge=1, description="Minimum component size"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> ComponentsListResponse:
    """Get all connected components in the graph.

    Args:
        limit: Maximum number of components to return.
        min_size: Minimum component size to include.

    Returns:
        List of connected components sorted by size (descending).
    """
    metrics = GraphQualityMetrics(neo4j)
    components = await metrics.get_connected_components()

    filtered = [c for c in components if c.size >= min_size][:limit]

    component_responses = [
        ConnectedComponentResponse(
            component_id=c.component_id,
            size=c.size,
            node_ids=c.node_ids[:100],
            entity_types=c.entity_types,
        )
        for c in filtered
    ]

    sizes = [c.size for c in components] if components else [0]

    return ComponentsListResponse(
        total_components=len(components),
        largest_size=max(sizes) if sizes else 0,
        smallest_size=min(sizes) if sizes else 0,
        components=component_responses,
    )


@router.get("/components/largest", response_model=ConnectedComponentResponse)
async def get_largest_component(
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> ConnectedComponentResponse:
    """Get the largest connected component.

    Returns:
        The largest connected component with its nodes and type distribution.

    Raises:
        HTTPException: If no components exist.
    """
    metrics = GraphQualityMetrics(neo4j)
    component = await metrics.get_largest_connected_component()

    if component is None:
        raise HTTPException(
            status_code=404,
            detail="No connected components found in graph",
        )

    return ConnectedComponentResponse(
        component_id=component.component_id,
        size=component.size,
        node_ids=component.node_ids[:100],
        entity_types=component.entity_types,
    )


@router.get("/orphans", response_model=OrphanEntitiesResponse)
async def get_orphan_entities(
    limit: int = Query(100, ge=1, le=1000, description="Max entities to return"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> OrphanEntitiesResponse:
    """Find entities with no connections (orphans).

    Args:
        limit: Maximum number of orphan entities to return.

    Returns:
        List of orphan entities.
    """
    metrics = GraphQualityMetrics(neo4j)
    orphans = await metrics.find_orphan_entities(limit=limit)

    return OrphanEntitiesResponse(
        count=len(orphans),
        entities=orphans,
    )


@router.get("/high-degree", response_model=HighDegreeEntitiesResponse)
async def get_high_degree_entities(
    min_degree: int = Query(10, ge=1, le=1000, description="Minimum degree threshold"),
    limit: int = Query(50, ge=1, le=500, description="Max entities to return"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> HighDegreeEntitiesResponse:
    """Get entities with degree above threshold.

    Args:
        min_degree: Minimum degree threshold.
        limit: Maximum number of entities to return.

    Returns:
        List of high-degree entities sorted by degree (descending).
    """
    metrics = GraphQualityMetrics(neo4j)
    entities = await metrics.get_high_degree_entities(
        min_degree=min_degree,
        limit=limit,
    )

    return HighDegreeEntitiesResponse(
        min_degree=min_degree,
        count=len(entities),
        entities=entities,
    )


@router.get("/modularity")
async def get_modularity_score(
    resolution: float = Query(1.0, ge=0.1, le=10.0, description="Resolution parameter"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> dict[str, Any]:
    """Calculate graph modularity score.

    The modularity score measures the quality of graph partitioning.
    Higher values (closer to 1) indicate better community structure.

    Args:
        resolution: Resolution parameter for modularity calculation.

    Returns:
        Modularity score and interpretation.
    """
    metrics = GraphQualityMetrics(neo4j)
    score = await metrics.calculate_modularity(resolution=resolution)

    if score >= 0.7:
        interpretation = "excellent"
        description = "Strong community structure with well-defined clusters"
    elif score >= 0.4:
        interpretation = "good"
        description = "Moderate community structure with identifiable clusters"
    elif score >= 0.0:
        interpretation = "weak"
        description = "Weak community structure, graph may be too connected or sparse"
    else:
        interpretation = "poor"
        description = "Poor community structure, consider reviewing entity relationships"

    return {
        "modularity_score": score,
        "interpretation": interpretation,
        "description": description,
        "resolution": resolution,
    }


@router.get("/distributions")
async def get_type_distributions(
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> dict[str, Any]:
    """Get entity and relationship type distributions.

    Returns:
        Distribution of entity types and relationship types.
    """
    metrics = GraphQualityMetrics(neo4j)
    result = await metrics.calculate_all_metrics()

    return {
        "entity_types": result.entity_type_distribution,
        "relationship_types": result.relationship_type_distribution,
        "entity_type_count": len(result.entity_type_distribution),
        "relationship_type_count": len(result.relationship_type_distribution),
    }
