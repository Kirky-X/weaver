# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Adaptive Search Engine for MAGMA multi-graph retrieval.

Implements Heuristic Beam Search with intent-aware traversal
across four orthogonal graph views (Temporal, Causal, Semantic, Entity).

Based on MAGMA Algorithm 1: Adaptive Hybrid Retrieval.

Enhanced with Phase 0 knowledge cache check for semantic similarity matching.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

from core.observability.logging import get_logger
from modules.memory.core.event_node import EventNode
from modules.memory.core.graph_types import EdgeType, IntentType
from modules.memory.core.traversal import calculate_transition_score

if TYPE_CHECKING:
    from core.protocols.knowledge_cache import KnowledgeCacheProtocol
    from modules.memory.graphs.causal import CausalGraphRepo
    from modules.memory.graphs.temporal import TemporalGraphRepo

log = get_logger(__name__)


class EmbeddingServiceProtocol(Protocol):
    """Protocol for embedding service."""

    async def embed(self, text: str) -> list[float]:
        """Compute embedding for a single text."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for multiple texts."""
        ...

    def is_ready(self) -> bool:
        """Check if the embedding service is ready."""
        ...

    def start_loading(self) -> None:
        """Start loading the model in background."""
        ...


class IntentClassifierProtocol(Protocol):
    """Protocol for intent classifier."""

    async def classify(self, query: str) -> Any: ...


