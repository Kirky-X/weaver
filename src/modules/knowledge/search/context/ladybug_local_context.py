# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB local context builder for entity-based neighborhood search.

Builds context by:
1. Finding relevant entities from the query
2. Expanding to neighboring entities and relationships
3. Including related text units and articles

Uses GraphQueryBuilder for database-agnostic queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.db.graph_query import (
    EntitySearchConfig,
    GraphQueryBuilder,
    RelatedEntitiesConfig,
    create_graph_query_builder,
)
from core.observability import get_logger
from core.protocols import GraphPool
from modules.knowledge.search.context.base_local_context import BaseLocalContextBuilder

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class LadybugLocalContextBuilder(BaseLocalContextBuilder):
    """Builds local context around query-relevant entities using LadybugDB.

    This builder focuses on the immediate neighborhood of relevant entities,
    making it suitable for specific, targeted queries.

    LadybugDB-specific features:
    - Fuzzy entity search via GraphQueryBuilder
    - Entity name validation with fallback
    - Text-based article search fallback
    - Uses r.edge_type instead of type(r)

    Implements: ContextBuilder (via BaseLocalContextBuilder)
    """

    def __init__(
        self,
        graph_pool: GraphPool,
        article_repo: Any = None,
        token_encoder: Any = None,
        default_max_tokens: int = 8000,
        max_entities: int = 20,
        max_relationships: int = 50,
        max_hops: int = 2,
    ) -> None:
        super().__init__(
            graph_pool=graph_pool,
            article_repo=article_repo,
            token_encoder=token_encoder,
            default_max_tokens=default_max_tokens,
            max_entities=max_entities,
            max_relationships=max_relationships,
            max_hops=max_hops,
        )
        self._query_builder: GraphQueryBuilder = create_graph_query_builder("ladybug")

    def _should_validate_entity_names(self) -> bool:
        """LadybugDB validates entity names because data model may differ."""
        return True

    async def _handle_no_entities(
        self,
        context: Any,
        query: str,
    ) -> Any:
        """Handle no entities by trying text-based article search."""
        context.add_content(
            name="Search Note",
            content=f"No direct entity matches found for '{query}'. Attempting to find related content...",
            priority=0,
        )
        articles = await self._get_related_articles_by_text(query)
        if articles:
            article_content = self.format_articles_section(articles)
            context.add_content(
                name="Related Articles",
                content=article_content,
                priority=50,
                metadata={"article_count": len(articles)},
            )
        return context

    async def _find_query_entities(self, query: str) -> list[str]:
        """Find entities mentioned in the query using GraphQueryBuilder."""
        config = EntitySearchConfig(query=query.lower(), limit=self._max_entities)
        cypher = self._query_builder.build_entity_search_query(config)

        try:
            results = await self._pool.execute_query(
                cypher, {"query": query.lower(), "limit": self._max_entities}
            )
            matches = [r["name"] for r in results if r.get("name")]
            if matches:
                log.info("entities_found", count=len(matches), entities=matches[:5])
                return matches
        except Exception as exc:
            log.warning("find_query_entities_failed", error=str(exc))

        return []

    async def _get_entities_with_details(
        self,
        entity_names: list[str],
    ) -> list[dict[str, Any]]:
        """Get detailed information for entities."""
        if not entity_names:
            return []

        cypher = self._query_builder.build_entities_by_names_query(entity_names, self._max_entities)

        try:
            results = await self._pool.execute_query(
                cypher, {"names": entity_names, "limit": self._max_entities}
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_entities_failed", error=str(exc))
            return []

    async def _get_related_entities(
        self,
        entity_names: list[str],
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get entities related to the query entities."""
        if not entity_names:
            return []

        config = RelatedEntitiesConfig(
            entity_names=tuple(entity_names),
            relation_types=tuple(relation_types) if relation_types else (),
            max_hops=self._max_hops,
            limit=self._max_entities,
        )

        cypher = self._query_builder.build_related_entities_query(config)

        try:
            results = await self._pool.execute_query(
                cypher,
                {"names": entity_names, "limit": self._max_entities},
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_related_entities_failed", error=str(exc))
            return []

    async def _get_relationships(
        self,
        entity_names: list[str],
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get relationships involving the query entities."""
        if not entity_names:
            return []

        cypher = self._query_builder.build_relationships_query(
            entity_names,
            relation_types,
            self._max_relationships,
        )

        params: dict[str, Any] = {"names": entity_names, "limit": self._max_relationships}
        if relation_types:
            params["relation_types"] = relation_types

        try:
            results = await self._pool.execute_query(cypher, params)
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_relationships_failed", error=str(exc))
            return []

    async def _get_related_articles(
        self,
        entity_names: list[str],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles mentioning the query entities."""
        if not entity_names:
            return []

        cypher = self._query_builder.build_articles_by_entities_query(entity_names, limit)

        try:
            results = await self._pool.execute_query(
                cypher, {"names": entity_names, "limit": limit}
            )
            articles = [dict(r) for r in results]

            pg_ids = [a.get("pg_id") or a.get("id") for a in articles]
            pg_ids = [str(pid) for pid in pg_ids if pid]
            bodies = await self.fetch_article_bodies(pg_ids)

            for article in articles:
                pg_id = str(article.get("pg_id") or article.get("id") or "")
                if pg_id and pg_id in bodies:
                    article["body_excerpt"] = self.extract_key_excerpt(
                        bodies[pg_id],
                        entity_names,
                        max_tokens=300,
                    )

            return articles
        except Exception as exc:
            log.warning("get_related_articles_failed", error=str(exc))
            return []

    async def _get_related_articles_by_text(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles related to the query text.

        This is a fallback when no entities are found.
        Uses parameterized query via GraphQueryBuilder.
        """
        cypher = self._query_builder.build_articles_by_text_query(limit)

        try:
            results = await self._pool.execute_query(
                cypher, {"query": query.lower(), "limit": limit}
            )
            articles = [dict(r) for r in results]
            if articles:
                log.info("articles_found_by_text", count=len(articles), query=query)
            return articles
        except Exception as exc:
            log.warning("get_related_articles_by_text_failed", error=str(exc))
            return []
