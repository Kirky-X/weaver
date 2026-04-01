# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph visualization API endpoints for knowledge graph exploration.

Provides API endpoints for:
- Graph topology visualization (snapshot)
- Interactive subgraph exploration
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_neo4j_pool
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.db.neo4j import Neo4jPool

router = APIRouter(prefix="/graph/visualization", tags=["graph-visualization"])


# Whitelist for hop patterns to prevent Cypher injection
_HOPS_PATTERNS = {
    1: "*1..1",
    2: "*1..2",
    3: "*1..3",
    4: "*1..4",
}


# ── Response Models ─────────────────────────────────────────────


class NodeResponse(BaseModel):
    """Graph node response."""

    id: str
    label: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class EdgeResponse(BaseModel):
    """Graph edge response."""

    source: str
    target: str
    relation_type: str
    weight: float | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphSnapshotResponse(BaseModel):
    """Graph snapshot for visualization."""

    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubgraphRequest(BaseModel):
    """Subgraph extraction request."""

    center_entity: str
    max_hops: int = Field(2, ge=1, le=4)
    include_types: list[str] | None = None
    exclude_types: list[str] | None = None


# ── Graph Visualization Endpoints ───────────────────────────────


@router.get("", response_model=APIResponse[GraphSnapshotResponse])
async def get_graph_visualization(
    limit: int = Query(100, ge=10, le=1000, description="Max nodes to return"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[GraphSnapshotResponse]:
    """Get a snapshot of the knowledge graph for visualization.

    Returns a subset of nodes and edges for initial visualization.
    Layout computation should be done on the client side using
    libraries like d3-force or cytoscape.js.

    **Migration:**
    - `/graph/visualization/snapshot` → `/graph/visualization`
    """
    node_query = """
    MATCH (e:Entity)
    RETURN e.canonical_name AS id,
           e.canonical_name AS label,
           e.type AS type,
           e.description AS description,
           size([(e)-[:RELATED_TO]-()|1]) AS degree
    ORDER BY degree DESC
    LIMIT $limit
    """

    try:
        results = await neo4j.execute_query(node_query, {"limit": limit})
    except Exception as exc:
        return success_response(
            GraphSnapshotResponse(
                nodes=[],
                edges=[],
                metadata={
                    "total_nodes": 0,
                    "error": str(exc)[:200] if str(exc) else "Graph service unavailable",
                },
            )
        )

    nodes = []
    node_ids = set()

    for r in results:
        nodes.append(
            NodeResponse(
                id=r.get("id") or "",
                label=r.get("label") or "",
                type=r.get("type") or "未知",
                properties={"description": r.get("description"), "degree": r.get("degree", 0)},
            )
        )
        node_ids.add(r.get("id"))

    if not node_ids:
        return success_response(
            GraphSnapshotResponse(nodes=[], edges=[], metadata={"total_nodes": 0})
        )

    edge_query = """
    MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
    WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
    RETURN e1.canonical_name AS source,
           e2.canonical_name AS target,
           r.relation_type AS relation_type,
           r.weight AS weight
    LIMIT $edge_limit
    """

    edge_limit = limit * 3
    try:
        edge_results = await neo4j.execute_query(
            edge_query,
            {
                "node_ids": list(node_ids),
                "edge_limit": edge_limit,
            },
        )
    except Exception:
        return success_response(
            GraphSnapshotResponse(
                nodes=nodes,
                edges=[],
                metadata={
                    "total_nodes": len(nodes),
                    "total_edges": 0,
                    "error": "Graph service unavailable",
                },
            )
        )

    edges = [
        EdgeResponse(
            source=r.get("source", ""),
            target=r.get("target", ""),
            relation_type=r.get("relation_type") or "RELATED_TO",
            weight=r.get("weight"),
        )
        for r in edge_results
    ]

    return success_response(
        GraphSnapshotResponse(
            nodes=nodes,
            edges=edges,
            metadata={"total_nodes": len(nodes), "total_edges": len(edges)},
        )
    )


@router.post("", response_model=APIResponse[GraphSnapshotResponse])
async def get_subgraph(
    request: SubgraphRequest,
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[GraphSnapshotResponse]:
    """Extract a subgraph around a center entity.

    Extracts nodes and edges within N hops of the center entity,
    with optional type filtering.

    Args:
        request: Subgraph extraction parameters.

    Returns:
        Subgraph with nodes and edges within N hops.

    """
    # Validate max_hops to prevent Cypher injection
    if not 1 <= request.max_hops <= 4:
        raise HTTPException(
            status_code=400,
            detail="max_hops must be between 1 and 4",
        )

    max_hops = int(request.max_hops)
    hop_pattern = _HOPS_PATTERNS.get(max_hops, "*1..2")  # Default to 2 hops
    cypher = f"""
    MATCH path = (center:Entity {{canonical_name: $center}})-[:RELATED_TO{hop_pattern}]-(related:Entity)
    """

    params: dict[str, Any] = {"center": request.center_entity}

    if request.include_types:
        cypher += "\nWHERE related.type IN $include_types"
        params["include_types"] = request.include_types

    cypher += """
    WITH collect(DISTINCT related) AS related_nodes
    MATCH (center:Entity {canonical_name: $center})
    WITH center + related_nodes AS all_nodes
    UNWIND all_nodes AS node
    MATCH (node)-[r:RELATED_TO]-(other)
    WHERE other IN all_nodes
    RETURN DISTINCT node.canonical_name AS id,
           node.canonical_name AS label,
           node.type AS type,
           node.description AS description
    LIMIT 200
    """

    results = await neo4j.execute_query(cypher, params)

    nodes = []
    node_ids = set()

    for r in results:
        if request.exclude_types and (r.get("type") or "未知") in request.exclude_types:
            continue
        nodes.append(
            NodeResponse(
                id=r.get("id") or "",
                label=r.get("label") or "",
                type=r.get("type") or "未知",
                properties={"description": r.get("description")},
            )
        )
        node_ids.add(r.get("id"))

    if not node_ids:
        raise HTTPException(status_code=404, detail="No nodes found in subgraph")

    edge_query = """
    MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
    WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
    RETURN e1.canonical_name AS source,
           e2.canonical_name AS target,
           r.relation_type AS relation_type,
           r.weight AS weight
    LIMIT 500
    """

    edge_results = await neo4j.execute_query(edge_query, {"node_ids": list(node_ids)})

    edges = [
        EdgeResponse(
            source=r.get("source", ""),
            target=r.get("target", ""),
            relation_type=r.get("relation_type") or "RELATED_TO",
            weight=r.get("weight"),
        )
        for r in edge_results
    ]

    return success_response(
        GraphSnapshotResponse(
            nodes=nodes,
            edges=edges,
            metadata={
                "center": request.center_entity,
                "max_hops": request.max_hops,
                "total_nodes": len(nodes),
                "total_edges": len(edges),
            },
        )
    )
