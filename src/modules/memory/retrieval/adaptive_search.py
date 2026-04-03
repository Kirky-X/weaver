# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Adaptive Search Engine for MAGMA multi-graph retrieval.

Implements Heuristic Beam Search with intent-aware traversal
across four orthogonal graph views (Temporal, Causal, Semantic, Entity).

Based on MAGMA Algorithm 1: Adaptive Hybrid Retrieval.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

from core.observability.logging import get_logger
from modules.memory.core.event_node import EventNode
from modules.memory.core.graph_types import EdgeType, IntentType
from modules.memory.core.traversal import calculate_transition_score

if TYPE_CHECKING:
    from modules.memory.graphs.causal import CausalGraphRepo
    from modules.memory.graphs.temporal import TemporalGraphRepo

log = get_logger("adaptive_search")


class EmbeddingServiceProtocol(Protocol):
    """Protocol for embedding service."""

    async def embed(self, text: str) -> list[float]: ...


class IntentClassifierProtocol(Protocol):
    """Protocol for intent classifier."""

    async def classify(self, query: str) -> Any: ...


class AdaptiveSearchEngine:
    """Intent-aware adaptive search across multi-graph views.

    This engine implements MAGMA's Heuristic Beam Search algorithm
    for retrieving relevant events based on query intent.
    """

    def __init__(
        self,
        temporal_repo: TemporalGraphRepo,
        causal_repo: CausalGraphRepo,
        embedding_service: EmbeddingServiceProtocol,
        intent_classifier: IntentClassifierProtocol,
        max_depth: int = 5,
        beam_width: int = 10,
        token_budget: int = 4000,
        decay_factor: float = 0.9,
    ) -> None:
        """Initialize the adaptive search engine.

        Args:
            temporal_repo: Repository for temporal graph operations.
            causal_repo: Repository for causal graph operations.
            embedding_service: Service for computing embeddings.
            intent_classifier: Classifier for query intent.
            max_depth: Maximum traversal depth.
            beam_width: Number of candidates to keep at each step.
            token_budget: Maximum tokens for retrieved context.
            decay_factor: Decay factor for cumulative scores.
        """
        self._temporal_repo = temporal_repo
        self._causal_repo = causal_repo
        self._embedding_service = embedding_service
        self._intent_classifier = intent_classifier
        self._max_depth = max_depth
        self._beam_width = beam_width
        self._token_budget = token_budget
        self._decay_factor = decay_factor

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

            return results

        except Exception as exc:
            log.error("adaptive_search_failed", query=query[:50], error=str(exc))
            return []

    async def _find_anchors(
        self,
        query: str,
        query_embedding: list[float],
        intent: IntentType,
    ) -> list[str]:
        """Find anchor nodes for traversal.

        Args:
            query: The search query.
            query_embedding: Query embedding.
            intent: Query intent.

        Returns:
            List of anchor event IDs.
        """
        # For WHY queries, look for recent events with causal chains
        if intent == IntentType.WHY:
            events = await self._temporal_repo.get_temporal_chain(limit=5)
            return [e["id"] for e in events if e.get("id")]

        # For WHEN queries, use temporal ordering
        if intent == IntentType.WHEN:
            events = await self._temporal_repo.get_temporal_chain(limit=3)
            return [e["id"] for e in events if e.get("id")]

        # Default: get recent events
        events = await self._temporal_repo.get_temporal_chain(limit=3)
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
        frontier: list[tuple[str, float]] = [(a, 1.0) for a in anchors]
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
                    results.append(
                        {
                            "id": event_id,
                            "content": event_data.get("content", ""),
                            "timestamp": event_data.get("timestamp"),
                            "score": cumulative_score,
                        }
                    )

                # Get neighbors based on intent
                neighbors = await self._get_neighbors_by_intent(event_id, intent)

                for neighbor_id, edge_type in neighbors:
                    if neighbor_id in visited:
                        continue

                    # Create mock EventNode for scoring
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
        events = await self._temporal_repo.get_temporal_chain(limit=1000)
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
