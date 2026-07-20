# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Neo4j global context builder for community-based search.

Builds context using community reports and hierarchical structure,
suitable for broad, exploratory queries that span multiple communities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.db.graph_query_builders import create_graph_query_builder
from core.llm.client import LLMClient
from core.observability import get_logger
from modules.knowledge.search.context.base_global_context import BaseGlobalContextBuilder

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class GlobalContextBuilder(BaseGlobalContextBuilder):
    """Builds global context using community reports from Neo4j.

    This builder uses community-level aggregation to handle queries
    that require understanding of the overall graph structure.

    Neo4j-specific features:
    - Vector similarity search via vector.similarity.cosine()
    - Typed relationship queries (semantic edge types)
    - CommunityReport nodes with full_content

    Implements: ContextBuilder (via BaseGlobalContextBuilder)
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
        article_repo: Any = None,
    ) -> None:
        super().__init__(
            graph_pool=graph_pool,
            token_encoder=token_encoder,
            default_max_tokens=default_max_tokens,
            max_communities=max_communities,
            max_entities_per_community=max_entities_per_community,
            llm_client=llm_client,
            fallback_enabled=fallback_enabled,
        )
        self._query_builder = create_graph_query_builder("neo4j")
        self._article_repo = article_repo

    def _should_skip_supplementary(self, used_fallback: bool) -> bool:
        """Neo4j skips supplementary queries for fallback results.

        Fallback results use synthetic IDs (e.g. "fallback:a1") that are
        not real community IDs, so key entities and cross-community
        relationship queries would fail.
        """
        return used_fallback

    def _include_cross_community_direction(self) -> bool:
        """Neo4j includes direction indicators in cross-community section."""
        return True

    async def _vector_search_communities(
        self,
        query: str,
        level: int,
    ) -> list[dict[str, Any]]:
        """Search communities using vector similarity on report embeddings."""
        if not self._llm_client:
            return []

        try:
            embeddings = await self._llm_client.embed_default([query])
            if not embeddings or not embeddings[0]:
                return []

            query_embedding = embeddings[0]

            cypher = """
            MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
            WHERE c.level >= $level AND r.full_content_embedding IS NOT NULL
            WITH c, r, vector.similarity.cosine(r.full_content_embedding, $embedding) AS score
            WHERE score > 0.3
            RETURN c.id AS id,
                   c.title AS title,
                   COALESCE(r.summary, '') AS summary,
                   c.rank AS rank,
                   c.entity_count AS entity_count,
                   r.full_content AS full_content,
                   r.key_entities AS key_entities,
                   score
            ORDER BY score DESC
            LIMIT $limit
            """

            results = await self._pool.execute_query(
                cypher,
                {"level": level, "embedding": query_embedding, "limit": self._max_communities},
            )

            if results:
                log.debug(
                    "vector_search_communities_found",
                    count=len(results),
                    top_score=results[0].get("score", 0),
                )
                return [
                    {
                        "id": r.get("id"),
                        "title": r.get("title", ""),
                        "summary": r.get("summary", ""),
                        "rank": r.get("rank", 1.0),
                        "entity_count": r.get("entity_count", 0),
                        "full_content": r.get("full_content", ""),
                        "key_entities": r.get("key_entities", []),
                        "similarity_score": r.get("score", 0),
                    }
                    for r in results
                ]
        except Exception as exc:
            log.warning("vector_search_communities_failed", error=str(exc))

        return []

    async def _find_entity_article_fallback(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        """Find entity-article aggregation as fallback.

        Queries Article-Entity relationships via MENTIONS edges.
        Returns article-based results with entity context.

        After the Article node slim-down (design.md §D2), the graph query
        returns only ``article_id`` (= ``a.pg_id``) plus entity fields.
        When ``self._article_repo`` is available, title and score are
        batch-fetched from PostgreSQL; otherwise the result falls back
        to using ``entity_name`` as the title and ``0.5`` as the rank.
        """
        tokens = [t.strip() for t in query.split() if t.strip()]
        if not tokens:
            return []

        cypher = self._query_builder.build_entity_article_fallback_query(
            tokens, self._max_communities
        )

        try:
            results = await self._pool.execute_query(
                cypher,
                {"tokens": tokens, "limit": self._max_communities},
            )

            if not results:
                return []

            # Batch-fetch titles/scores from PostgreSQL when available.
            # Graph query returns ``a.pg_id AS article_id``; missing or
            # non-string values are filtered out before the batch call.
            pg_ids = [str(r.get("article_id")) for r in results if r.get("article_id")]
            titles: dict[str, dict[str, Any]] = {}
            if self._article_repo and pg_ids:
                try:
                    titles = await self._article_repo.fetch_titles_by_pg_ids(pg_ids)
                except Exception as exc:
                    log.warning(
                        "fallback_fetch_titles_failed",
                        error=str(exc),
                        pg_id_count=len(pg_ids),
                    )
                    titles = {}

            fallback_results: list[dict[str, Any]] = []
            for r in results:
                row = dict(r)
                pg_id = str(row.get("article_id") or "")
                meta = titles.get(pg_id.lower()) if pg_id else None
                entity_name = row.get("entity_name", "")
                # When article_repo is available, use the real title;
                # otherwise degrade to entity_name only (no trailing dash).
                title = (meta or {}).get("title") or entity_name
                rank = float((meta or {}).get("score") or 0.5)
                fallback_results.append(
                    {
                        "id": f"fallback:{pg_id}",
                        "title": title,
                        "summary": row.get("entity_description", ""),
                        "rank": rank,
                        "entity_count": 1,
                    }
                )
            return fallback_results
        except Exception as exc:
            log.warning("entity_article_fallback_failed", error=str(exc))
            return []

    async def _get_cross_community_relationships(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get relationships that connect different communities.

        Neo4j queries both typed relationships (semantic edge types)
        and generic RELATED_TO relationships.
        """
        if len(communities) < 2:
            return []

        community_ids = [str(c["id"]) for c in communities if c.get("id")]

        # First try typed relationships (semantic edge types)
        typed_cypher = """
        MATCH (c1:Community)-[:HAS_ENTITY]->(e1:Entity)
              -[r]->(e2:Entity)<-[:HAS_ENTITY]-(c2:Community)
        WHERE c1.id IN $community_ids
          AND c2.id IN $community_ids
          AND c1.id <> c2.id
          AND NOT type(r) = 'RELATED_TO'
          AND NOT type(r) = 'MENTIONS'
          AND NOT type(r) = 'HAS_ENTITY'
        RETURN DISTINCT
               c1.title AS source_community,
               c2.title AS target_community,
               e1.canonical_name AS source_entity,
               e2.canonical_name AS target_entity,
               type(r) AS relation_type
        LIMIT 50
        """

        try:
            results = await self._pool.execute_query(
                typed_cypher,
                {"community_ids": community_ids},
            )
            typed_results = [dict(r) for r in results]
        except Exception as exc:
            log.debug("get_typed_cross_community_rels_failed", error=str(exc))
            typed_results = []

        # Also get generic RELATED_TO relationships
        generic_cypher = self._query_builder.build_cross_community_relationships_query(
            community_ids
        )

        try:
            results = await self._pool.execute_query(
                generic_cypher,
                {"community_ids": community_ids},
            )
            generic_results = [dict(r) for r in results]
        except Exception as exc:
            log.debug("get_generic_cross_community_rels_failed", error=str(exc))
            generic_results = []

        return typed_results + generic_results
