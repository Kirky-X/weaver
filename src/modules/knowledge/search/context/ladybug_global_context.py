# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LadybugDB global context builder for community-based search.

Builds context using community reports and hierarchical structure,
suitable for broad, exploratory queries that span multiple communities.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from core.db.graph_query_builders import create_graph_query_builder
from core.llm.client import LLMClient
from core.observability import get_logger
from core.protocols import GraphPool
from modules.knowledge.search.context.base_global_context import BaseGlobalContextBuilder

log = get_logger(__name__)

# Upper bound on CommunityReport candidates pulled for in-process cosine
# scoring (each row carries a ~1024-dim float embedding). Keeps memory and
# event-loop latency bounded on large graphs.
_EMBEDDING_CANDIDATE_CAP = 500


class LadybugGlobalContextBuilder(BaseGlobalContextBuilder):
    """Builds global context using community reports from LadybugDB.

    This builder uses community-level aggregation to handle queries
    that require understanding of the overall graph structure.

    LadybugDB-specific features:
    - No native vector search (falls back to text search)
    - Entity-based fallback (no MENTIONS edges)
    - Uses r.edge_type instead of type(r)

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
        self._query_builder = create_graph_query_builder("ladybug")

    def _should_skip_supplementary(self, used_fallback: bool) -> bool:
        """LadybugDB skips supplementary queries for fallback results.

        Fallback results are already entity-based, so key entities
        and cross-community relationships are redundant.
        """
        return used_fallback

    def _include_cross_community_direction(self) -> bool:
        """LadybugDB does not include direction indicators."""
        return False

    async def _vector_search_communities(
        self,
        query: str,
        level: int,
    ) -> list[dict[str, Any]]:
        """Vector search via in-process cosine re-ranking.

        LadybugDB lacks ``vector.similarity.cosine``, but CommunityReport
        nodes persist ``full_content_embedding`` — so fetch candidates with
        embeddings and score them in Python. This keeps parity with the
        Neo4j builder instead of silently degrading to text search (and
        paying for a query embedding that is then thrown away).
        """
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
            RETURN c.id AS id,
                   c.title AS title,
                   COALESCE(r.summary, '') AS summary,
                   c.rank AS rank,
                   c.entity_count AS entity_count,
                   r.full_content AS full_content,
                   r.key_entities AS key_entities,
                   r.full_content_embedding AS embedding
            ORDER BY c.rank DESC
            LIMIT $candidate_cap
            """

            results = await self._pool.execute_query(
                cypher, {"level": level, "candidate_cap": _EMBEDDING_CANDIDATE_CAP}
            )

            # Batched numpy cosine (single matmul) — pure-Python loops cost
            # 100ms+ per 1k communities and block the event loop.
            emb_matrix = np.array(
                [
                    r.get("embedding")
                    for r in results
                    if isinstance(r.get("embedding"), list) and r.get("embedding")
                ],
                dtype=np.float32,
            )
            if emb_matrix.size == 0:
                return []
            query_vec = np.array(query_embedding, dtype=np.float32)
            norms = np.linalg.norm(emb_matrix, axis=1) * np.linalg.norm(query_vec)
            norms[norms == 0.0] = 1e-9
            scores = (emb_matrix @ query_vec) / norms

            scored: list[tuple[float, dict[str, Any]]] = []
            idx = 0
            for r in results:
                emb = r.get("embedding")
                if not isinstance(emb, list) or not emb:
                    continue
                sim = float(scores[idx])
                idx += 1
                if sim > 0.3:
                    scored.append((sim, r))

            scored.sort(key=lambda pair: pair[0], reverse=True)

            if scored:
                log.debug(
                    "ladybug_vector_search_communities_found",
                    count=len(scored),
                    top_score=scored[0][0],
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
                    "similarity_score": round(sim, 4),
                }
                for sim, r in scored[: self._max_communities]
            ]

        except Exception as exc:
            log.warning("vector_search_communities_failed", error=str(exc))
            return []

    async def _find_entity_article_fallback(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        """Find entity-article aggregation as fallback.

        LadybugDB searches Entity directly (MENTIONS edges may not exist).
        Returns entity-based results.
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

            # If no results with token-based search, try full query substring match
            # For Chinese queries without spaces, split into individual keywords
            if not results and len(query) > 1:
                chinese_chunks: list[str] = []
                for chunk_len in [4, 3, 2]:
                    for i in range(0, len(query) - chunk_len + 1):
                        chinese_chunks.append(query[i : i + chunk_len])

                if chinese_chunks:
                    chunks_to_search = chinese_chunks[:10]
                    fallback_cypher = (
                        self._query_builder.build_entity_article_fallback_with_description_query(
                            chunks_to_search, self._max_communities
                        )
                    )
                    results = await self._pool.execute_query(
                        fallback_cypher,
                        {"tokens": chunks_to_search, "limit": self._max_communities},
                    )

            if not results:
                return []

            return [
                {
                    "id": f"entity:{dict(r).get('entity_name', '')}",
                    "title": dict(r).get("entity_name", ""),
                    "summary": dict(r).get("entity_description", ""),
                    "rank": (
                        1.0 - (dict(r).get("entity_tier", 2) / 10.0)
                    ),  # Higher tier = lower rank
                }
                for r in results
            ]
        except Exception as exc:
            log.warning("entity_article_fallback_failed", error=str(exc))
            return []

    async def _get_cross_community_relationships(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get relationships that connect different communities.

        LadybugDB queries generic relationships only (no typed edge queries).
        """
        if len(communities) < 2:
            return []

        community_ids = [str(c["id"]) for c in communities if c.get("id")]

        cypher = self._query_builder.build_cross_community_relationships_query(community_ids)

        try:
            results = await self._pool.execute_query(
                cypher,
                {"community_ids": community_ids},
            )
            return [dict(r) for r in results]
        except Exception as exc:
            log.debug("get_cross_community_rels_failed", error=str(exc))
            return []
