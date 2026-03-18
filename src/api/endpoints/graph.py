# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph API endpoints for entity and relationship queries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.middleware.auth import verify_api_key
from core.db.neo4j import Neo4jPool

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


# ── Dependency for Neo4j Client ─────────────────────────────────

_neo4j_client: Neo4jPool | None = None


def set_neo4j_client(client: Neo4jPool) -> None:
    """Set the global Neo4j client instance."""
    global _neo4j_client
    _neo4j_client = client


def get_neo4j_client() -> Neo4jPool:
    """Get the Neo4j client instance."""
    if _neo4j_client is None:
        raise HTTPException(
            status_code=503,
            detail="Neo4j client not initialized",
        )
    return _neo4j_client


# ── Endpoints ───────────────────────────────────────────────────


@router.get("/entities/{name}", response_model=EntityWithRelations)
async def get_entity(
    name: str,
    limit: int = Query(10, ge=1, le=100, description="Max related entities to return"),
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_client),
) -> EntityWithRelations:
    """Get entity information and its relationships.

    Args:
        name: Entity canonical name (URL encoded).
        limit: Maximum number of related entities to return.
        _: Verified API key.
        neo4j: Neo4j client.

    Returns:
        Entity with relationships.
    """
    import urllib.parse

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
            id=record["id"],
            canonical_name=record["canonical_name"],
            type=record["type"],
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
                    relation_type=row["relation_type"],
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
                    id=row["id"],
                    canonical_name=row["canonical_name"],
                    type=row["type"],
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

        return EntityWithRelations(
            entity=entity,
            relationships=relationships,
            related_entities=related_entities,
            mentioned_in_articles=mentioned_in_articles,
        )


@router.get("/articles/{article_id}/graph", response_model=ArticleGraphResponse)
async def get_article_graph(
    article_id: str,
    _: str = Depends(verify_api_key),
    neo4j: Neo4jPool = Depends(get_neo4j_client),
) -> ArticleGraphResponse:
    """Get the knowledge graph for a specific article.

    Args:
        article_id: The article UUID (Postgres ID).
        _: Verified API key.
        neo4j: Neo4j client.

    Returns:
        Article graph with entities and relationships.
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
            id=article_record["id"],
            title=article_record["title"],
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
                    id=row["id"],
                    canonical_name=row["canonical_name"],
                    type=row["type"],
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
                    relation_type=row["relation_type"],
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
                    id=row["id"],
                    title=row["title"],
                    category=row.get("category"),
                    publish_time=(
                        row["publish_time"].isoformat() if row.get("publish_time") else None
                    ),
                    score=row.get("score"),
                )
            )

        return ArticleGraphResponse(
            article=article,
            entities=entities,
            relationships=relationships,
            related_articles=related_articles,
        )
