# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph API endpoints for entity and relationship queries."""

from __future__ import annotations

import urllib.parse
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_graph_pool, get_graph_pool_type, get_graph_repo
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from api.schemas.traverse import (
    EdgeResponse,
    PathNode,
    PathResponse,
    TraverseRequest,
    TraverseResponse,
    TraverseResultItem,
    TraverseStatistics,
)
from core.protocols import GraphPool
from modules.storage.graph_repo import GraphRepository

router = APIRouter(prefix="/graph", tags=["graph"])


# ── Request/Response Models ─────────────────────────────────────


class EntityResponse(BaseModel):
    """Response model for entity."""

    id: str
    canonical_name: str
    type: str
    aliases: list[str] | None
    description: str | None
    updated_at: str | None


class EntityRelationship(BaseModel):
    """Response model for entity relationship."""

    target: str
    relation_type: str
    source_article_id: str | None
    created_at: str | None


class EntityWithRelations(BaseModel):
    """Response model for entity with relationships."""

    entity: EntityResponse
    relationships: list[EntityRelationship]
    related_entities: list[EntityResponse]
    mentioned_in_articles: list[dict[str, Any]]


class ArticleGraphNode(BaseModel):
    """Node in article graph."""

    id: str
    title: str
    category: str | None
    publish_time: str | None
    score: float | None


class ArticleGraphRelationship(BaseModel):
    """Relationship in article graph."""

    source_id: str
    target_id: str
    relation_type: str
    properties: dict[str, Any] | None


class ArticleGraphResponse(BaseModel):
    """Response model for article graph."""

    article: ArticleGraphNode
    entities: list[EntityResponse]
    relationships: list[ArticleGraphRelationship]
    related_articles: list[ArticleGraphNode]


class RelationTypeSummary(BaseModel):
    """Layer 1: Summary of a relation type for an entity."""

    relation_type: str
    target_count: int
    primary_direction: str


class RelatedEntityResult(BaseModel):
    """Layer 2: Related entity matched by relation type."""

    relation_type: str
    direction: str
    target_name: str
    target_type: str
    target_description: str | None = None
    weight: float = 1.0


# ── Endpoints ───────────────────────────────────────────────────


