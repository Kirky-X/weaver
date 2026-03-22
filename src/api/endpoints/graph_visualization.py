# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph visualization API endpoints for enhanced knowledge graph exploration.

Provides API endpoints for:
- Graph topology visualization
- Interactive exploration
- Subgraph extraction
- Layout computation
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.endpoints import _deps as deps
from api.middleware.auth import verify_api_key
from core.db.neo4j import Neo4jPool

router = APIRouter(prefix="/graph/visualization", tags=["graph-visualization"])


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


class LayoutNode(BaseModel):
    """Node with computed layout."""

    id: str
    label: str
    type: str
    x: float = 0.0
    y: float = 0.0
    size: float = 10.0
    color: str = "#4285F4"
    properties: dict[str, Any] = Field(default_factory=dict)


class LayoutEdge(BaseModel):
    """Layout edge."""

    source: str
    target: str
    relation_type: str
    weight: float | None = None


class LayoutResponse(BaseModel):
    """Graph layout response."""

    nodes: list[LayoutNode]
    edges: list[LayoutEdge]
    metadata: dict[str, Any] = Field(default_factory=dict)


TYPE_COLORS = {
    "人物": "#E91E63",
    "组织机构": "#9C27B0",
    "地点": "#2196F3",
    "产品": "#4CAF50",
    "事件": "#FF9800",
    "概念": "#607D8B",
}


