# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Local context builder for entity-based neighborhood search.

Builds context by:
1. Finding relevant entities from the query
2. Expanding to neighboring entities and relationships
3. Including related text units and articles
"""

from __future__ import annotations

from typing import Any

from core.db.neo4j import Neo4jPool
from core.db.safe_query import validate_edge_type
from core.observability.logging import get_logger
from modules.knowledge.graph.relation_type_normalizer import RelationTypeNormalizer
from modules.knowledge.search.context.builder import ContextBuilder, SearchContext

log = get_logger("search.local_context")


class LocalContextBuilder(ContextBuilder):
    """Builds local context around query-relevant entities.

    This builder focuses on the immediate neighborhood of relevant entities,
    making it suitable for specific, targeted queries.

    Context structure:
    1. Query entities: Entities directly matching the query
    2. Related entities: Entities connected to query entities
    3. Relationships: Connections between entities
    4. Source texts: Relevant text units or article excerpts
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        token_encoder: Any = None,
        default_max_tokens: int = 8000,
        max_entities: int = 20,
        max_relationships: int = 50,
        max_hops: int = 2,
    ) -> None:
        """Initialize local context builder.

        Args:
            neo4j_pool: Neo4j connection pool.
            token_encoder: Optional tokenizer.
            default_max_tokens: Default max tokens for context.
            max_entities: Maximum entities to include.
            max_relationships: Maximum relationships to include.
            max_hops: Maximum hops for neighborhood expansion.
        """
        super().__init__(token_encoder, default_max_tokens)
        self._pool = neo4j_pool
        self._max_entities = max_entities
        self._max_relationships = max_relationships
        self._max_hops = max_hops

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
            relation_types: Optional list of relation type name_en values to filter by.
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

        # Build the relationship pattern clause
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
            # Validate all relation types to prevent Cypher injection
            for rt in relation_types:
                validate_edge_type(rt)

            # Build UNION of queries for each relation type to handle direction
            queries = []
            for rt_name_en in relation_types:
                # Default to asymmetric for typed relations unless known symmetric
                is_symmetric = self._is_known_symmetric(rt_name_en)
                pattern = RelationTypeNormalizer.get_cypher_pattern(
                    rt_name_en,
                    is_symmetric,
                )
                if is_symmetric:
                    queries.append(f"""
                        MATCH (e1:Entity){pattern}(e2:Entity)
                        WHERE e1.canonical_name IN $names OR e2.canonical_name IN $names
                        RETURN e1.canonical_name AS source_name,
                               e2.canonical_name AS target_name,
                               '{rt_name_en}' AS relation_type,
                               true AS is_symmetric
                    """)
                else:
                    queries.append(f"""
                        MATCH (e1:Entity){pattern}(e2:Entity)
                        WHERE e1.canonical_name IN $names OR e2.canonical_name IN $names
                        RETURN e1.canonical_name AS source_name,
                               e2.canonical_name AS target_name,
                               '{rt_name_en}' AS relation_type,
                               false AS is_symmetric
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
        """Get articles mentioning the query entities."""
        if not entity_names:
            return []

        cypher = """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE e.canonical_name IN $names
        RETURN DISTINCT a.pg_id AS id,
               a.title AS title,
               a.summary AS summary,
               a.publish_time AS publish_time
        ORDER BY a.publish_time DESC
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"names": entity_names, "limit": limit},
            )
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
        """Format relationships section with direction info."""
        lines = []
        for rel in relationships:
            lines.append(self._format_relation_with_direction(rel))
        return "\n".join(lines)

    @staticmethod
    def _is_known_symmetric(name_en: str) -> bool:
        """Check if a relation type is known to be symmetric.

        This uses a hardcoded set of well-known symmetric types.
        For a complete picture, the RelationTypeNormalizer database should
        be consulted, but this avoids requiring a DB connection in the
        context builder for simple pattern generation.
        """
        symmetric_types = {
            "PARTNERS_WITH",
            "COLLABORATES_WITH",
            "RELATED_TO",
            "COOPERATES_WITH",
            "ALLIED_WITH",
            "ASSOCIATED_WITH",
        }
        return name_en in symmetric_types

    def _build_rel_match_clause(
        self,
        relation_types: list[str] | None = None,
    ) -> str:
        """Build a Cypher relationship match clause.

        When relation_types is specified, generates a pattern that matches
        any of the specified types. Uses directional patterns for asymmetric
        relations and undirectional for symmetric ones, combined via '|'.

        Args:
            relation_types: Optional list of relation type name_en values.

        Returns:
            Cypher relationship match clause string.

        Raises:
            ValueError: If any relation type is invalid.
        """
        if not relation_types:
            return f"-[:RELATED_TO*1..{self._max_hops}]-"

        # Validate all relation types to prevent Cypher injection
        for rt in relation_types:
            validate_edge_type(rt)

        # For multiple typed relations, use alternation with proper directions
        # Since Cypher alternation requires same directionality, we fall back
        # to undirected matching for mixed types
        return f"-[:{'|'.join(relation_types)}*1..{self._max_hops}]-"

    @staticmethod
    def _format_relation_with_direction(rel: dict[str, Any]) -> str:
        """Format a relationship with direction indicator.

        Args:
            rel: Relationship dict with source_name, target_name,
                 relation_type, and optional is_symmetric.

        Returns:
            Formatted string like:
                - 华为 --[合作(双向)]--> 比亚迪
                - 工信部 --[监管(单向)]--> 华为
        """
        source = rel.get("source_name", "Unknown")
        target = rel.get("target_name", "Unknown")
        rel_type = rel.get("relation_type", "RELATED_TO")
        is_symmetric = rel.get("is_symmetric", False)

        display_name = rel_type
        direction = "双向" if is_symmetric else "单向"

        return f"- {source} --[{display_name}({direction})]--> {target}"

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
