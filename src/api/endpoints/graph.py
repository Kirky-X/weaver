# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph API endpoints for entity and relationship queries."""

from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from api.dependencies import get_neo4j_pool
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.db.models import RelationType, RelationTypeAlias
from core.db.neo4j import Neo4jPool
from core.db.postgres import PostgresPool
from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

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


class RelationTypeInfo(BaseModel):
    """Relation type with statistics from PostgreSQL."""

    name: str
    name_en: str
    category: str
    is_symmetric: bool
    description: str | None = None
    alias_count: int


# ── Dependency for PostgreSQL Pool ──────────────────────────────

_pg_pool: PostgresPool | None = None


def set_postgres_pool(pool: PostgresPool) -> None:
    """Set the global PostgreSQL pool instance."""
    global _pg_pool
    _pg_pool = pool


# ── Endpoints ───────────────────────────────────────────────────


@router.get("/entities/{name}", response_model=APIResponse[EntityWithRelations])
async def get_entity(
    name: str,
    limit: int = Query(10, ge=1, le=100, description="Max related entities to return"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[EntityWithRelations]:
    """Get entity information and its relationships.

    Args:
        name: Entity canonical name (URL encoded).
        limit: Maximum number of related entities to return.
        _: Verified API key.
        neo4j: Neo4j client.

    Returns:
        Entity with relationships wrapped in APIResponse.
    """
    canonical_name = urllib.parse.unquote(name)

    async with neo4j.session() as session:
        # Get entity
        result = await session.run(
            """
            MATCH (e:Entity {canonical_name: $name})
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, e.description as description,
                   e.updated_at as updated_at
            """,
            name=canonical_name,
        )
        record = await result.single()

        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{canonical_name}' not found",
            )

        entity = EntityResponse(
            id=record.get("id") or "",
            canonical_name=record.get("canonical_name") or "",
            type=record.get("type") or "未知",
            aliases=record.get("aliases"),
            description=record.get("description"),
            updated_at=record["updated_at"].isoformat() if record.get("updated_at") else None,
        )

        # Get relationships FROM this entity
        rel_result = await session.run(
            """
            MATCH (e:Entity {canonical_name: $name})-[r:RELATED_TO]->(target:Entity)
            RETURN target.canonical_name as target, r.relation_type as relation_type,
                   r.source_article_id as source_article_id, r.created_at as created_at
            ORDER BY r.created_at DESC
            LIMIT $limit
            """,
            name=canonical_name,
            limit=limit,
        )

        relationships = []
        async for row in rel_result:
            relationships.append(
                EntityRelationship(
                    target=row["target"],
                    relation_type=row["relation_type"] or "RELATED_TO",
                    source_article_id=row.get("source_article_id"),
                    created_at=row["created_at"].isoformat() if row.get("created_at") else None,
                )
            )

        # Get related entities (entities mentioned in same articles)
        related_result = await session.run(
            """
            MATCH (e:Entity {canonical_name: $name})-[:MENTIONS]-(a:Article)-[:MENTIONS]-(re:Entity)
            WHERE re.canonical_name <> $name
            RETURN DISTINCT re.id as id, re.canonical_name as canonical_name,
                   re.type as type, re.aliases as aliases
            LIMIT $limit
            """,
            name=canonical_name,
            limit=limit,
        )

        related_entities = []
        async for row in related_result:
            related_entities.append(
                EntityResponse(
                    id=row.get("id") or "",
                    canonical_name=row.get("canonical_name") or "",
                    type=row.get("type") or "未知",
                    aliases=row.get("aliases"),
                    description=None,
                    updated_at=None,
                )
            )

        # Get articles mentioning this entity
        articles_result = await session.run(
            """
            MATCH (e:Entity {canonical_name: $name})-[:MENTIONS]->(a:Article)
            RETURN a.pg_id as id, a.title as title, a.category as category,
                   a.publish_time as publish_time, a.score as score
            ORDER BY a.publish_time DESC
            LIMIT $limit
            """,
            name=canonical_name,
            limit=limit,
        )

        mentioned_in_articles = []
        async for row in articles_result:
            mentioned_in_articles.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "category": row.get("category"),
                    "publish_time": (
                        row["publish_time"].isoformat() if row.get("publish_time") else None
                    ),
                    "score": row.get("score"),
                }
            )

        return success_response(
            EntityWithRelations(
                entity=entity,
                relationships=relationships,
                related_entities=related_entities,
                mentioned_in_articles=mentioned_in_articles,
            )
        )


