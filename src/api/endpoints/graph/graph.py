# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph API endpoints for entity and relationship queries."""

from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_graph_repo, get_relational_pool
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from api.schemas.types import RoundedFloat, RoundedFloatOpt
from core.observability.logging import get_logger
from core.protocols import RelationalPool
from modules.storage.graph_repo import GraphRepository

log = get_logger(__name__)

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
    score: RoundedFloatOpt


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
    graph_synced: bool = True
    """Whether the article is synced to the graph database."""


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
    weight: RoundedFloat = 1.0


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
    try:
        entity = await graph_repo.get_entity(canonical_name)
        relationships = await graph_repo.get_entity_relations(canonical_name, limit)
        related_entities = await graph_repo.get_related_entities(canonical_name, limit)
        mentioned_articles = await graph_repo.get_entity_articles(canonical_name, limit)
    except Exception as exc:
        log.warning("graph_entity_fetch_failed", entity=canonical_name, error=str(exc))
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{canonical_name}' not found or graph unavailable",
        )

    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{canonical_name}' not found",
        )

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
    relational_pool: RelationalPool = Depends(get_relational_pool),
) -> APIResponse[ArticleGraphResponse]:
    """Get the knowledge graph for a specific article.

    Args:
        article_id: The article UUID (Postgres ID).
        _: Verified API key.
        graph_repo: Graph repository (database-agnostic).
        relational_pool: Relational database pool for fallback lookup.

    Returns:
        Article graph with entities and relationships wrapped in APIResponse.

    """
    # Try to get article from graph database
    try:
        article = await graph_repo.get_article(article_id)
        if article:
            entities = await graph_repo.get_article_entities(article_id)
            relationships = await graph_repo.get_article_relationships(article_id)
            related_articles = await graph_repo.get_related_articles(article_id)
    except Exception as exc:
        log.warning("article_graph_fetch_failed", article_id=str(article_id), error=str(exc))
        article = None
        entities = []
        relationships = []
        related_articles = []

    if article is None:
        # Fallback: check PostgreSQL for article existence
        from sqlalchemy import select

        from core.db.models import Article

        async with relational_pool.session() as session:
            query = select(Article).where(Article.id == article_id)
            result = await session.execute(query)
            pg_article = result.scalar_one_or_none()

        if pg_article is not None:
            # Article exists in PostgreSQL but not synced to graph
            # Return partial response with graph_synced=False
            pg_article_data = {
                "id": str(pg_article.id),
                "title": pg_article.title or "",
                "category": pg_article.category.value if pg_article.category else None,
                "publish_time": (
                    pg_article.publish_time.isoformat()
                    if pg_article.publish_time and hasattr(pg_article.publish_time, "isoformat")
                    else str(pg_article.publish_time or "")
                ),
                "score": pg_article.score,
            }
            return success_response(
                ArticleGraphResponse(
                    article=ArticleGraphNode(**pg_article_data),
                    entities=[],
                    relationships=[],
                    related_articles=[],
                    graph_synced=False,
                )
            )

        # Article not found in either database
        raise HTTPException(
            status_code=404,
            detail=f"Article '{article_id}' not found",
        )

    # Article found in graph - use already fetched data from try block

    return success_response(
        ArticleGraphResponse(
            article=ArticleGraphNode(**article),
            entities=[EntityResponse(**e) for e in entities],
            relationships=[ArticleGraphRelationship(**r) for r in relationships],
            related_articles=[ArticleGraphNode(**a) for a in related_articles],
            graph_synced=True,
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
    result_list = [
        RelationTypeSummary(
            relation_type=r["relation_type"],
            target_count=r["target_count"],
            primary_direction=r["primary_direction"],
        )
        for r in rows
    ]

    # Provide helpful message when no relations found
    if not result_list:
        # Check if entity exists to provide context
        entity_data = await graph_repo.get_entity(entity)
        if entity_data is None:
            log.info("entity_not_found_for_relations", entity=entity)
            raise HTTPException(
                status_code=404,
                detail=f"实体 '{entity}' 不存在于知识图谱中",
            )
        log.info("entity_has_no_relations", entity=entity)
        return success_response(
            result_list,
            message=f"实体 '{entity}' 存在但未发现任何关系。",
        )

    return success_response(result_list)


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
    try:
        rows = await graph_repo.find_by_relation_types(entity, entity_type, types_list, limit)
    except Exception as exc:
        log.warning("relations_search_failed", entity=entity, error=str(exc))
        rows = []
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