@router.get("/snapshot", response_model=GraphSnapshotResponse)
async def get_graph_snapshot(
    limit: int = Query(100, ge=10, le=1000, description="Max nodes to return"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(deps.Endpoints.get_neo4j_pool),
) -> GraphSnapshotResponse:
    """Get a snapshot of the knowledge graph.

    Returns a subset of nodes and edges for initial visualization.
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
        return GraphSnapshotResponse(
            nodes=[],
            edges=[],
            metadata={
                "total_nodes": 0,
                "error": str(exc)[:200] if str(exc) else "Graph service unavailable",
            },
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
        return GraphSnapshotResponse(nodes=[], edges=[], metadata={"total_nodes": 0})

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
        return GraphSnapshotResponse(
            nodes=nodes,
            edges=[],
            metadata={
                "total_nodes": len(nodes),
                "total_edges": 0,
                "error": "Graph service unavailable",
            },
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

    return GraphSnapshotResponse(
        nodes=nodes,
        edges=edges,
        metadata={"total_nodes": len(nodes), "total_edges": len(edges)},
    )


@router.post("/subgraph", response_model=GraphSnapshotResponse)
async def get_subgraph(
    request: SubgraphRequest,
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(deps.Endpoints.get_neo4j_pool),
) -> GraphSnapshotResponse:
    """Extract a subgraph around a center entity.

    Args:
        request: Subgraph extraction parameters.

    Returns:
        Subgraph with nodes and edges within N hops.
    """
    cypher = f"""
    MATCH path = (center:Entity {{canonical_name: $center}})-[:RELATED_TO*1..{request.max_hops}]-(related:Entity)
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

    return GraphSnapshotResponse(
        nodes=nodes,
        edges=edges,
        metadata={
            "center": request.center_entity,
            "max_hops": request.max_hops,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
    )


@router.get("/layout/force-directed", response_model=LayoutResponse)
async def get_force_directed_layout(
    center_entity: str = Query(..., description="Center entity name"),
    max_hops: int = Query(2, ge=1, le=4),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(deps.Endpoints.get_neo4j_pool),
) -> LayoutResponse:
    """Get a simple force-directed layout for visualization.

    This is a simplified layout - for production, consider using
    a proper graph layout library like d3-force or cytoscape.js.
    """
    import random

    random.seed(42)

    subgraph = await _extract_subgraph_nodes(neo4j, center_entity, max_hops)

    if not subgraph["nodes"]:
        raise HTTPException(status_code=404, detail="Entity not found")

    nodes_data = subgraph["nodes"]
    edges_data = subgraph["edges"]

    positions = _compute_simple_layout(nodes_data, edges_data)

    layout_nodes = []
    for node in nodes_data:
        pos = positions.get(node["id"], {"x": 0, "y": 0})
        color = TYPE_COLORS.get(node["type"], "#9E9E9E")
        size = min(40, 10 + node.get("degree", 0) * 2)

        layout_nodes.append(
            LayoutNode(
                id=node["id"],
                label=node["label"],
                type=node["type"],
                x=pos["x"],
                y=pos["y"],
                size=size,
                color=color,
                properties={"description": node.get("description")},
            )
        )

    layout_edges = [
        LayoutEdge(
            source=e["source"] or "",
            target=e["target"] or "",
            relation_type=e["relation_type"] or "RELATED_TO",
            weight=e.get("weight"),
        )
        for e in edges_data
    ]

    return LayoutResponse(
        nodes=layout_nodes,
        edges=layout_edges,
        metadata={
            "center": center_entity,
            "max_hops": max_hops,
            "total_nodes": len(layout_nodes),
            "total_edges": len(layout_edges),
        },
    )


async def _extract_subgraph_nodes(
    pool: Neo4jPool,
    center: str,
    hops: int,
) -> dict:
    """Extract subgraph nodes and edges."""
    cypher = f"""
    MATCH path = (center:Entity {{canonical_name: $center}})-[:RELATED_TO*1..{hops}]-(related:Entity)
    WITH collect(DISTINCT related) AS related_nodes
    MATCH (center:Entity {{canonical_name: $center}})
    WITH center + related_nodes AS all_nodes
    UNWIND all_nodes AS node
    MATCH (node)-[r:RELATED_TO]-(other)
    WHERE other IN all_nodes
    RETURN DISTINCT node.canonical_name AS id,
           node.canonical_name AS label,
           node.type AS type,
           node.description AS description,
           size([(node)-[:RELATED_TO]-()|1]) AS degree
    LIMIT 200
    """

    results = await pool.execute_query(cypher, {"center": center})

    nodes = [dict(r) for r in results]
    node_ids = {n["id"] for n in nodes}

    edge_query = """
    MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
    WHERE e1.canonical_name IN $node_ids AND e2.canonical_name IN $node_ids
    RETURN e1.canonical_name AS source,
           e2.canonical_name AS target,
           r.relation_type AS relation_type,
           r.weight AS weight
    LIMIT 500
    """

    edge_results = await pool.execute_query(edge_query, {"node_ids": list(node_ids)})
    edges = [dict(r) for r in edge_results]

    return {"nodes": nodes, "edges": edges}


def _compute_simple_layout(
    nodes: list[dict],
    edges: list[dict],
    width: float = 800,
    height: float = 600,
) -> dict[str, dict[str, float]]:
    """Compute a simple circular layout with force simulation approximation."""
    import math
    import random

    random.seed(42)

    positions: dict[str, dict[str, float]] = {}
    n = len(nodes)

    if n == 0:
        return positions

    for i, node in enumerate(nodes):
        angle = 2 * math.pi * i / n
        radius = min(width, height) * 0.35

        base_x = width / 2 + radius * math.cos(angle)
        base_y = height / 2 + radius * math.sin(angle)

        jitter = 30
        # Using deterministic random for consistent layout (not cryptographic)
        x = base_x + random.uniform(-jitter, jitter)  # noqa: S311
        y = base_y + random.uniform(-jitter, jitter)  # noqa: S311

        positions[node["id"]] = {"x": x, "y": y}

    node_ids = {n["id"] for n in nodes}
    edge_map: dict[str, set[str]] = {nid: set() for nid in node_ids}

    for e in edges:
        if e["source"] in node_ids and e["target"] in node_ids:
            edge_map[e["source"]].add(e["target"])
            edge_map[e["target"]].add(e["source"])

    iterations = 50
    k = math.sqrt((width * height) / n) * 2

    for _ in range(iterations):
        forces: dict[str, tuple[float, float]] = {}

        for node in nodes:
            nid = node["id"]
            forces[nid] = (0.0, 0.0)

        for e in edges:
            s, t = e["source"], e["target"]
            if s not in positions or t not in positions:
                continue

            sx, sy = positions[s]["x"], positions[s]["y"]
            tx, ty = positions[t]["x"], positions[t]["y"]

            dx = tx - sx
            dy = ty - sy
            dist = math.sqrt(dx * dx + dy * dy) + 0.1

            force = (k * k) / dist

            fx = (dx / dist) * force
            fy = (dy / dist) * force

            fx1, fy1 = forces[s]
            fx2, fy2 = forces[t]
            forces[s] = (fx1 + fx, fy1 + fy)
            forces[t] = (fx2 - fx, fy2 - fy)

        for _i, node in enumerate(nodes):
            nid = node["id"]
            fx, fy = forces.get(nid, (0, 0))

            fx += 0.01 * (width / 2 - positions[nid]["x"])
            fy += 0.01 * (height / 2 - positions[nid]["y"])

            positions[nid]["x"] += fx * 0.1
            positions[nid]["y"] += fy * 0.1

            positions[nid]["x"] = max(20, min(width - 20, positions[nid]["x"]))
            positions[nid]["y"] = max(20, min(height - 20, positions[nid]["y"]))

    return positions