@router.get("/articles/{article_id}/graph", response_model=APIResponse[ArticleGraphResponse])
async def get_article_graph(
    article_id: str,
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[ArticleGraphResponse]:
    """Get the knowledge graph for a specific article.

    Args:
        article_id: The article UUID (Postgres ID).
        _: Verified API key.
        neo4j: Neo4j client.

    Returns:
        Article graph with entities and relationships wrapped in APIResponse.
    """
    async with neo4j.session() as session:
        # Get article node
        article_result = await session.run(
            """
            MATCH (a:Article {pg_id: $id})
            RETURN a.pg_id as id, a.title as title, a.category as category,
                   a.publish_time as publish_time, a.score as score
            """,
            id=article_id,
        )
        article_record = await article_result.single()

        if article_record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Article '{article_id}' not found in graph",
            )

        article = ArticleGraphNode(
            id=article_record.get("id") or "",
            title=article_record.get("title") or "",
            category=article_record.get("category"),
            publish_time=(
                article_record["publish_time"].isoformat()
                if article_record.get("publish_time")
                else None
            ),
            score=article_record.get("score"),
        )

        # Get entities mentioned in this article
        entities_result = await session.run(
            """
            MATCH (a:Article {pg_id: $id})-[r:MENTIONS]->(e:Entity)
            RETURN e.id as id, e.canonical_name as canonical_name, e.type as type,
                   e.aliases as aliases, r.role as role
            """,
            id=article_id,
        )

        entities = []
        async for row in entities_result:
            entities.append(
                EntityResponse(
                    id=row.get("id") or "",
                    canonical_name=row.get("canonical_name") or "",
                    type=row.get("type") or "未知",
                    aliases=row.get("aliases"),
                    description=None,
                    updated_at=None,
                )
            )

        # Get relationships between entities in this article
        rels_result = await session.run(
            """
            MATCH (a:Article {pg_id: $id})-[:MENTIONS]->(e1:Entity)
            MATCH (e1)-[r:RELATED_TO]->(e2:Entity)
            WHERE (a)-[:MENTIONS]->(e2)
            RETURN e1.canonical_name as source, e2.canonical_name as target,
                   r.relation_type as relation_type,
                   r.source_article_id as source_article_id, r.created_at as created_at
            """,
            id=article_id,
        )

        relationships = []
        async for row in rels_result:
            relationships.append(
                ArticleGraphRelationship(
                    source_id=row["source"],
                    target_id=row["target"],
                    relation_type=row["relation_type"] or "RELATED_TO",
                    properties={
                        "source_article_id": row.get("source_article_id"),
                        "created_at": (
                            row["created_at"].isoformat() if row.get("created_at") else None
                        ),
                    },
                )
            )

        # Get related articles (followed by or similar topic)
        related_result = await session.run(
            """
            MATCH (a:Article {pg_id: $id})-[r:FOLLOWED_BY|MENTIONS]->(ra:Article)
            RETURN DISTINCT ra.pg_id as id, ra.title as title, ra.category as category,
                   ra.publish_time as publish_time, ra.score as score,
                   type(r) as relation_type
            ORDER BY ra.publish_time DESC
            LIMIT 10
            """,
            id=article_id,
        )

        related_articles = []
        async for row in related_result:
            related_articles.append(
                ArticleGraphNode(
                    id=row.get("id") or "",
                    title=row.get("title") or "",
                    category=row.get("category"),
                    publish_time=(
                        row["publish_time"].isoformat() if row.get("publish_time") else None
                    ),
                    score=row.get("score"),
                )
            )

        return success_response(
            ArticleGraphResponse(
                article=article,
                entities=entities,
                relationships=relationships,
                related_articles=related_articles,
            )
        )


# ── Relation Search Endpoints ─────────────────────────────────


@router.get("/relations", response_model=APIResponse[list[RelationTypeSummary]])
async def get_entity_relations(
    entity: str = Query(..., description="Entity canonical name"),
    entity_type: str = Query("组织机构", description="Entity type"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[list[RelationTypeSummary]]:
    """Layer 1: Discover all relation types for an entity.

    Args:
        entity: Entity canonical name.
        entity_type: Entity type (e.g. '组织机构', '人物').
        _: Verified API key.
        neo4j: Neo4j client.

    Returns:
        List of relation type summaries wrapped in APIResponse.
    """
    repo = Neo4jEntityRepo(neo4j)
    rows = await repo.get_relation_types(entity, entity_type)
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
    neo4j: Neo4jPool = Depends(get_neo4j_pool),
) -> APIResponse[list[RelatedEntityResult]]:
    """Layer 2: Search related entities by relation types.

    Args:
        entity: Entity canonical name.
        entity_type: Entity type.
        relation_types: Optional comma-separated list of relation types to filter.
        limit: Maximum number of results (1-200).
        _: Verified API key.
        neo4j: Neo4j client.

    Returns:
        List of related entities wrapped in APIResponse.
    """
    repo = Neo4jEntityRepo(neo4j)
    types_list = (
        [t.strip() for t in relation_types.split(",") if t.strip()] if relation_types else None
    )
    rows = await repo.find_by_relation_types(entity, entity_type, types_list, limit)
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


@router.get("/relation-types", response_model=APIResponse[list[RelationTypeInfo]])
async def list_relation_types(
    _: str = Depends(verify_api_key),
) -> APIResponse[list[RelationTypeInfo]]:
    """List all active relation types with statistics.

    Args:
        _: Verified API key.

    Returns:
        List of relation types ordered by sort_order, wrapped in APIResponse.

    Raises:
        HTTPException: 503 if PostgreSQL pool not initialized.
    """
    if _pg_pool is None:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL pool not initialized",
        )

    async with _pg_pool.session_context() as session:
        stmt = (
            select(
                RelationType.name,
                RelationType.name_en,
                RelationType.category,
                RelationType.is_symmetric,
                RelationType.description,
                func.count(RelationTypeAlias.id).label("alias_count"),
            )
            .outerjoin(RelationTypeAlias)
            .where(RelationType.is_active == True)  # noqa: E712
            .group_by(RelationType.id)
            .order_by(RelationType.sort_order)
        )
        result = await session.execute(stmt)
        return success_response(
            [
                RelationTypeInfo(
                    name=row.name,
                    name_en=row.name_en,
                    category=row.category,
                    is_symmetric=row.is_symmetric,
                    description=row.description,
                    alias_count=row.alias_count,
                )
                for row in result
            ]
        )
