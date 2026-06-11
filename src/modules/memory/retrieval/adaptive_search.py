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

from core.observability import get_logger
from modules.knowledge.search.rerankers.beam_search_reranker import BeamSearchReranker
from modules.memory.core.event_node import EventNode
from modules.memory.core.graph_types import EdgeType, IntentType
from modules.memory.core.traversal import calculate_transition_score

if TYPE_CHECKING:
    from core.protocols import KnowledgeCacheProtocol
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


class _IntentGraphAdapter:
    """Adapter wrapping temporal/causal repos as a graph for BeamSearchReranker.

    Provides get_neighbors(entity_id) that returns scored neighbor dicts
    compatible with BeamSearchReranker's expansion logic.
    """

    def __init__(
        self,
        temporal_repo: Any,
        causal_repo: Any,
        query_embedding: list[float],
        intent: IntentType,
        event_cache: dict[str, dict[str, Any]] | None,
    ) -> None:
        self._temporal_repo = temporal_repo
        self._causal_repo = causal_repo
        self._query_embedding = query_embedding
        self._intent = intent
        self._event_cache = event_cache

    def get_neighbors(self, entity_id: str) -> list[dict[str, Any]]:
        """Get scored neighbors for an entity (synchronous wrapper).

        Note: This is a synchronous interface for BeamSearchReranker.
        The async neighbor fetching is done during _beam_search setup.
        """
        # Return empty — actual expansion is handled via _expand_neighbors
        return self._cached_neighbors.get(entity_id, [])

    def set_cached_neighbors(self, neighbors: dict[str, list[dict[str, Any]]]) -> None:
        """Pre-populate neighbor cache for synchronous access."""
        self._cached_neighbors = neighbors


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
        self._event_cache: dict[str, dict[str, Any]] | None = None
        self._reranker = BeamSearchReranker(
            beam_width=beam_width,
            decay_factor=decay_factor,
            expansion_weight=1.0 - decay_factor,
        )

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

            from core.protocols import KnowledgeCluster

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
        """Execute heuristic beam search traversal using BeamSearchReranker.

        Args:
            anchors: Starting anchor event IDs.
            query_embedding: Query embedding vector.
            intent: Query intent type.

        Returns:
            List of retrieved events with scores.
        """
        # Pre-fetch temporal chain into cache to avoid N+1 queries
        all_events = await self._temporal_repo.get_temporal_chain(limit=self._event_lookup_limit)
        self._event_cache = {e["id"]: e for e in all_events if e.get("id")}

        # Score anchors based on content relevance
        candidates: list[dict[str, Any]] = []
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
                candidates.append(
                    {
                        "id": anchor_id,
                        "fusion_score": anchor_score,
                        "content": event_data.get("content", ""),
                        "timestamp": event_data.get("timestamp"),
                    }
                )
            else:
                candidates.append(
                    {
                        "id": anchor_id,
                        "fusion_score": 0.5,
                        "content": "",
                    }
                )

        # Pre-fetch neighbors for all events and build graph adapter
        neighbor_cache = await self._prefetch_neighbors(candidates, intent, query_embedding)
        graph_adapter = _IntentGraphAdapter(
            temporal_repo=self._temporal_repo,
            causal_repo=self._causal_repo,
            query_embedding=query_embedding,
            intent=intent,
            event_cache=self._event_cache,
        )
        graph_adapter.set_cached_neighbors(neighbor_cache)

        # Use BeamSearchReranker for traversal
        reranked = self._reranker.rerank(
            query="",
            candidates=candidates,
            graph=graph_adapter,
            depth=self._max_depth,
        )

        # Build results from reranked output
        results: list[dict[str, Any]] = []
        for item in reranked:
            event_id = item.get("id", "")
            event_data = await self._get_event_data(event_id)
            content = ""
            timestamp = None
            if event_data:
                content = event_data.get("content", "")
                timestamp = event_data.get("timestamp")
            elif item.get("content"):
                content = item["content"]
                timestamp = item.get("timestamp")

            if content.strip():
                results.append(
                    {
                        "id": event_id,
                        "content": content,
                        "timestamp": timestamp,
                        "score": item.get("cumulative_score", item.get("fusion_score", 0.0)),
                    }
                )

            # Token budget check
            if self._estimate_tokens(results) >= self._token_budget:
                break

        return results

    async def _prefetch_neighbors(
        self,
        candidates: list[dict[str, Any]],
        intent: IntentType,
        query_embedding: list[float],
    ) -> dict[str, list[dict[str, Any]]]:
        """Pre-fetch and score neighbors for all candidate entities.

        Args:
            candidates: List of candidate dicts with id field.
            intent: Query intent type.
            query_embedding: Query embedding vector for scoring.

        Returns:
            Dict mapping entity_id to list of scored neighbor dicts.
        """
        neighbor_cache: dict[str, list[dict[str, Any]]] = {}

        for candidate in candidates:
            entity_id = candidate.get("id", "")
            if not entity_id:
                continue

            try:
                neighbors = await self._get_neighbors_by_intent(entity_id, intent)
            except Exception as exc:
                log.warning("prefetch_neighbors_failed", entity_id=entity_id, error=str(exc))
                neighbor_cache[entity_id] = []
                continue

            scored_neighbors = []
            for neighbor_id, edge_type in neighbors:
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
                scored_neighbors.append(
                    {
                        "id": neighbor_id,
                        "fusion_score": score,
                    }
                )

            neighbor_cache[entity_id] = scored_neighbors

        return neighbor_cache

    async def _get_event_data(self, event_id: str) -> dict[str, Any] | None:
        """Get event data by ID.

        Uses pre-fetched event cache when available (set by _beam_search),
        falling back to temporal chain query otherwise.

        Args:
            event_id: Event ID.

        Returns:
            Event data dictionary or None.
        """
        # Fast path: check cache first
        if self._event_cache is not None and event_id in self._event_cache:
            return self._event_cache[event_id]

        # Fallback: query temporal repo
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
