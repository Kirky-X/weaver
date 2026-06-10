# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DeepGraphRAGEngine — 3-stage hierarchical retrieval.

Implements a three-stage hierarchical retrieval pipeline:
1. Community Filtering: Vector search to find relevant communities
2. Entity Refinement: Filter isolated entities by degree
3. Entity-Level Search: Fusion scoring with beam reranking

Fusion score formula:
    0.4 * similarity + 0.3 * community_relevance + 0.2 * centrality + 0.1 * recency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.observability.logging import get_logger

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

    Implements: DeepGraphRAGSearchEngine

    Pipeline:
    1. _community_filter: Vector search top communities
    2. _entity_refine: Filter isolated entities by degree
    3. _entity_search: Fusion scoring with optional beam reranking

    Args:
        vector_repo: Vector repository for community search.
        reranker: Optional BeamSearchReranker for final reranking.
        config: Engine configuration.
    """

    def __init__(
        self,
        vector_repo: Any = None,
        reranker: Any = None,
        config: DeepGraphRAGConfig | None = None,
    ) -> None:
        self._vector_repo = vector_repo
        self._reranker = reranker
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
        communities = await self._community_filter(embedding, top_k=self._config.community_top_k)

        if not communities:
            log.info("deep_graph_rag_no_communities", query=query[:50])
            return DeepGraphRAGResult(query=query)

        # Stage 2: Entity refinement
        raw_entities = self._collect_entities_from_communities(communities)
        refined = self._entity_refine(raw_entities)

        # Stage 3: Entity-level search with fusion scoring
        scored = self._entity_search(refined)

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
        embedding: list[float] | None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Stage 1: Vector search for relevant communities.

        Args:
            embedding: Query embedding vector.
            top_k: Number of top communities to return.

        Returns:
            List of community dicts with id and score.
        """
        if not self._vector_repo or not embedding:
            return []

        try:
            results = await self._vector_repo.find_similar(embedding, limit=top_k)
            return [
                {
                    "id": r.get("id", r.get("doc_id", "")),
                    "score": r.get("score", 0.0),
                    "name": r.get("name", ""),
                }
                for r in results
            ]
        except Exception as exc:
            log.error("community_filter_failed", error=str(exc))
            return []

    def _entity_refine(
        self,
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Stage 2: Filter isolated entities by degree.

        Args:
            entities: List of entity dicts with degree field.

        Returns:
            Filtered entities with degree >= min_degree.
        """
        return [e for e in entities if e.get("degree", 0) >= self._config.min_degree]

    def _entity_search(
        self,
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Stage 3: Compute fusion scores for entities.

        Fusion formula:
            0.4 * similarity + 0.3 * community_relevance
            + 0.2 * centrality + 0.1 * recency

        Args:
            entities: List of entity dicts with scoring fields.

        Returns:
            Entities sorted by fusion_score descending.
        """
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
        """Collect entities from community results.

        In production, this would query the graph database for entities
        belonging to the filtered communities. For now, returns entities
        embedded in community metadata.

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