@router.get("/entities", response_model=APIResponse[list[dict[str, Any]]])
async def list_entities(
    entity_type: str | None = Query(None, description="Filter by entity type"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Result offset"),
    _: str = Depends(verify_api_key),
    pool: GraphPool = Depends(get_graph_pool),
    pool_type: str = Depends(get_graph_pool_type),
) -> APIResponse[list[dict[str, Any]]]:
    """List entities with optional type filter.

    Returns a paginated list of entities from the graph database.
    Works with both Neo4j and LadybugDB backends.

    Args:
        entity_type: Optional entity type filter.
        limit: Maximum number of results (1-100).
        offset: Result offset for pagination.
        _: Verified API key.
        pool: GraphPool connection pool.
        pool_type: Graph database type ('neo4j' or 'ladybug').

    Returns:
        List of entities with id, name, entity_type, and mention_count.

    """
    # Build query conditionally based on entity_type filter.
    # Use undirected MENTIONS pattern to count article mentions across
    # both Neo4j (Entity->Article) and LadybugDB (Article->Entity) directions.
    where_clause = "WHERE e.type = $entity_type" if entity_type is not None else ""
    query = f"""
        MATCH (e:Entity)
        {where_clause}
        OPTIONAL MATCH (a:Article)-[m:MENTIONS]-(e)
        WITH e, count(DISTINCT a) AS mention_count
        RETURN e.id AS id, e.canonical_name AS name, e.type AS entity_type,
               mention_count
        ORDER BY mention_count DESC, e.canonical_name ASC
        SKIP $offset LIMIT $limit
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if entity_type is not None:
        params["entity_type"] = entity_type

    try:
        rows = await pool.execute_query(query, params)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list entities: {exc!s}",
        ) from exc

    entities = [
        {
            "id": str(row.get("id") or ""),
            "name": row.get("name") or "",
            "entity_type": row.get("entity_type") or "未知",
            "mention_count": int(row.get("mention_count") or 0),
        }
        for row in rows
    ]
    return success_response(entities)


@router.get("/entities/{name}", response_model=APIResponse[EntityWithRelations])
async def get_entity(
    name: str,
    limit: int = Query(10, ge=1, le=100, description="Max related entities to return"),
    _: str = Depends(verify_api_key),
    graph_repo: GraphRepository = Depends(get_graph_repo),
) -> APIResponse[EntityWithRelations]:
    """Get entity information and its relationships.

    Args:
        name: Entity canonical name (URL encoded).
        limit: Maximum number of related entities to return.
        _: Verified API key.
        graph_repo: Graph repository (database-agnostic).

    Returns:
        Entity with relationships wrapped in APIResponse.

    """
    canonical_name = urllib.parse.unquote(name)

    # Get entity
    entity = await graph_repo.get_entity(canonical_name)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{canonical_name}' not found",
        )

    # Get relationships in parallel
    relationships = await graph_repo.get_entity_relations(canonical_name, limit)
    related_entities = await graph_repo.get_related_entities(canonical_name, limit)
    mentioned_articles = await graph_repo.get_entity_articles(canonical_name, limit)

    return success_response(
        EntityWithRelations(
            entity=EntityResponse(**entity),
            relationships=[EntityRelationship(**r) for r in relationships],
            related_entities=[EntityResponse(**e) for e in related_entities],
            mentioned_in_articles=mentioned_articles,
        )
    )


@router.get("/articles/{article_id}/graph", response_model=APIResponse[ArticleGraphResponse])
async def get_article_graph(
    article_id: str,
    _: str = Depends(verify_api_key),
    graph_repo: GraphRepository = Depends(get_graph_repo),
) -> APIResponse[ArticleGraphResponse]:
    """Get the knowledge graph for a specific article.

    Args:
        article_id: The article UUID (Postgres ID).
        _: Verified API key.
        graph_repo: Graph repository (database-agnostic).

    Returns:
        Article graph with entities and relationships wrapped in APIResponse.

    """
    # Get article node
    article = await graph_repo.get_article(article_id)
    if article is None:
        raise HTTPException(
            status_code=404,
            detail=f"Article '{article_id}' not found in graph",
        )

    # Get entities and relationships
    entities = await graph_repo.get_article_entities(article_id)
    relationships = await graph_repo.get_article_relationships(article_id)
    related_articles = await graph_repo.get_related_articles(article_id)

    return success_response(
        ArticleGraphResponse(
            article=ArticleGraphNode(**article),
            entities=[EntityResponse(**e) for e in entities],
            relationships=[ArticleGraphRelationship(**r) for r in relationships],
            related_articles=[ArticleGraphNode(**a) for a in related_articles],
        )
    )


# ── Relation Search Endpoints ─────────────────────────────────


@router.get("/relations", response_model=APIResponse[list[RelationTypeSummary]])
async def get_entity_relations(
    entity: str = Query(..., description="Entity canonical name"),
    entity_type: str | None = Query(
        None, description="Entity type (optional, e.g. '组织机构', '人物')"
    ),
    _: str = Depends(verify_api_key),
    graph_repo: GraphRepository = Depends(get_graph_repo),
) -> APIResponse[list[RelationTypeSummary]]:
    """Layer 1: Discover all relation types for an entity.

    Args:
        entity: Entity canonical name.
        entity_type: Entity type (e.g. '组织机构', '人物').
        _: Verified API key.
        graph_repo: Graph repository (database-agnostic).

    Returns:
        List of relation type summaries wrapped in APIResponse.

    Raises:
        HTTPException: 404 if entity does not exist in the graph.

    """
    # Verify entity exists before listing relation types (P0-1: return 404
    # for non-existent entities instead of empty 200 array).
    existing = await graph_repo.get_entity(entity)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{entity}' not found",
        )

    rows = await graph_repo.get_relation_types(entity, entity_type)
    return success_response(
        [
            RelationTypeSummary(
                relation_type=r["relation_type"],
                target_count=r["target_count"],
                primary_direction=r["primary_direction"],
            )
            for r in rows
        ]
    )


@router.get("/relations/search", response_model=APIResponse[list[RelatedEntityResult]])
async def search_relations(
    entity: str = Query(..., description="Entity canonical name"),
    entity_type: str | None = Query(None, description="Entity type (optional)"),
    relation_types: str | None = Query(None, description="Comma-separated relation types"),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(verify_api_key),
    graph_repo: GraphRepository = Depends(get_graph_repo),
) -> APIResponse[list[RelatedEntityResult]]:
    """Layer 2: Search related entities by relation types.

    Args:
        entity: Entity canonical name.
        entity_type: Entity type.
        relation_types: Optional comma-separated list of relation types to filter.
        limit: Maximum number of results (1-200).
        _: Verified API key.
        graph_repo: Graph repository (database-agnostic).

    Returns:
        List of related entities wrapped in APIResponse.

    """
    types_list = (
        [t.strip() for t in relation_types.split(",") if t.strip()] if relation_types else None
    )
    rows = await graph_repo.find_by_relation_types(entity, entity_type, types_list, limit)
    return success_response(
        [
            RelatedEntityResult(
                relation_type=r["relation_type"],
                direction=r["direction"],
                target_name=r["target_name"],
                target_type=r["target_type"],
                target_description=r.get("target_description"),
                weight=r.get("weight", 1.0),
            )
            for r in rows
        ]
    )


# ── Traverse Endpoint ────────────────────────────────────────────


@router.post("/traverse", response_model=APIResponse[TraverseResponse])
async def traverse_graph(
    request: TraverseRequest,
    _: str = Depends(verify_api_key),
    graph_repo: GraphRepository = Depends(get_graph_repo),
) -> APIResponse[TraverseResponse]:
    """Multi-hop graph traversal from a starting entity.

    Supports relation type filtering, depth limiting, timeout control,
    path return mode, aggregate mode, and confidence filtering.

    Args:
        request: Traverse request parameters.
        _: Verified API key.
        graph_repo: Graph repository (database-agnostic).

    Returns:
        Traversal results wrapped in APIResponse.

    """
    results = await graph_repo.traverse(
        start_entity=request.start_entity,
        max_depth=request.max_depth,
        relation_types=request.relation_types,
        max_results=request.max_results,
        timeout_seconds=request.timeout_seconds,
        return_paths=request.return_paths,
        mode=request.mode,
        min_confidence=request.min_confidence,
    )

    result_items = []
    total_nodes = 0
    total_edges = 0
    max_depth_found = 0
    for item in results:
        nodes = [
            PathNode(
                id=n.get("id", ""),
                canonical_name=n.get("canonical_name", ""),
                type=n.get("type", ""),
                description=n.get("description"),
            )
            for n in item.get("nodes", [])
        ]
        edges = [
            EdgeResponse(
                source=e.get("source", ""),
                target=e.get("target", ""),
                relation_type=e.get("relation_type", ""),
                weight=e.get("weight"),
            )
            for e in item.get("edges", [])
        ]
        paths = None
        if item.get("paths"):
            paths = [
                PathResponse(
                    nodes=p.get("nodes", []),
                    edges=p.get("edges", []),
                )
                for p in item["paths"]
            ]
        total_nodes += len(nodes)
        total_edges += len(edges)
        # Track max depth from paths
        if paths:
            for p in paths:
                max_depth_found = max(max_depth_found, len(p.nodes) - 1)
        result_items.append(
            TraverseResultItem(
                nodes=nodes,
                edges=edges,
                paths=paths,
                aggregate=item.get("aggregate"),
            )
        )

    # Compute depth_reached: from paths if available, otherwise BFS from start entity
    if max_depth_found == 0 and total_edges > 0:
        # Build adjacency list from all result edges for BFS
        adj: dict[str, set[str]] = {}
        for item in results:
            for e in item.get("edges", []):
                src = e.get("source", "")
                tgt = e.get("target", "")
                if src and tgt:
                    adj.setdefault(src, set()).add(tgt)
                    adj.setdefault(tgt, set()).add(src)
        # BFS from start entity to find actual depth reached
        visited = {request.start_entity}
        queue = deque([(request.start_entity, 0)])
        while queue:
            node, depth = queue.popleft()
            max_depth_found = max(max_depth_found, depth)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

    statistics = TraverseStatistics(
        nodes_visited=total_nodes,
        edges_traversed=total_edges,
        depth_reached=max_depth_found,
    )

    return success_response(TraverseResponse(results=result_items, statistics=statistics))
