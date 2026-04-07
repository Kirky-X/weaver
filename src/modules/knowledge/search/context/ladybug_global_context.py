# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB global context builder for community-based search.

Builds context using community reports and hierarchical structure,
suitable for broad, exploratory queries that span multiple communities.
"""

from __future__ import annotations

from typing import Any

from core.db.graph_query import (
    CommunitySearchConfig,
    GraphQueryBuilder,
    create_graph_query_builder,
)
from core.llm.client import LLMClient
from core.observability.logging import get_logger
from core.protocols import GraphPool
from modules.knowledge.search.context.builder import ContextBuilder, SearchContext

log = get_logger("search.ladybug_global_context")


class LadybugGlobalContextBuilder(ContextBuilder):
    """Builds global context using community reports from LadybugDB.

    This builder uses community-level aggregation to handle queries
    that require understanding of the overall graph structure.

    Implements: ContextBuilder
    """

    def __init__(
        self,
        graph_pool: GraphPool,
        token_encoder: Any = None,
        default_max_tokens: int = 12000,
        max_communities: int = 10,
        max_entities_per_community: int = 5,
        llm_client: LLMClient | None = None,
        fallback_enabled: bool = True,
    ) -> None:
        """Initialize global context builder.

        Args:
            graph_pool: GraphPool instance (LadybugPool).
            token_encoder: Optional tokenizer.
            default_max_tokens: Default max tokens for context.
            max_communities: Maximum communities to include.
            max_entities_per_community: Max entities per community.
            llm_client: LLM client for query embedding (vector search).
            fallback_enabled: Whether to use entity-article fallback when no communities.
        """
        super().__init__(token_encoder, default_max_tokens)
        self._pool = graph_pool
        self._max_communities = max_communities
        self._max_entities_per_community = max_entities_per_community
        self._llm_client = llm_client
        self._fallback_enabled = fallback_enabled
        self._query_builder: GraphQueryBuilder = create_graph_query_builder("ladybug")

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

        relevant_communities, used_fallback, search_method = await self._find_relevant_communities(
            query, community_level
        )

        if not relevant_communities:
            has_communities = await self._has_any_communities(community_level)
            if not has_communities:
                context.add_content(
                    name="No Communities",
                    content="社区数据尚未初始化，请先执行社区检测。",
                    priority=0,
                )
                context.metadata["communities"] = 0
                context.metadata["hint"] = "run POST /api/v1/admin/communities/rebuild"
            else:
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
        context.metadata["search_method"] = search_method
        if used_fallback:
            context.metadata["fallback_source"] = "entity_article"

        return context

    async def _has_any_communities(self, level: int | None = None) -> bool:
        """Check if any communities exist in the graph."""
        cypher = self._query_builder.build_communities_exist_query(level)

        try:
            result = await self._pool.execute_query(cypher)
            if result and result[0].get("count", 0) > 0:
                return True
        except (TypeError, KeyError, Exception) as exc:
            log.debug("has_communities_check_failed", error=str(exc))
        return False

    async def _find_relevant_communities(
        self,
        query: str,
        level: int,
    ) -> tuple[list[dict[str, Any]], bool, str]:
        """Find communities relevant to the query."""
        # Step 1: Try vector similarity search on community reports
        if self._llm_client:
            vector_results = await self._vector_search_communities(query, level)
            if vector_results:
                return vector_results, False, "vector_similarity"

        # Step 2: Try text-based search on community titles/summaries
        text_results = await self._text_search_communities(query, level)
        if text_results:
            return text_results, False, "text_search"

        # Step 3: Fall back to entity-article aggregation if enabled
        if self._fallback_enabled:
            fallback_results = await self._find_entity_article_fallback(query)
            if fallback_results:
                return fallback_results, True, "entity_article_fallback"

        return [], False, "none"

    async def _vector_search_communities(
        self,
        query: str,
        level: int,
    ) -> list[dict[str, Any]]:
        """Search communities using vector similarity on report embeddings.

        Note: LadybugDB doesn't have native vector indexes, so this uses
        full table scan for similarity calculation.
        """
        if not self._llm_client:
            return []

        try:
            embeddings = await self._llm_client.embed(
                "embedding.aiping.Qwen3-Embedding-0.6B", [query]
            )
            if not embeddings or not embeddings[0]:
                return []

            query_embedding = embeddings[0]

            # LadybugDB doesn't support vector.similarity.cosine
            # Fall back to text search for now
            return await self._text_search_communities(query, level)

        except Exception as exc:
            log.warning("vector_search_communities_failed", error=str(exc))
            return []

    async def _text_search_communities(
        self,
        query: str,
        level: int,
    ) -> list[dict[str, Any]]:
        """Search communities using text matching on title/summary."""
        config = CommunitySearchConfig(level=level, query=query, limit=self._max_communities)
        cypher = self._query_builder.build_community_search_query(config)

        try:
            results = await self._pool.execute_query(cypher)
            if results:
                return [dict(r) for r in results]
        except Exception as exc:
            log.debug("text_search_failed", error=str(exc))

        # Fall back to top communities by rank
        config_fallback = CommunitySearchConfig(level=level, limit=self._max_communities)
        cypher_fallback = self._query_builder.build_community_search_query(config_fallback)

        try:
            results = await self._pool.execute_query(cypher_fallback)
            if results:
                return [dict(r) for r in results]
        except Exception as exc:
            log.warning("community_fallback_failed", error=str(exc))

        return []

    async def _find_entity_article_fallback(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        """Find entity-article aggregation as fallback when no Community nodes exist."""
        tokens = [t.strip() for t in query.split() if t.strip()]
        if not tokens:
            return []

        # Build query for LadybugDB
        tokens_str = ", ".join(f"'{t}'" for t in tokens)
        cypher = f"""
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE any(token IN [{tokens_str}] WHERE
                 LOWER(e.canonical_name) CONTAINS token
                 OR LOWER(a.title) CONTAINS token)
        RETURN e.canonical_name AS entity_name,
               e.type AS entity_type,
               e.description AS entity_description,
               a.id AS article_id,
               a.title AS article_title,
               a.score AS article_score
        ORDER BY article_score DESC
        LIMIT {self._max_communities}
        """

        try:
            results = await self._pool.execute_query(cypher)

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
                }
                for r in results
            ]
        except Exception as exc:
            log.warning("entity_article_fallback_failed", error=str(exc))
            return []

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

        cypher = self._query_builder.build_key_entities_query(
            community_ids,
            self._max_entities_per_community * len(community_ids),
        )

        try:
            results = await self._pool.execute_query(cypher)
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
        ids_str = ", ".join(f"'{id}'" for id in community_ids)

        # Query for cross-community relationships via RELATED_TO
        cypher = f"""
        MATCH (c1:Community)-[:HAS_ENTITY]->(e1:Entity)
              -[r:RELATED_TO]->(e2:Entity)<-[:HAS_ENTITY]-(c2:Community)
        WHERE c1.id IN [{ids_str}]
          AND c2.id IN [{ids_str}]
          AND c1.id <> c2.id
        RETURN DISTINCT
               c1.title AS source_community,
               c2.title AS target_community,
               e1.canonical_name AS source_entity,
               e2.canonical_name AS target_entity,
               r.edge_type AS relation_type
        LIMIT 50
        """

        try:
            results = await self._pool.execute_query(cypher)
            return [dict(r) for r in results]
        except Exception as exc:
            log.debug("get_cross_community_rels_failed", error=str(exc))
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
