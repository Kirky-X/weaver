# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Article reader for graph repository.

Handles article-centric read operations: article node lookup, entities
mentioned in an article, intra-article entity relationships, and
related-article discovery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.utils.time_utils import convert_timestamp
from modules.storage.graph_readers.base import GraphReaderBase

if TYPE_CHECKING:
    pass


class GraphArticleReader(GraphReaderBase):
    """Reader for article-centric graph operations.

    Provides read access to article nodes and their associated entities,
    relationships, and related articles. Query execution with fallback
    is delegated to the injected ``execute_fn`` callable.

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        execute_fn: Callable that runs a query with fallback support.
    """

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
        result = await self._execute_fn(
            lambda qb: qb.build_get_entity_articles_query(),
            {"name": canonical_name, "limit": limit},
        )
        articles = []
        for row in result:
            publish_time = convert_timestamp(row.get("publish_time"))
            articles.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "category": row.get("category"),
                    "publish_time": publish_time,
                    "score": row.get("score"),
                }
            )
        return articles

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        """Get article node from graph.

        Args:
            article_id: Article UUID (pg_id).

        Returns:
            Article dict or None if not found.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_article_graph_query(),
            {"id": article_id},
        )
        if result:
            record = result[0]
            publish_time = convert_timestamp(record.get("publish_time"))

            return {
                "id": record.get("id") or "",
                "title": record.get("title") or "",
                "category": record.get("category"),
                "publish_time": publish_time,
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
        result = await self._execute_fn(
            lambda qb: qb.build_get_article_entities_query(),
            {"id": article_id},
        )
        entities = []
        for row in result:
            updated_at = convert_timestamp(row.get("updated_at"))
            created_at = convert_timestamp(row.get("created_at"))

            entities.append(
                {
                    "id": row.get("id") or "",
                    "canonical_name": row.get("canonical_name") or "",
                    "type": row.get("type") or "未知",
                    "aliases": row.get("aliases"),
                    "description": row.get("description"),
                    "created_at": created_at,
                    "updated_at": updated_at,
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
        result = await self._execute_fn(
            lambda qb: qb.build_get_article_relationships_query(),
            {"id": article_id},
        )
        relationships = []
        for row in result:
            created_at = convert_timestamp(row.get("created_at"))
            relationships.append(
                {
                    "source_id": row["source"],
                    "target_id": row["target"],
                    "relation_type": row["relation_type"] or "RELATED_TO",
                    "properties": {
                        "description": row.get("description"),
                        "weight": row.get("weight", 1.0),
                        "created_at": created_at,
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
        result = await self._execute_fn(
            lambda qb: qb.build_get_related_articles_query(),
            {"id": article_id},
        )
        articles = []
        for row in result:
            publish_time = convert_timestamp(row.get("publish_time"))
            articles.append(
                {
                    "id": row.get("id") or "",
                    "title": row.get("title") or "",
                    "category": row.get("category"),
                    "publish_time": publish_time,
                    "score": row.get("score"),
                }
            )
        return articles