class AdaptiveSearchEngine:
    """Intent-aware adaptive search across multi-graph views.

    This engine implements MAGMA's Heuristic Beam Search algorithm
    for retrieving relevant events based on query intent.

    Enhanced with Phase 0 cache check for semantic similarity matching.
    When a similar query has been processed before, returns cached results
    directly without graph traversal.
    """

    def __init__(
        self,
        temporal_repo: TemporalGraphRepo,
        causal_repo: CausalGraphRepo,
        embedding_service: EmbeddingServiceProtocol,
        intent_classifier: IntentClassifierProtocol,
        knowledge_cache: KnowledgeCacheProtocol | None = None,
        cache_similarity_threshold: float = 0.85,
        max_depth: int = 5,
        beam_width: int = 10,
        token_budget: int = 4000,
        decay_factor: float = 0.9,
        why_anchor_limit: int = 5,
        when_anchor_limit: int = 3,
        default_anchor_limit: int = 3,
        event_lookup_limit: int = 1000,
    ) -> None:
        """Initialize the adaptive search engine.

        Args:
            temporal_repo: Repository for temporal graph operations.
            causal_repo: Repository for causal graph operations.
            embedding_service: Service for computing embeddings.
            intent_classifier: Classifier for query intent.
            knowledge_cache: Optional cache for similar query results.
            cache_similarity_threshold: Minimum similarity for cache hit.
            max_depth: Maximum traversal depth.
            beam_width: Number of candidates to keep at each step.
            token_budget: Maximum tokens for retrieved context.
            decay_factor: Decay factor for cumulative scores.
            why_anchor_limit: Max anchors for WHY intent.
            when_anchor_limit: Max anchors for WHEN intent.
            default_anchor_limit: Max anchors for default intent.
            event_lookup_limit: Max events to lookup by ID.
        """
        self._temporal_repo = temporal_repo
        self._causal_repo = causal_repo
        self._embedding_service = embedding_service
        self._intent_classifier = intent_classifier
        self._knowledge_cache = knowledge_cache
        self._cache_similarity_threshold = cache_similarity_threshold
        self._max_depth = max_depth
        self._beam_width = beam_width
        self._token_budget = token_budget
        self._decay_factor = decay_factor
        self._why_anchor_limit = why_anchor_limit
        self._when_anchor_limit = when_anchor_limit
        self._default_anchor_limit = default_anchor_limit
        self._event_lookup_limit = event_lookup_limit

    async def search(
        self,
        query: str,
        anchors: list[str] | None = None,
        intent: IntentType | None = None,
    ) -> list[dict[str, Any]]:
        """Execute adaptive search across multi-graph views.

        Args:
            query: The search query.
            anchors: Optional list of anchor event IDs to start from.
            intent: Optional pre-classified intent.

        Returns:
            List of relevant events with scores.
        """
        start_time = time.monotonic()

        try:
            # Phase 0: Check knowledge cache for similar queries
            if self._knowledge_cache is not None:
                cached_cluster = await self._knowledge_cache.find_similar_cluster(
                    query, threshold=self._cache_similarity_threshold
                )
                if cached_cluster is not None:
                    # Update hotness for cache hit
                    await self._knowledge_cache.update_hotness(cached_cluster.id)

                    latency_ms = (time.monotonic() - start_time) * 1000
                    log.info(
                        "adaptive_search_cache_hit",
                        query=query[:50],
                        cluster_id=cached_cluster.id,
                        latency_ms=round(latency_ms, 2),
                    )

                    # Return cached content as result
                    return [
                        {
                            "id": cached_cluster.id,
                            "content": cached_cluster.content,
                            "score": 1.0,  # Perfect match from cache
                            "source": "cache",
                        }
                    ]

            # 1. Classify intent if not provided
            if intent is None:
                classification = await self._intent_classifier.classify(query)
                intent = (
                    classification.intent if hasattr(classification, "intent") else IntentType.OPEN
                )

            # 2. Compute query embedding
            query_embedding = await self._embedding_service.embed(query)

            # 3. Find anchor nodes if not provided
            if not anchors:
                anchors = await self._find_anchors(query, query_embedding, intent)

            if not anchors:
                log.warning("adaptive_search_no_anchors", query=query[:50])
                return []

            # 4. Execute beam search
            results = await self._beam_search(
                anchors=anchors,
                query_embedding=query_embedding,
                intent=intent,
            )

            latency_ms = (time.monotonic() - start_time) * 1000
            log.info(
                "adaptive_search_complete",
                query=query[:50],
                intent=intent.value,
                results=len(results),
                latency_ms=round(latency_ms, 2),
            )

            # Filter zero-relevance events (exp(0) = 1.0 means no alignment)
            results = [r for r in results if r.get("score", 0) > 1.0]

            # Normalize scores to [0, 1] range (MAGMA Eq.5 exp() output is unbounded)
            if results:
                scores = [r.get("score", 0) for r in results]
                min_score = min(scores)
                max_score = max(scores)
                score_range = max_score - min_score
                for r in results:
                    raw = r.get("score", 0)
                    r["score"] = 0.5 if score_range == 0 else (raw - min_score) / score_range

            # Phase 5: Store results in cache for future queries
            if self._knowledge_cache is not None and results:
                await self._store_search_results(query, results)

            return results

        except Exception as exc:
            log.error("adaptive_search_failed", query=query[:50], error=str(exc))
            return []

    async def _store_search_results(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Store search results in knowledge cache.

        Args:
            query: The original query.
            results: The search results to cache.
        """
        try:
            import uuid

            from core.protocols.knowledge_cache import KnowledgeCluster

            # Create a cluster from the top result
            if not results:
                return

            top_result = results[0]
            cluster = KnowledgeCluster(
                id=f"kc_{uuid.uuid4().hex[:8]}",
                name=query[:100],
                description=query,
                content=top_result.get("content", ""),
                query=query,
                hotness=0.5,
            )

            await self._knowledge_cache.store_cluster(cluster)
            log.debug("search_results_cached", cluster_id=cluster.id, query=query[:50])

        except Exception as exc:
            log.warning("failed_to_cache_results", error=str(exc))

    async def _find_anchors(
        self,
        query: str,
        query_embedding: list[float],
        intent: IntentType,
    ) -> list[str]:
        """Find anchor nodes for traversal using semantic search.

        Args:
            query: The search query.
            query_embedding: Query embedding.
            intent: Query intent.

        Returns:
            List of anchor event IDs.
        """
        # Use semantic search to find relevant anchors (not just recent events)
        anchor_limit = self._default_anchor_limit
        if intent == IntentType.WHY:
            anchor_limit = self._why_anchor_limit
        elif intent == IntentType.WHEN:
            anchor_limit = self._when_anchor_limit

        # Try semantic search first
        events = await self._temporal_repo.search_temporal_events(query=query, limit=anchor_limit)

        # Fallback to temporal chain if no semantic matches found
        if not events:
            events = await self._temporal_repo.get_temporal_chain(limit=anchor_limit)

        return [e["id"] for e in events if e.get("id")]

    async def _beam_search(
        self,
        anchors: list[str],
        query_embedding: list[float],
        intent: IntentType,
    ) -> list[dict[str, Any]]:
        """Execute heuristic beam search traversal.

        Args:
            anchors: Starting anchor event IDs.
            query_embedding: Query embedding vector.
            intent: Query intent type.

        Returns:
            List of retrieved events with scores.
        """
        visited: set[str] = set()
        # Score anchors based on content relevance instead of fixed 1.0
        scored_anchors: list[tuple[str, float]] = []
        for anchor_id in anchors:
            event_data = await self._get_event_data(anchor_id)
            if event_data:
                anchor_event = EventNode(
                    id=anchor_id,
                    content=event_data.get("content", ""),
                    timestamp=event_data.get("timestamp"),
                    embedding=None,
                )
                anchor_score = calculate_transition_score(
                    neighbor=anchor_event,
                    query_embedding=query_embedding,
                    query_intent=intent,
                    edge_type=EdgeType.TEMPORAL,
                )
                scored_anchors.append((anchor_id, anchor_score))
            else:
                scored_anchors.append((anchor_id, 0.5))

        frontier = scored_anchors
        results: list[dict[str, Any]] = []

        for depth in range(self._max_depth):
            if not frontier:
                break

            candidates: list[tuple[str, float]] = []

            for event_id, cumulative_score in frontier:
                if event_id in visited:
                    continue
                visited.add(event_id)

                # Get event details
                event_data = await self._get_event_data(event_id)
                if event_data:
                    content = event_data.get("content", "")
                    if content.strip():
                        results.append(
                            {
                                "id": event_id,
                                "content": content,
                                "timestamp": event_data.get("timestamp"),
                                "score": cumulative_score,
                            }
                        )

                # Get neighbors based on intent
                neighbors = await self._get_neighbors_by_intent(event_id, intent)

                for neighbor_id, edge_type in neighbors:
                    if neighbor_id in visited:
                        continue

                    # Create placeholder EventNode with minimal data for scoring
                    neighbor_event = EventNode(
                        id=neighbor_id,
                        content="",
                        timestamp=None,
                        embedding=None,
                    )

                    score = calculate_transition_score(
                        neighbor=neighbor_event,
                        query_embedding=query_embedding,
                        query_intent=intent,
                        edge_type=edge_type,
                    )

                    decayed_score = cumulative_score * self._decay_factor + score
                    candidates.append((neighbor_id, decayed_score))

            # Beam search: keep top-k
            candidates.sort(key=lambda x: x[1], reverse=True)
            frontier = candidates[: self._beam_width]

            # Token budget check
            if self._estimate_tokens(results) >= self._token_budget:
                break

        return results

    async def _get_event_data(self, event_id: str) -> dict[str, Any] | None:
        """Get event data by ID.

        Args:
            event_id: Event ID.

        Returns:
            Event data dictionary or None.
        """
        # Try temporal repo first
        events = await self._temporal_repo.get_temporal_chain(limit=self._event_lookup_limit)
        for event in events:
            if event.get("id") == event_id:
                return event
        return None

    async def _get_neighbors_by_intent(
        self,
        event_id: str,
        intent: IntentType,
    ) -> list[tuple[str, EdgeType]]:
        """Get neighbors based on intent.

        Args:
            event_id: Event ID to get neighbors for.
            intent: Query intent.

        Returns:
            List of (neighbor_id, edge_type) tuples.
        """
        neighbors: list[tuple[str, EdgeType]] = []

        # Always get temporal neighbors
        temporal_neighbors = await self._temporal_repo.get_neighbors(event_id)
        for n in temporal_neighbors:
            if n.get("id"):
                neighbors.append((n["id"], EdgeType.TEMPORAL))

        # For WHY queries, prioritize causal neighbors
        if intent == IntentType.WHY:
            causes = await self._causal_repo.get_causes(event_id)
            for c in causes:
                if c.get("id"):
                    neighbors.append((c["id"], EdgeType.CAUSAL))

            effects = await self._causal_repo.get_effects(event_id)
            for e in effects:
                if e.get("id"):
                    neighbors.append((e["id"], EdgeType.CAUSAL))

        return neighbors

    def _estimate_tokens(self, results: list[dict[str, Any]]) -> int:
        """Estimate token count for results.

        Args:
            results: List of result dictionaries.

        Returns:
            Estimated token count.
        """
        total_chars = sum(len(r.get("content", "")) for r in results)
        # Rough estimate: ~4 chars per token
        return total_chars // 4
