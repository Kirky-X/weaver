# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Base global context builder using Template Method pattern.

Provides shared build flow for community-based search context,
with database-specific hooks for Neo4j and LadybugDB.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from core.db.graph_query_builders import (
    CommunitySearchConfig,
    GraphQueryBuilder,
)
from core.llm.client import LLMClient
from core.observability import get_logger
from modules.knowledge.search.context.builder import ContextBuilder, SearchContext

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class BaseGlobalContextBuilder(ContextBuilder):
    """Base class for global context builders using Template Method pattern.

    Provides the shared build flow for community-based search:
    1. Find relevant communities (vector → text → fallback cascade)
    2. Format community summaries
    3. Get key entities (optional, skipped for fallback results)
    4. Get cross-community relationships (optional, skipped for fallback results)
    5. Assemble SearchContext

    Subclasses must set ``_query_builder`` in ``__init__`` and may override
    hook methods for database-specific behavior.

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
        super().__init__(token_encoder, default_max_tokens)
        self._pool = graph_pool
        self._max_communities = max_communities
        self._max_entities_per_community = max_entities_per_community
        self._llm_client = llm_client
        self._fallback_enabled = fallback_enabled
        self._query_builder: GraphQueryBuilder  # set by subclass

    # ── Template Method: build ──────────────────────────────────────────

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

        relevant_communities, used_fallback, search_method = await self.find_relevant_communities(
            query, community_level
        )

        if not relevant_communities:
            has_communities = await self.has_any_communities(community_level)
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
            community_content = self.format_communities_section(relevant_communities)
            context.add_content(
                name="Community Summaries",
                content=community_content,
                priority=100,
                metadata={"community_count": len(relevant_communities)},
            )

        # Skip supplementary queries for fallback results when appropriate
        cross_community_rels: list[dict[str, Any]] = []
        if not self._should_skip_supplementary(used_fallback):
            key_entities = await self._get_key_entities(relevant_communities)
            if key_entities:
                entity_content = self.format_entities_section(key_entities)
                context.add_content(
                    name="Key Entities",
                    content=entity_content,
                    priority=90,
                    metadata={"entity_count": len(key_entities)},
                )

            cross_community_rels = await self._get_cross_community_relationships(
                relevant_communities
            )

        if cross_community_rels:
            rel_content = self.format_cross_community_section(
                cross_community_rels, include_direction=self._include_cross_community_direction()
            )
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

    # ── Shared methods using query_builder ──────────────────────────────

    async def has_any_communities(self, level: int | None = None) -> bool:
        """Check if any communities exist in the graph."""
        cypher = self._query_builder.build_communities_exist_query(level)

        try:
            params: dict[str, Any] = {}
            if level is not None:
                params["level"] = level
            result = await self._pool.execute_query(cypher, params)
            if result and result[0].get("count", 0) > 0:
                return True
        except (TypeError, KeyError, Exception) as exc:
            log.debug("has_communities_check_failed", error=str(exc))
        return False

    async def find_relevant_communities(
        self,
        query: str,
        level: int,
    ) -> tuple[list[dict[str, Any]], bool, str]:
        """Find communities relevant to the query.

        Three-step cascade: vector similarity → text search → entity-article fallback.
        """
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

    async def _text_search_communities(
        self,
        query: str,
        level: int,
    ) -> list[dict[str, Any]]:
        """Search communities using text matching on title/summary."""
        config = CommunitySearchConfig(level=level, query=query, limit=self._max_communities)
        cypher = self._query_builder.build_community_search_query(config)

        try:
            results = await self._pool.execute_query(
                cypher,
                {"level": level, "query": query.lower(), "limit": self._max_communities},
            )
            if results:
                return [dict(r) for r in results]
        except Exception as exc:
            log.debug("text_search_failed", error=str(exc))

        # Fall back to top communities by rank (no query filter)
        config_fallback = CommunitySearchConfig(level=level, limit=self._max_communities)
        cypher_fallback = self._query_builder.build_community_search_query(config_fallback)

        try:
            results = await self._pool.execute_query(
                cypher_fallback,
                {"level": level, "limit": self._max_communities},
            )
            if results:
                return [dict(r) for r in results]
        except Exception as exc:
            log.warning("community_fallback_failed", error=str(exc))

        return []

    async def _get_key_entities(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get key entities from the communities.

        Filters out non-UUID IDs (e.g. fallback results like "fallback:a1")
        since they are not real community IDs and cannot be used in queries.
        """
        if not communities:
            return []

        import re

        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        community_ids = [
            cid for c in communities if (cid := c.get("id")) and uuid_pattern.match(str(cid))
        ]
        if not community_ids:
            return []

        cypher = self._query_builder.build_key_entities_query(
            community_ids,
            self._max_entities_per_community * len(community_ids),
        )

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

    async def get_community_entities(
        self,
        community_id: str,
    ) -> list[dict[str, Any]]:
        """Get entities belonging to a specific community.

        Filters out non-UUID IDs (e.g. fallback results like "entity:xxx")
        since they are not real community IDs and cannot be used in queries.
        """
        if not community_id:
            return []

        # Skip non-UUID community IDs (e.g. fallback results like "entity:xxx")
        # validate_uuid in build_community_entities_query would reject these,
        # but the call is outside the try-except block below.
        import re

        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        if not uuid_pattern.match(str(community_id)):
            log.debug("skip_non_uuid_community_id", community_id=community_id)
            return []

        cypher = self._query_builder.build_community_entities_query(
            community_id, self._max_entities_per_community
        )

        try:
            results = await self._pool.execute_query(
                cypher,
                {"community_id": community_id, "limit": self._max_entities_per_community},
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.warning("get_community_entities_failed", community_id=community_id, error=str(exc))
            return []

    async def build_map_reduce_context(
        self,
        query: str,
        max_tokens_per_community: int = 2000,
        community_level: int = 0,
    ) -> list[SearchContext]:
        """Build separate contexts for each community (Map-Reduce pattern)."""
        communities, used_fallback, search_method = await self.find_relevant_communities(
            query, community_level
        )

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

            entities = await self.get_community_entities(str(comm.get("id", "")))
            if entities:
                entity_content = self.format_entities_section(entities)
                context.add_content(
                    name="Community Entities",
                    content=entity_content,
                    priority=90,
                )

            contexts.append(context)

        return contexts

    # ── Hook methods (override in subclasses) ───────────────────────────

    def _should_skip_supplementary(self, used_fallback: bool) -> bool:
        """Whether to skip key entities and cross-community queries.

        LadybugDB skips these for fallback results since they are already
        entity-based. Neo4j includes them regardless.
        """
        return False

    def _include_cross_community_direction(self) -> bool:
        """Whether to include direction indicators in cross-community section."""
        return False

    @abstractmethod
    async def _vector_search_communities(
        self,
        query: str,
        level: int,
    ) -> list[dict[str, Any]]:
        """Search communities using vector similarity.

        Neo4j uses vector.similarity.cosine(), LadybugDB falls back to text.
        """
        ...

    @abstractmethod
    async def _find_entity_article_fallback(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        """Find entity-article aggregation as fallback.

        Result shape differs between Neo4j (article-based) and LadybugDB
        (entity-based).
        """
        ...

    @abstractmethod
    async def _get_cross_community_relationships(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get relationships that connect different communities.

        Neo4j queries both typed and generic relationships.
        LadybugDB queries generic relationships only.
        """
        ...
