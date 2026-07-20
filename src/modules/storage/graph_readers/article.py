# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Article reader for graph repository.

Handles article-centric read operations: article node lookup, entities
mentioned in an article, intra-article entity relationships, and
related-article discovery.

After the Article node slim-down (design.md §D2), graph Article nodes only
store ``pg_id`` (and ``created_at`` on Neo4j). Business fields (title /
category / publish_time / score) are batch-fetched from PostgreSQL via
``ArticleRepository.fetch_titles_by_pg_ids`` when ``article_repo`` is
injected; otherwise the reader degrades to returning ``{id: pg_id}`` dicts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from core.utils.time_utils import convert_timestamp
from modules.storage.graph_readers.base import GraphReaderBase

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class GraphArticleReader(GraphReaderBase):
    """Reader for article-centric graph operations.

    Provides read access to article nodes and their associated entities,
    relationships, and related articles. Query execution with fallback
    is delegated to the injected ``execute_fn`` callable.

    After the Article node slim-down, graph queries return only ``pg_id``.
    When ``article_repo`` is provided, this reader batch-fetches
    ``title``/``category``/``publish_time``/``score`` from PostgreSQL and
    merges them into the result dicts. When ``article_repo`` is ``None``
    (degraded mode, e.g., during tests or when the relational DB is
    unavailable), only ``{id: pg_id}`` is returned.

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        execute_fn: Callable that runs a query with fallback support.
        article_repo: Optional ``ArticleRepository``-compatible instance
            used to batch-fetch business fields by ``pg_id``. ``None``
            triggers degraded mode (pg_id only).
    """

    def __init__(
        self,
        pool: Any,
        query_builder: Any,
        execute_fn: Any,
        article_repo: Any = None,
    ) -> None:
        super().__init__(pool, query_builder, execute_fn)
        self._article_repo = article_repo

    async def _fetch_titles(self, pg_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Batch-fetch article metadata from PostgreSQL by pg_ids.

        Returns ``{}`` when ``article_repo`` is None (degraded mode) or
        when the lookup fails — callers must handle the empty case by
        emitting ``{id: pg_id}`` dicts only.

        Args:
            pg_ids: List of article UUID strings (lowercased on lookup).

        Returns:
            Mapping of ``pg_id`` (lowercase) -> metadata dict with keys
            ``title``, ``category``, ``publish_time``, ``score``.
        """
        if not self._article_repo or not pg_ids:
            return {}
        try:
            return await self._article_repo.fetch_titles_by_pg_ids(pg_ids)
        except Exception as exc:
            log.warning(
                "graph_article_reader_fetch_titles_failed",
                error=str(exc),
                pg_id_count=len(pg_ids),
            )
            return {}

    async def get_entity_articles(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get articles mentioning an entity.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of articles.

        Returns:
            List of article dicts. When ``article_repo`` is available,
            each dict contains ``id``/``title``/``category``/
            ``publish_time``/``score``; otherwise only ``{id: pg_id}``.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_entity_articles_query(),
            {"name": canonical_name, "limit": limit},
        )
        pg_ids = [str(row.get("id")) for row in result if row.get("id")]
        titles = await self._fetch_titles(pg_ids)
        articles = []
        for row in result:
            pg_id = str(row.get("id") or "")
            meta = titles.get(pg_id.lower()) if pg_id else None
            publish_time = convert_timestamp(meta.get("publish_time") if meta else None)
            articles.append(
                {
                    "id": pg_id,
                    "title": (meta or {}).get("title", ""),
                    "category": (meta or {}).get("category"),
                    "publish_time": publish_time,
                    "score": (meta or {}).get("score"),
                }
            )
        return articles

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        """Get article node from graph.

        Args:
            article_id: Article UUID (pg_id).

        Returns:
            Article dict or None if not found. When ``article_repo`` is
            available, the dict contains ``id``/``title``/``category``/
            ``publish_time``/``score``; otherwise only ``{id: pg_id}``.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_article_graph_query(),
            {"id": article_id},
        )
        if not result:
            return None
        record = result[0]
        pg_id = str(record.get("id") or "")
        titles = await self._fetch_titles([pg_id]) if pg_id else {}
        meta = titles.get(pg_id.lower()) if pg_id else None
        publish_time = convert_timestamp(meta.get("publish_time") if meta else None)
        return {
            "id": pg_id,
            "title": (meta or {}).get("title", ""),
            "category": (meta or {}).get("category"),
            "publish_time": publish_time,
            "score": (meta or {}).get("score"),
        }

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
            List of article dicts. When ``article_repo`` is available,
            each dict contains ``id``/``title``/``category``/
            ``publish_time``/``score``; otherwise only ``{id: pg_id}``.
            ``shared_entities`` count is preserved when present (Neo4j).
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_related_articles_query(),
            {"id": article_id},
        )
        pg_ids = [str(row.get("id")) for row in result if row.get("id")]
        titles = await self._fetch_titles(pg_ids)
        articles = []
        for row in result:
            pg_id = str(row.get("id") or "")
            meta = titles.get(pg_id.lower()) if pg_id else None
            publish_time = convert_timestamp(meta.get("publish_time") if meta else None)
            article = {
                "id": pg_id,
                "title": (meta or {}).get("title", ""),
                "category": (meta or {}).get("category"),
                "publish_time": publish_time,
                "score": (meta or {}).get("score"),
            }
            if "shared_entities" in row:
                article["shared_entities"] = row["shared_entities"]
            articles.append(article)
        return articles
