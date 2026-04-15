# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph visualization API endpoints for knowledge graph exploration.

Provides API endpoints for:
- Graph topology visualization (snapshot)
- Interactive subgraph exploration
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_graph_repo
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from api.schemas.types import RoundedFloatOpt

if TYPE_CHECKING:
    from modules.storage.graph_repo import GraphRepository

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
    weight: RoundedFloatOpt = None
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
    graph_repo: GraphRepository = Depends(get_graph_repo),
) -> APIResponse[GraphSnapshotResponse]:
    """Get a snapshot of the knowledge graph for visualization.

    Returns a subset of nodes and edges for initial visualization.
    Layout computation should be done on the client side using
    libraries like d3-force or cytoscape.js.

    **Migration:**
    - `/graph/visualization/snapshot` → `/graph/visualization`
    """
    try:
        nodes_data = await graph_repo.get_visualization_nodes(limit)
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

    for node in nodes_data:
        nodes.append(
            NodeResponse(
                id=node["id"],
                label=node["label"],
                type=node["type"],
                properties={
                    "description": node.get("description"),
                    "degree": node.get("degree", 0),
                },
            )
        )
        node_ids.add(node["id"])

    if not node_ids:
        return success_response(
            GraphSnapshotResponse(nodes=[], edges=[], metadata={"total_nodes": 0})
        )

    edge_limit = limit * 3
    try:
        edges_data = await graph_repo.get_visualization_edges(list(node_ids), edge_limit)
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
            source=edge["source"],
            target=edge["target"],
            relation_type=edge["relation_type"],
            weight=edge.get("weight"),
        )
        for edge in edges_data
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
    graph_repo: GraphRepository = Depends(get_graph_repo),
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

    try:
        nodes_data = await graph_repo.get_subgraph_nodes(
            center_entity=request.center_entity,
            hop_pattern=hop_pattern,
            include_types=request.include_types,
            exclude_types=request.exclude_types,
        )
    except Exception:
        raise HTTPException(status_code=404, detail="No nodes found in subgraph")

    nodes = []
    node_ids = set()

    for node in nodes_data:
        nodes.append(
            NodeResponse(
                id=node["id"],
                label=node["label"],
                type=node["type"],
                properties={"description": node.get("description")},
            )
        )
        node_ids.add(node["id"])

    if not node_ids:
        raise HTTPException(status_code=404, detail="No nodes found in subgraph")

    edges_data = await graph_repo.get_subgraph_edges(list(node_ids))

    edges = [
        EdgeResponse(
            source=edge["source"],
            target=edge["target"],
            relation_type=edge["relation_type"],
            weight=edge.get("weight"),
        )
        for edge in edges_data
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
