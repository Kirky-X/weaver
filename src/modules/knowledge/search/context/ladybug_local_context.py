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
from modules.knowledge.search.context.builder import ContextBuilder, SearchContext

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class LadybugLocalContextBuilder(ContextBuilder):
    """Builds local context around query-relevant entities using LadybugDB.

    This builder focuses on the immediate neighborhood of relevant entities,
    making it suitable for specific, targeted queries.

    Implements: ContextBuilder
    """

    def __init__(
        self,
        graph_pool: GraphPool,
        article_repo: ArticleRepo | None = None,
        token_encoder: Any = None,
        default_max_tokens: int = 8000,
        max_entities: int = 20,
        max_relationships: int = 50,
        max_hops: int = 2,
    ) -> None:
        """Initialize local context builder.

        Args:
            graph_pool: GraphPool instance (LadybugPool).
            article_repo: Optional PostgreSQL ArticleRepo for fetching body content.
            token_encoder: Optional tokenizer.
            default_max_tokens: Default max tokens for context.
            max_entities: Maximum entities to include.
            max_relationships: Maximum relationships to include.
            max_hops: Maximum hops for neighborhood expansion.
        """
        super().__init__(token_encoder, default_max_tokens)
        self._pool = graph_pool
        self._article_repo = article_repo
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
        else:
            # Verify provided entity_names exist; fall back to fuzzy search if not
            entities_check = await self._get_entities_with_details(entity_names)
            if not entities_check:
                log.info(
                    "entity_names_not_found_fallback",
                    provided=entity_names,
                    query=query,
                )
                entity_names = await self._find_query_entities(query)

        if not entity_names:
            # Instead of returning early, add a message and continue to try finding related content
            context.add_content(
                name="Search Note",
                content=f"No direct entity matches found for '{query}'. Attempting to find related content...",
                priority=0,
            )
            # Try to find related articles based on query text
            articles = await self._get_related_articles_by_text(query)
            if articles:
                article_content = self._format_articles_section(articles)
                context.add_content(
                    name="Related Articles",
                    content=article_content,
                    priority=50,
                    metadata={"article_count": len(articles)},
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
        """Find entities mentioned in the query.

        Uses a two-step approach:
        1. Exact match on canonical_name and aliases
        2. Fuzzy match using CONTAINS if no exact matches
        """
        # Step 1: Try exact match
        config = EntitySearchConfig(query=query.lower(), limit=self._max_entities)
        cypher = self._query_builder.build_entity_search_query(config)

        try:
            results = await self._pool.execute_query(
                cypher, {"query": query.lower(), "limit": self._max_entities}
            )
            exact_matches = [r["name"] for r in results if r.get("name")]
            if exact_matches:
                log.info(
                    "entities_found_exact", count=len(exact_matches), entities=exact_matches[:5]
                )
                return exact_matches
        except Exception as exc:
            log.warning("find_query_entities_exact_failed", error=str(exc))

        # Step 2: Try fuzzy match using CONTAINS
        # LadybugDB: simple query without complex OR/EXISTS
        limit = self._max_entities
        fuzzy_cypher = f"""
        MATCH (e:Entity)
        WHERE LOWER(e.canonical_name) CONTAINS LOWER($query)
        RETURN e.canonical_name AS name
        LIMIT {limit}
        """

        try:
            results = await self._pool.execute_query(fuzzy_cypher, {"query": query.lower()})
            fuzzy_matches = [r["name"] for r in results if r.get("name")]
            if fuzzy_matches:
                log.info(
                    "entities_found_fuzzy", count=len(fuzzy_matches), entities=fuzzy_matches[:5]
                )
                return fuzzy_matches
        except Exception as exc:
            log.warning("find_query_entities_fuzzy_failed", error=str(exc))

        log.info("no_entities_found", query=query)
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

        params = {"names": entity_names, "limit": self._max_relationships}
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
        """Get articles mentioning the query entities.

        Enriches articles with body excerpts from PostgreSQL when available.
        """
        if not entity_names:
            return []

        cypher = self._query_builder.build_articles_by_entities_query(entity_names, limit)

        try:
            results = await self._pool.execute_query(
                cypher, {"names": entity_names, "limit": limit}
            )
            articles = [dict(r) for r in results]

            # Fetch body content from PostgreSQL
            pg_ids = [a.get("pg_id") or a.get("id") for a in articles]
            pg_ids = [str(pid) for pid in pg_ids if pid]
            bodies = await self._fetch_article_bodies(pg_ids)

            for article in articles:
                pg_id = str(article.get("pg_id") or article.get("id") or "")
                if pg_id and pg_id in bodies:
                    article["body_excerpt"] = self._extract_key_excerpt(
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
        It searches for articles that mention the query in title.
        LadybugDB: Article node may not have summary/url properties, use title only.
        """
        cypher = f"""
        MATCH (a:Article)
        WHERE LOWER(a.title) CONTAINS LOWER($query)
        RETURN a.title AS title
        LIMIT {limit}
        """

        try:
            results = await self._pool.execute_query(cypher, {"query": query.lower()})
            articles = [dict(r) for r in results]
            if articles:
                log.info("articles_found_by_text", count=len(articles), query=query)
            return articles
        except Exception as exc:
            log.warning("get_related_articles_by_text_failed", error=str(exc))
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
        """Format articles section with body excerpt."""
        lines = []
        for article in articles:
            title = article.get("title", "Unknown")
            summary = article.get("summary", "")
            body_excerpt = article.get("body_excerpt", "")

            lines.append(f"- {title}")
            if summary:
                truncated = self.truncate_content(summary, 200)
                lines.append(f"  概要: {truncated}")
            if body_excerpt:
                lines.append(f"  原文片段: {body_excerpt}")
        return "\n".join(lines)

    async def _fetch_article_bodies(
        self,
        pg_ids: list[str],
    ) -> dict[str, str]:
        """Fetch article body content from PostgreSQL by pg_ids.

        Args:
            pg_ids: List of PostgreSQL article IDs.

        Returns:
            Dict mapping pg_id to body content.
        """
        if not self._article_repo or not pg_ids:
            return {}

        bodies: dict[str, str] = {}
        for pg_id in pg_ids[:5]:
            try:
                article = await self._article_repo.get(pg_id)
                if article and article.body:
                    bodies[str(pg_id)] = article.body
            except Exception as exc:
                log.warning("fetch_body_failed", pg_id=pg_id, error=str(exc))
        return bodies

    def _extract_key_excerpt(
        self,
        body: str,
        entity_names: list[str],
        max_tokens: int = 300,
    ) -> str:
        """Extract key excerpt from article body.

        Extracts sentences containing entity mentions, falling back to
        head/tail truncation when no matches found.

        Args:
            body: Full article body text.
            entity_names: Entity names to match in sentences.
            max_tokens: Maximum tokens for excerpt.

        Returns:
            Truncated excerpt with entity-relevant content prioritized.
        """
        # Split into sentences
        import re

        sentences = re.split(r"(?<=[。！？.!?\n])", body)
        matched: list[str] = []
        others: list[str] = []

        for s in sentences:
            s = s.strip()
            if not s:
                continue
            lower_s = s.lower()
            if any(n.lower() in lower_s for n in entity_names):
                matched.append(s)
            else:
                others.append(s)

        # Prefer entity-matched sentences, fill with head sentences
        selected = matched[:8]
        if len(selected) < 4:
            selected.extend(others[: 4 - len(selected)])

        excerpt = "".join(selected)
        return self.truncate_content(excerpt, max_tokens)
