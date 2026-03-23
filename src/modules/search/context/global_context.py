# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Global context builder for community-based search.

Builds context using community reports and hierarchical structure,
suitable for broad, exploratory queries that span multiple communities.
"""

from __future__ import annotations

from typing import Any

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger
from modules.search.context.builder import ContextBuilder, SearchContext

log = get_logger("search.global_context")


class GlobalContextBuilder(ContextBuilder):
    """Builds global context using community reports.

    This builder uses community-level aggregation to handle queries
    that require understanding of the overall graph structure.

    Context structure:
    1. Community summaries: High-level community descriptions
    2. Key entities: Important entities across communities
    3. Cross-community relationships: Connections between communities
    4. Relevant articles: Articles from relevant communities
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        token_encoder: Any = None,
        default_max_tokens: int = 12000,
        max_communities: int = 10,
        max_entities_per_community: int = 5,
    ) -> None:
        """Initialize global context builder.

        Args:
            neo4j_pool: Neo4j connection pool.
            token_encoder: Optional tokenizer.
            default_max_tokens: Default max tokens for context.
            max_communities: Maximum communities to include.
            max_entities_per_community: Max entities per community.
        """
        super().__init__(token_encoder, default_max_tokens)
        self._pool = neo4j_pool
        self._max_communities = max_communities
        self._max_entities_per_community = max_entities_per_community

    async def build(
        self,
        query: str,
        max_tokens: int | None = None,
        community_level: int = 0,
        **kwargs: Any,
    ) -> SearchContext:
        """Build global context for a query.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for context.
            community_level: Community hierarchy level (0 = leaf).
            **kwargs: Additional parameters.

        Returns:
            SearchContext with community-level information.
        """
        context = self.create_context(query, max_tokens)

        relevant_communities, used_fallback = await self._find_relevant_communities(
            query, community_level
        )

        if not relevant_communities:
            context.add_content(
                name="No Communities Found",
                content="No relevant communities found for the query.",
                priority=0,
            )
            context.metadata["total_communities"] = 0
            return context

        if relevant_communities:
            community_content = self._format_communities_section(relevant_communities)
            context.add_content(
                name="Community Summaries",
                content=community_content,
                priority=100,
                metadata={"community_count": len(relevant_communities)},
            )

        key_entities = await self._get_key_entities(relevant_communities)
        if key_entities:
            entity_content = self._format_entities_section(key_entities)
            context.add_content(
                name="Key Entities",
                content=entity_content,
                priority=90,
                metadata={"entity_count": len(key_entities)},
            )

        cross_community_rels = await self._get_cross_community_relationships(relevant_communities)
        if cross_community_rels:
            rel_content = self._format_cross_community_section(cross_community_rels)
            context.add_content(
                name="Cross-Community Connections",
                content=rel_content,
                priority=80,
                metadata={"connection_count": len(cross_community_rels)},
            )

        context.metadata["community_level"] = community_level
        context.metadata["total_communities"] = len(relevant_communities)
        if used_fallback:
            context.metadata["fallback_source"] = "entity_article"

        return context

    async def _find_entity_article_fallback(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        """Find entity-article aggregation as fallback when no Community nodes exist.

        Queries Article-Entity relationships directly, filters by query tokens
        against entity names and article titles/summaries, and returns ranked results.

        Args:
            query: The search query (used to extract filter tokens).

        Returns:
            List of dicts with id (prefixed "fallback:"), title, rank, entity_count.
        """
        tokens = [t.strip() for t in query.split() if t.strip()]
        if not tokens:
            return []

        cypher = """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE any(token IN tokens($tokens) WHERE
                 toLower(e.canonical_name) CONTAINS token
                 OR toLower(a.title) CONTAINS token
                 OR toLower(a.summary) CONTAINS token)
        RETURN e.canonical_name AS entity_name,
               e.type AS entity_type,
               e.description AS entity_description,
               a.id AS article_id,
               a.title AS article_title,
               a.summary AS article_summary,
               a.score AS article_score,
               size((e)-[:RELATED_TO]->()) AS entity_degree
        ORDER BY article_score DESC, entity_degree DESC
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"tokens": tokens, "limit": self._max_communities},
            )

            if not results:
                return []

            return [
                {
                    "id": f"fallback:{dict(r).get('article_id', '')}",
                    "title": (
                        f"{dict(r).get('entity_name', '')} — {dict(r).get('article_title', '')}"
                    ),
                    "summary": dict(r).get("entity_description", ""),
                    "rank": float(dict(r).get("article_score", 0.5)),
                    "entity_count": 1,
                }
                for r in results
            ]
        except Exception as exc:
            log.warning("entity_article_fallback_failed", error=str(exc))
            return []

    async def _find_relevant_communities(
        self,
        query: str,
        level: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Find communities relevant to the query.

        Returns:
            Tuple of (results list, used_fallback bool).
            used_fallback is True when entity-article aggregation was used
            instead of Community nodes.
        """
        query_lower = query.lower()

        cypher = """
        MATCH (c:Community)
        WHERE c.level = $level
          AND (toLower(c.title) CONTAINS $query
               OR toLower(c.summary) CONTAINS $query)
        RETURN c.id AS id,
               c.title AS title,
               c.summary AS summary,
               c.rank AS rank,
               c.entity_count AS entity_count
        ORDER BY c.rank DESC
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"level": level, "query": query_lower, "limit": self._max_communities},
            )

            if results:
                return [dict(r) for r in results], False
        except Exception as exc:
            log.debug("community_search_failed", error=str(exc))

        cypher_fallback = """
        MATCH (c:Community)
        WHERE c.level = $level
        RETURN c.id AS id,
               c.title AS title,
               c.summary AS summary,
               c.rank AS rank,
               c.entity_count AS entity_count
        ORDER BY c.rank DESC
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher_fallback,
                {"level": level, "limit": self._max_communities},
            )
            if results:
                return [dict(r) for r in results], False
        except Exception as exc:
            log.warning("community_fallback_failed", error=str(exc))

        # Fall back to entity-article aggregation when no Community nodes exist
        fallback_results = await self._find_entity_article_fallback(query)
        return fallback_results, True

    async def _get_key_entities(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get key entities from the communities."""
        if not communities:
            return []

        community_ids = [c.get("id") for c in communities if c.get("id")]

        if not community_ids:
            return []

        cypher = """
        MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)
        WHERE c.id IN $community_ids
        WITH e, count(c) AS community_count,
             size((e)-[:RELATED_TO]->()) AS degree
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description,
               degree,
               community_count
        ORDER BY community_count DESC, degree DESC
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {
                    "community_ids": community_ids,
                    "limit": self._max_entities_per_community * len(community_ids),
                },
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_key_entities_failed", error=str(exc))
            return []

    async def _get_cross_community_relationships(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get relationships that connect different communities."""
        if len(communities) < 2:
            return []

        community_ids = [c.get("id") for c in communities if c.get("id")]

        cypher = """
        MATCH (c1:Community)-[:HAS_ENTITY]->(e1:Entity)
              -[r:RELATED_TO]->(e2:Entity)<-[:HAS_ENTITY]-(c2:Community)
        WHERE c1.id IN $community_ids
          AND c2.id IN $community_ids
          AND c1.id <> c2.id
        RETURN DISTINCT
               c1.title AS source_community,
               c2.title AS target_community,
               e1.canonical_name AS source_entity,
               e2.canonical_name AS target_entity,
               r.relation_type AS relation_type
        LIMIT 50
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"community_ids": community_ids},
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_cross_community_rels_failed", error=str(exc))
            return []

    def _format_communities_section(
        self,
        communities: list[dict[str, Any]],
    ) -> str:
        """Format communities section."""
        lines = []
        for i, comm in enumerate(communities, 1):
            title = comm.get("title", f"Community {i}")
            summary = comm.get("summary", "")
            entity_count = comm.get("entity_count", 0)

            lines.append(f"### {title}")
            lines.append(f"Entities: {entity_count}")
            if summary:
                truncated = self.truncate_content(summary, 200)
                lines.append(f"Summary: {truncated}")
            lines.append("")

        return "\n".join(lines)

    def _format_entities_section(
        self,
        entities: list[dict[str, Any]],
    ) -> str:
        """Format entities section."""
        lines = []
        for entity in entities:
            lines.append(self.format_entity(entity))
        return "\n".join(lines)

    def _format_cross_community_section(
        self,
        connections: list[dict[str, Any]],
    ) -> str:
        """Format cross-community connections section."""
        lines = []
        for conn in connections:
            source_comm = conn.get("source_community", "Unknown")
            target_comm = conn.get("target_community", "Unknown")
            source_entity = conn.get("source_entity", "Unknown")
            target_entity = conn.get("target_entity", "Unknown")
            rel_type = conn.get("relation_type", "RELATED_TO")

            lines.append(
                f"- [{source_comm}] {source_entity} --[{rel_type}]--> {target_entity} [{target_comm}]"
            )

        return "\n".join(lines)

    async def build_map_reduce_context(
        self,
        query: str,
        max_tokens_per_community: int = 2000,
        community_level: int = 0,
    ) -> list[SearchContext]:
        """Build separate contexts for each community (Map-Reduce pattern).

        This method creates individual contexts for each community,
        allowing parallel processing and aggregation of results.

        Args:
            query: The search query.
            max_tokens_per_community: Max tokens per community context.
            community_level: Community hierarchy level.

        Returns:
            List of SearchContext, one per relevant community.
        """
        communities, _ = await self._find_relevant_communities(query, community_level)

        contexts = []
        for comm in communities:
            context = self.create_context(query, max_tokens_per_community)

            title = comm.get("title", "Unknown Community")
            summary = comm.get("summary", "")

            context.add_content(
                name="Community",
                content=f"## {title}\n{summary}",
                priority=100,
                metadata={"community_id": comm.get("id")},
            )

            entities = await self._get_community_entities(comm.get("id"))
            if entities:
                entity_content = self._format_entities_section(entities)
                context.add_content(
                    name="Community Entities",
                    content=entity_content,
                    priority=90,
                )

            contexts.append(context)

        return contexts

    async def _get_community_entities(
        self,
        community_id: str,
    ) -> list[dict[str, Any]]:
        """Get entities belonging to a specific community."""
        if not community_id:
            return []

        cypher = """
        MATCH (c:Community {id: $community_id})-[:HAS_ENTITY]->(e:Entity)
        RETURN e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(
                cypher,
                {"community_id": community_id, "limit": self._max_entities_per_community},
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_community_entities_failed", error=str(exc))
            return []
