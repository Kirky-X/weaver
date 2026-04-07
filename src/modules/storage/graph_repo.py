# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Abstract graph repository using QueryBuilder pattern.

Provides database-agnostic graph operations by delegating query building
to GraphQueryBuilder implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.db.graph_query_builders import GraphQueryBuilder
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger("graph_repo")


class GraphRepository:
    """Database-agnostic graph repository.

    Handles entity and article graph operations using the QueryBuilder pattern
    to abstract Neo4j/LadybugDB syntax differences.

    Args:
        pool: Graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder.
    """

    def __init__(self, pool: GraphPool, query_builder: GraphQueryBuilder) -> None:
        self._pool = pool
        self._query_builder = query_builder

    @property
    def database_type(self) -> str:
        """Get the database type."""
        return self._query_builder.database_type.value

    # ── Entity Operations ─────────────────────────────────────────────

    async def get_entity(self, canonical_name: str) -> dict[str, Any] | None:
        """Get entity by canonical name.

        Args:
            canonical_name: Entity canonical name.

        Returns:
            Entity dict or None if not found.
        """
        query = self._query_builder.build_get_entity_query()
        result = await self._pool.execute_query(query, {"name": canonical_name})
        if result:
            record = result[0]
            return {
                "id": record.get("id") or "",
                "canonical_name": record.get("canonical_name") or "",
                "type": record.get("type") or "未知",
                "aliases": record.get("aliases"),
                "description": record.get("description"),
                "updated_at": (
                    record["updated_at"].isoformat() if record.get("updated_at") else None
                ),
            }
        return None

    async def get_entity_relations(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get relationships from an entity.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of relationships.

        Returns:
            List of relationship dicts.
        """
        query = self._query_builder.build_get_entity_relations_query()
        result = await self._pool.execute_query(query, {"name": canonical_name, "limit": limit})
        relations = []
        for row in result:
            relations.append(
                {
                    "target": row["target"],
                    "relation_type": row["relation_type"] or "RELATED_TO",
                    "source_article_id": row.get("source_article_id"),
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                }
            )
        return relations

    async def get_related_entities(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get entities mentioned in same articles.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of entities.

        Returns:
            List of entity dicts.
        """
        query = self._query_builder.build_get_related_entities_query()
        result = await self._pool.execute_query(query, {"name": canonical_name, "limit": limit})
        entities = []
        for row in result:
            entities.append(
                {
                    "id": row.get("id") or "",
                    "canonical_name": row.get("canonical_name") or "",
                    "type": row.get("type") or "未知",
                    "aliases": row.get("aliases"),
                    "description": None,
                    "updated_at": None,
                }
            )
        return entities

    async def get_entity_articles(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get articles mentioning an entity.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of articles.

        Returns:
            List of article dicts.
        """
        query = self._query_builder.build_get_entity_articles_query()
        result = await self._pool.execute_query(query, {"name": canonical_name, "limit": limit})
        articles = []
        for row in result:
            articles.append(
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
        return articles

    # ── Article Graph Operations ───────────────────────────────────────

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        """Get article node from graph.

        Args:
            article_id: Article UUID (pg_id).

        Returns:
            Article dict or None if not found.
        """
        query = self._query_builder.build_get_article_graph_query()
        result = await self._pool.execute_query(query, {"id": article_id})
        if result:
            record = result[0]
            return {
                "id": record.get("id") or "",
                "title": record.get("title") or "",
                "category": record.get("category"),
                "publish_time": (
                    record["publish_time"].isoformat() if record.get("publish_time") else None
                ),
                "score": record.get("score"),
            }
        return None

    async def get_article_entities(self, article_id: str) -> list[dict[str, Any]]:
        """Get entities mentioned in an article.

        Args:
            article_id: Article UUID.

        Returns:
            List of entity dicts.
        """
        query = self._query_builder.build_get_article_entities_query()
        result = await self._pool.execute_query(query, {"id": article_id})
        entities = []
        for row in result:
            entities.append(
                {
                    "id": row.get("id") or "",
                    "canonical_name": row.get("canonical_name") or "",
                    "type": row.get("type") or "未知",
                    "aliases": row.get("aliases"),
                    "description": None,
                    "updated_at": None,
                }
            )
        return entities

    async def get_article_relationships(self, article_id: str) -> list[dict[str, Any]]:
        """Get relationships between entities in an article.

        Args:
            article_id: Article UUID.

        Returns:
            List of relationship dicts.
        """
        query = self._query_builder.build_get_article_relationships_query()
        result = await self._pool.execute_query(query, {"id": article_id})
        relationships = []
        for row in result:
            relationships.append(
                {
                    "source_id": row["source"],
                    "target_id": row["target"],
                    "relation_type": row["relation_type"] or "RELATED_TO",
                    "properties": {
                        "source_article_id": row.get("source_article_id"),
                        "created_at": (
                            row["created_at"].isoformat() if row.get("created_at") else None
                        ),
                    },
                }
            )
        return relationships

    async def get_related_articles(self, article_id: str) -> list[dict[str, Any]]:
        """Get related articles.

        Args:
            article_id: Article UUID.

        Returns:
            List of article dicts.
        """
        query = self._query_builder.build_get_related_articles_query()
        result = await self._pool.execute_query(query, {"id": article_id})
        articles = []
        for row in result:
            articles.append(
                {
                    "id": row.get("id") or "",
                    "title": row.get("title") or "",
                    "category": row.get("category"),
                    "publish_time": (
                        row["publish_time"].isoformat() if row.get("publish_time") else None
                    ),
                    "score": row.get("score"),
                }
            )
        return articles

    # ── Relation Type Operations ────────────────────────────────────────

    async def get_relation_types(self, entity_name: str, entity_type: str) -> list[dict[str, Any]]:
        """Get all relation types for an entity.

        Args:
            entity_name: Entity canonical name.
            entity_type: Entity type.

        Returns:
            List of relation type summaries.
        """
        query = self._query_builder.build_get_relation_types_query()
        result = await self._pool.execute_query(query, {"name": entity_name, "type": entity_type})
        return [
            {
                "relation_type": r["relation_type"],
                "target_count": r["target_count"],
                "primary_direction": r["primary_direction"],
            }
            for r in result
        ]

    async def find_by_relation_types(
        self,
        entity_name: str,
        entity_type: str,
        relation_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find related entities by relation types.

        Args:
            entity_name: Entity canonical name.
            entity_type: Entity type.
            relation_types: Optional list of relation types to filter.
            limit: Maximum number of results.

        Returns:
            List of related entity dicts.
        """
        query = self._query_builder.build_find_by_relation_types_query(relation_types)
        result = await self._pool.execute_query(
            query, {"name": entity_name, "type": entity_type, "limit": limit}
        )
        return [
            {
                "relation_type": r["relation_type"],
                "direction": r["direction"],
                "target_name": r["target_name"],
                "target_type": r["target_type"],
                "target_description": r.get("target_description"),
                "weight": r.get("weight", 1.0),
            }
            for r in result
        ]
