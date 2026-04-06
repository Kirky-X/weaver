# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB local context builder for entity-based neighborhood search.

Builds context by:
1. Finding relevant entities from the query
2. Expanding to neighboring entities and relationships
3. Including related text units and articles

Uses GraphQueryBuilder for database-agnostic queries.
"""

from __future__ import annotations

from typing import Any

from core.db.graph_query import (
    EntitySearchConfig,
    GraphQueryBuilder,
    RelatedEntitiesConfig,
    create_graph_query_builder,
)
from core.observability.logging import get_logger
from core.protocols import GraphPool
from modules.knowledge.search.context.builder import ContextBuilder, SearchContext

log = get_logger("search.ladybug_local_context")


class LadybugLocalContextBuilder(ContextBuilder):
    """Builds local context around query-relevant entities using LadybugDB.

    This builder focuses on the immediate neighborhood of relevant entities,
    making it suitable for specific, targeted queries.

    Implements: ContextBuilder
    """

    def __init__(
        self,
        graph_pool: GraphPool,
        token_encoder: Any = None,
        default_max_tokens: int = 8000,
        max_entities: int = 20,
        max_relationships: int = 50,
        max_hops: int = 2,
    ) -> None:
        """Initialize local context builder.

        Args:
            graph_pool: GraphPool instance (LadybugPool).
            token_encoder: Optional tokenizer.
            default_max_tokens: Default max tokens for context.
            max_entities: Maximum entities to include.
            max_relationships: Maximum relationships to include.
            max_hops: Maximum hops for neighborhood expansion.
        """
        super().__init__(token_encoder, default_max_tokens)
        self._pool = graph_pool
        self._max_entities = max_entities
        self._max_relationships = max_relationships
        self._max_hops = max_hops
        self._query_builder: GraphQueryBuilder = create_graph_query_builder("ladybug")

    async def build(
        self,
        query: str,
        max_tokens: int | None = None,
        entity_names: list[str] | None = None,
        relation_types: list[str] | None = None,
        **kwargs: Any,
    ) -> SearchContext:
        """Build local context for a query.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for context.
            entity_names: Optional list of entity names to focus on.
            relation_types: Optional list of relation types to filter by.
            **kwargs: Additional parameters.

        Returns:
            SearchContext with local entity neighborhood.
        """
        context = self.create_context(query, max_tokens)

        if entity_names is None:
            entity_names = await self._find_query_entities(query)

        if not entity_names:
            context.add_content(
                name="No Entities Found",
                content="No relevant entities found for the query.",
                priority=0,
            )
            return context

        entities = await self._get_entities_with_details(entity_names)
        if entities:
            entity_content = self._format_entities_section(entities)
            context.add_content(
                name="Relevant Entities",
                content=entity_content,
                priority=100,
                metadata={"entity_count": len(entities)},
            )

        related_entities = await self._get_related_entities(
            entity_names,
            relation_types=relation_types,
        )
        if related_entities:
            related_content = self._format_entities_section(
                related_entities, include_description=False
            )
            context.add_content(
                name="Related Entities",
                content=related_content,
                priority=80,
                metadata={"related_count": len(related_entities)},
            )

        relationships = await self._get_relationships(
            entity_names,
            relation_types=relation_types,
        )
        if relationships:
            rel_content = self._format_relationships_section(relationships)
            context.add_content(
                name="Relationships",
                content=rel_content,
                priority=90,
                metadata={"relationship_count": len(relationships)},
            )

        articles = await self._get_related_articles(entity_names)
        if articles:
            article_content = self._format_articles_section(articles)
            context.add_content(
                name="Source Articles",
                content=article_content,
                priority=70,
                metadata={"article_count": len(articles)},
            )

        context.metadata["total_entities"] = len(entities) + len(related_entities)
        context.metadata["total_relationships"] = len(relationships)
        if relation_types:
            context.metadata["filtered_relation_types"] = relation_types

        return context

    async def _find_query_entities(self, query: str) -> list[str]:
        """Find entities mentioned in the query."""
        config = EntitySearchConfig(query=query.lower(), limit=self._max_entities)
        cypher = self._query_builder.build_entity_search_query(config)

        try:
            results = await self._pool.execute_query(
                cypher, {"query": query.lower(), "limit": self._max_entities}
            )
            return [r["name"] for r in results if r.get("name")]
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
            results = await self._pool.execute_query(cypher)
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

        try:
            results = await self._pool.execute_query(cypher)
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
            results = await self._pool.execute_query(cypher)
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_related_articles_failed", error=str(exc))
            return []

    def _format_entities_section(
        self,
        entities: list[dict[str, Any]],
        include_description: bool = True,
    ) -> str:
        """Format entities section."""
        lines = []
        for entity in entities:
            lines.append(self.format_entity(entity, include_description))
        return "\n".join(lines)

    def _format_relationships_section(
        self,
        relationships: list[dict[str, Any]],
    ) -> str:
        """Format relationships section."""
        lines = []
        for rel in relationships:
            source = rel.get("source_name", "Unknown")
            target = rel.get("target_name", "Unknown")
            rel_type = rel.get("relation_type", "RELATED_TO")
            lines.append(f"- {source} --[{rel_type}]--> {target}")
        return "\n".join(lines)

    def _format_articles_section(
        self,
        articles: list[dict[str, Any]],
    ) -> str:
        """Format articles section."""
        lines = []
        for article in articles:
            title = article.get("title", "Unknown")
            summary = article.get("summary", "")
            lines.append(f"- {title}")
            if summary:
                truncated = self.truncate_content(summary, 100)
                lines.append(f"  {truncated}")
        return "\n".join(lines)
