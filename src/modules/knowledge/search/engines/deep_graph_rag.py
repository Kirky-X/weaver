# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DeepGraphRAGEngine — 3-stage hierarchical retrieval.

Implements a three-stage hierarchical retrieval pipeline:
1. Community Filtering: LLM embed + vector search to find relevant communities
2. Entity Refinement: Query community_repo for entities, filter by degree
3. Entity-Level Search: Vector similarity with fusion scoring + beam reranking

Fusion score formula:
    0.4 * similarity + 0.3 * community_relevance + 0.2 * centrality + 0.1 * recency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.observability import get_logger

log = get_logger(__name__)


@dataclass
class DeepGraphRAGConfig:
    """Configuration for DeepGraphRAGEngine."""

    community_top_k: int = 5
    min_degree: int = 1
    sim_weight: float = 0.4
    community_weight: float = 0.3
    centrality_weight: float = 0.2
    recency_weight: float = 0.1
    max_depth: int = 3


@dataclass
class DeepGraphRAGResult:
    """Result from DeepGraphRAGEngine search."""

    query: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    communities_filtered: int = 0
    entities_candidates: int = 0
    depth_reached: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class DeepGraphRAGEngine:
    """3-stage hierarchical retrieval engine.

    Implements: DeepGraphRAG Integration — ADD §3.2

    Pipeline:
    1. _community_filter: LLM embed + vector search top communities
    2. _entity_refine: Query community_repo for entities, filter by degree
    3. _entity_search: Vector similarity with fusion scoring + beam reranking

    Args:
        vector_repo: Vector repository for community/entity search.
        graph_repo: Graph repository for entity queries.
        community_repo: Community repository for entity retrieval.
        llm_client: LLM client for embedding generation.
        reranker: Optional BeamSearchReranker for final reranking.
        community_vector_repo: Optional community vector repository for dedicated community search.
        config: Engine configuration.
    """

    def __init__(
        self,
        vector_repo: Any = None,
        graph_repo: Any = None,
        community_repo: Any = None,
        llm_client: Any = None,
        reranker: Any = None,
        community_vector_repo: Any = None,
        config: DeepGraphRAGConfig | None = None,
    ) -> None:
        if graph_repo is None:
            raise TypeError("graph_repo is required")
        if community_repo is None:
            raise TypeError("community_repo is required")
        if llm_client is None:
            raise TypeError("llm_client is required")

        self._vector_repo = vector_repo
        self._graph_repo = graph_repo
        self._community_repo = community_repo
        self._llm_client = llm_client
        self._reranker = reranker
        self._community_vector_repo = community_vector_repo
        self._config = config or DeepGraphRAGConfig()

    async def search(
        self,
        query: str,
        embedding: list[float] | None = None,
    ) -> DeepGraphRAGResult:
        """Execute 3-stage hierarchical retrieval.

        Args:
            query: Search query text.
            embedding: Pre-computed query embedding.

        Returns:
            DeepGraphRAGResult with entities and statistics.
        """
        log.info("deep_graph_rag_search_started", query=query[:100])

        # Stage 1: Community filtering
        communities = await self._community_filter(
            embedding=embedding, top_k=self._config.community_top_k, query=query
        )

        if not communities:
            log.info("deep_graph_rag_no_communities", query=query[:50])
            return DeepGraphRAGResult(query=query)

        # Stage 2: Entity refinement
        refined = await self._entity_refine(communities)

        # Stage 3: Entity-level search with fusion scoring
        query_embedding = embedding
        if query_embedding is None and self._llm_client:
            try:
                embed_results = await self._llm_client.embed_default([query])
                query_embedding = embed_results[0]
            except Exception:
                query_embedding = None

        scored = await self._entity_search(refined, query_embedding)

        # Optional beam reranking
        if self._reranker and scored:
            try:
                scored = self._reranker.rerank(query, scored)
            except Exception as exc:
                log.warning("beam_rerank_failed", error=str(exc))

        depth_reached = min(
            self._config.max_depth, 1 + (1 if refined else 0) + (1 if scored else 0)
        )

        result = DeepGraphRAGResult(
            query=query,
            entities=scored,
            communities_filtered=len(communities),
            entities_candidates=len(refined),
            depth_reached=depth_reached,
        )

        log.info(
            "deep_graph_rag_search_complete",
            communities=len(communities),
            entities=len(scored),
            depth=depth_reached,
        )

        return result

    async def _community_filter(
        self,
        embedding: list[float] | None = None,
        top_k: int = 5,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Stage 1: LLM embed + vector search for relevant communities.

        Args:
            embedding: Pre-computed query embedding vector.
            top_k: Number of top communities to return.
            query: Search query text for LLM embedding.

        Returns:
            List of community dicts with id and score.
        """
        # Try LLM embed first
        query_embedding = None
        if self._llm_client and query:
            try:
                embed_results = await self._llm_client.embed_default([query])
                query_embedding = embed_results[0]
            except Exception as exc:
                log.warning("llm_embed_failed_fallback", error=str(exc))
                query_embedding = embedding  # Fall back to pre-computed
        else:
            query_embedding = embedding

        if not query_embedding:
            return []

        try:
            # Priority 1: Use community vector repo if available
            if self._community_vector_repo:
                try:
                    results = await self._community_vector_repo.find_similar_communities(
                        query_embedding, limit=top_k
                    )
                    communities = [
                        {
                            "id": r.community_id,
                            "score": r.score,
                            "name": r.title or "",
                        }
                        for r in results
                    ]

                    if communities:
                        return communities
                except Exception as exc:
                    log.warning("community_vector_repo_failed", error=str(exc))

            # Priority 2: Fallback to general vector repo
            if self._vector_repo:
                results = await self._vector_repo.find_similar(query_embedding, limit=top_k)
                communities = [
                    {
                        "id": r.article_id,
                        "score": r.similarity,
                        "name": "",
                    }
                    for r in results
                ]

                # Priority 3: Text fallback when vector search returns empty
                if not communities and self._community_repo and query:
                    try:
                        text_results = await self._community_repo.search_by_text(query)
                        communities = [
                            {
                                "id": r.get("id", ""),
                                "score": r.get("score", 0.5),
                                "name": r.get("title", ""),
                            }
                            for r in text_results
                        ]
                    except Exception as exc:
                        log.warning("text_fallback_failed", error=str(exc))

                return communities

            return []
        except Exception as exc:
            log.error("community_filter_failed", error=str(exc))
            return []

    async def _entity_refine(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Stage 2: Query community_repo for entities, filter by degree.

        Args:
            communities: List of community dicts with id and score.

        Returns:
            Filtered entities with degree >= min_degree.
        """
        all_entities = []

        if self._community_repo and hasattr(self._community_repo, "get_community_entities"):
            for c in communities:
                community_id = c.get("id", "")
                if not community_id:
                    continue
                try:
                    entities = await self._community_repo.get_community_entities(community_id)
                    for e in entities:
                        e.setdefault("community_relevance", c.get("score", 0.0))
                        all_entities.append(e)
                except Exception as exc:
                    log.warning(
                        "community_entities_query_failed",
                        community_id=community_id,
                        error=str(exc),
                    )
        else:
            # Fallback: extract entities from community metadata
            all_entities = self._collect_entities_from_communities(communities)

        return [e for e in all_entities if e.get("degree", 0) >= self._config.min_degree]

    async def _entity_search(
        self,
        entities: list[dict[str, Any]],
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Stage 3: Compute fusion scores for entities.

        When vector_repo is available, uses find_similar_entities for actual
        vector similarity. Otherwise falls back to in-memory fusion scoring.

        Fusion formula:
            0.4 * similarity + 0.3 * community_relevance
            + 0.2 * centrality + 0.1 * recency

        Args:
            entities: List of entity dicts with scoring fields.
            query_embedding: Query embedding for vector similarity.

        Returns:
            Entities sorted by fusion_score descending.
        """
        # If vector_repo available, enhance with actual vector similarity
        if self._vector_repo and query_embedding:
            try:
                similar = await self._vector_repo.find_similar_entities(query_embedding, limit=20)
                # Build similarity map from vector results
                sim_map = {}
                for r in similar:
                    sim_map[r.neo4j_id] = r.similarity

                # Update entity similarity scores from vector search
                for e in entities:
                    eid = e.get("id", e.get("neo4j_id", ""))
                    if eid in sim_map:
                        e["similarity"] = sim_map[eid]
            except Exception as exc:
                log.warning("vector_similarity_failed", error=str(exc))

        # Compute fusion scores
        scored = []
        for e in entities:
            fusion_score = (
                self._config.sim_weight * e.get("similarity", 0.0)
                + self._config.community_weight * e.get("community_relevance", 0.0)
                + self._config.centrality_weight * e.get("centrality", 0.0)
                + self._config.recency_weight * e.get("recency", 0.0)
            )
            scored.append({**e, "fusion_score": fusion_score})

        scored.sort(key=lambda x: x["fusion_score"], reverse=True)
        return scored

    def _collect_entities_from_communities(
        self,
        communities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Collect entities from community metadata (fallback).

        Args:
            communities: List of community dicts.

        Returns:
            List of entity dicts.
        """
        entities = []
        for c in communities:
            community_entities = c.get("entities", [])
            for e in community_entities:
                e.setdefault("community_relevance", c.get("score", 0.0))
                entities.append(e)
        return entities
