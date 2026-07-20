# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Neo4j local context builder for entity-based neighborhood search.

Builds context by:
1. Finding relevant entities from the query
2. Expanding to neighboring entities and relationships
3. Including related text units and articles
"""

from __future__ import annotations

from typing import Any

from core.db.safe_query import validate_edge_type
from core.observability import get_logger
from core.utils.article_enrichment import enrich_articles_with_titles
from modules.knowledge.graph.relation_type_normalizer import RelationTypeNormalizer
from modules.knowledge.search.context.base_local_context import BaseLocalContextBuilder

log = get_logger(__name__)


class LocalContextBuilder(BaseLocalContextBuilder):
    """Builds local context around query-relevant entities using Neo4j.

    This builder focuses on the immediate neighborhood of relevant entities,
    making it suitable for specific, targeted queries.

    Neo4j-specific features:
    - Alias search in entity matching
    - Typed relationship queries with RelationTypeNormalizer
    - MENTIONS edges for article-entity linking
    - Direction indicators in relationship display

    Cross-database divergence (intentional, see design.md §H1):
    This class does NOT override ``_handle_no_entities`` and uses the base
    behavior (relational DB text search, matching title + body) directly.
    LadybugDB ``LadybugLocalContextBuilder`` overrides it to add a graph
    Article node search path (title-only match) before the relational
    fallback. The two backends are NOT semantically equivalent in the
    no-entities path — accepted trade-off, see H1 in
    ``specmark/changes/db-consistency-verify/design.md``.

    Implements: ContextBuilder (via BaseLocalContextBuilder)
    """

    def _include_relationship_direction(self) -> bool:
        """Neo4j includes direction indicators in relationship section."""
        return True

    async def _find_query_entities(self, query: str) -> list[str]:
        """Find entities mentioned in the query using alias search."""
        query_lower = query.lower()

        cypher = """
        MATCH (e:Entity)
        WHERE toLower(e.canonical_name) CONTAINS $query
           OR any(alias IN e.aliases WHERE toLower(alias) CONTAINS $query)
        RETURN e.canonical_name AS name
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"query": query_lower, "limit": self._max_entities},
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

        cypher = """
        MATCH (e:Entity)
        WHERE e.canonical_name IN $names
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description,
               e.aliases AS aliases
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"names": entity_names, "limit": self._max_entities},
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

        rel_clause = self._build_rel_match_clause(relation_types)

        cypher = f"""
        MATCH (e:Entity)-{rel_clause}(related:Entity)
        WHERE e.canonical_name IN $names
        RETURN DISTINCT related.canonical_name AS canonical_name,
               related.type AS type,
               count(e) AS connection_count
        ORDER BY connection_count DESC
        LIMIT $limit
        """

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

        if relation_types:
            for rt in relation_types:
                validate_edge_type(rt)

            queries = []
            for rt_name_en in relation_types:
                is_symmetric = self.is_known_symmetric(rt_name_en)
                pattern = RelationTypeNormalizer.get_cypher_pattern(
                    rt_name_en,
                    is_symmetric,
                )
                queries.append(f"""
                    MATCH (e1:Entity){pattern}(e2:Entity)
                    WHERE e1.canonical_name IN $names OR e2.canonical_name IN $names
                    RETURN e1.canonical_name AS source_name,
                           e2.canonical_name AS target_name,
                           '{rt_name_en}' AS relation_type,
                           true AS is_symmetric
                """)
            cypher = "\n UNION ALL \n".join(queries) + "\n LIMIT $limit"
        else:
            cypher = """
            MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
            WHERE e1.canonical_name IN $names OR e2.canonical_name IN $names
            RETURN e1.canonical_name AS source_name,
                   e2.canonical_name AS target_name,
                   r.relation_type AS relation_type,
                   false AS is_symmetric
            ORDER BY coalesce(r.weight, 1.0) DESC
            LIMIT $limit
            """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"names": entity_names, "limit": self._max_relationships},
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_relationships_failed", error=str(exc))
            return []

    async def _get_related_articles(
        self,
        entity_names: list[str],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get articles mentioning the query entities via MENTIONS edges.

        After the Article node slim-down (design.md §D2), the graph query
        returns only ``a.pg_id AS id``. Title / publish_time are
        batch-fetched from PostgreSQL via ``enrich_articles_with_titles``
        when ``self._article_repo`` is available; article bodies are
        fetched via ``fetch_article_bodies`` for excerpt extraction.
        """
        if not entity_names:
            return []

        cypher = """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE e.canonical_name IN $names
        RETURN DISTINCT a.pg_id AS id
        ORDER BY a.pg_id
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"names": entity_names, "limit": limit},
            )
            articles = [dict(r) for r in results]

            # Batch-enrich titles from PG (slim-down); returns the
            # lowercase pg_ids list so we can reuse it for body fetching.
            pg_ids = await enrich_articles_with_titles(
                articles,
                article_repo=self._article_repo,
                id_fields=["id"],
            )

            bodies = await self.fetch_article_bodies(pg_ids)

            for article in articles:
                pg_id = str(article.get("id", "")).lower()
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

    def _build_rel_match_clause(
        self,
        relation_types: list[str] | None = None,
    ) -> str:
        """Build a Cypher relationship match clause.

        When relation_types is specified, generates a pattern that matches
        any of the specified types.

        Args:
            relation_types: Optional list of relation type name_en values.

        Returns:
            Cypher relationship match clause string.
        """
        if not relation_types:
            return f"-[:RELATED_TO*1..{self._max_hops}]-"

        for rt in relation_types:
            validate_edge_type(rt)

        return f"-[:{'|'.join(relation_types)}*1..{self._max_hops}]-"
