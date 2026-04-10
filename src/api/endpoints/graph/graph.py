# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph API endpoints for entity and relationship queries."""

from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_graph_repo
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
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
    entity_type: str = Query("组织机构", description="Entity type"),
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

    """
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
    entity_type: str = Query("组织机构", description="Entity type"),
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
