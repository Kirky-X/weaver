# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Memory Integration Service - Unified interface for MAGMA memory system.

This service integrates all MAGMA components and provides a single entry point
for pipeline integration and API usage.

Components:
- TemporalGraphRepo: Temporal backbone
- CausalGraphRepo: Causal relationships
- SynapticIngestionService: Fast path ingestion
- StructuralConsolidationWorker: Slow path consolidation
- ConsolidationQueue: Event queue for slow path
- AdaptiveSearchEngine: Intent-aware retrieval
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from core.observability.logging import get_logger
from modules.memory.core.event_node import EventNode
from modules.memory.core.graph_types import IntentType
from modules.memory.evolution.fast_path import SynapticIngestionService
from modules.memory.evolution.queue import ConsolidationQueue
from modules.memory.evolution.result import ConsolidationResult
from modules.memory.evolution.slow_path import StructuralConsolidationWorker
from modules.memory.graphs.causal import CausalGraphRepo
from modules.memory.graphs.temporal import TemporalGraphRepo
from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine

if TYPE_CHECKING:
    from core.db import Neo4jPool
    from core.llm.client import LLMClient
    from modules.knowledge.search.intent.classifier import IntentClassifier

log = get_logger("memory_service")


# Mapping from QueryIntent (knowledge search) to IntentType (memory system)
_QUERY_INTENT_TO_MEMORY_INTENT: dict[str, IntentType] = {
    "why": IntentType.WHY,
    "when": IntentType.WHEN,
    "entity": IntentType.ENTITY,
    "open": IntentType.OPEN,
    "multi_hop": IntentType.OPEN,  # Map MULTI_HOP to OPEN for now
}


class IntentClassifierAdapter:
    """Adapter to convert QueryIntent to IntentType.

    Wraps the existing IntentClassifier and converts its output
    for use with the memory system's AdaptiveSearchEngine.
    """

    def __init__(self, classifier: IntentClassifier) -> None:
        """Initialize the adapter.

        Args:
            classifier: The existing IntentClassifier instance.
        """
        self._classifier = classifier

    async def classify(self, query: str) -> Any:
        """Classify query and convert to memory IntentType.

        Args:
            query: The search query.

        Returns:
            Object with intent field containing IntentType.
        """
        result = await self._classifier.classify(query)

        # Convert QueryIntent to IntentType
        intent_str = result.intent.value if hasattr(result.intent, "value") else str(result.intent)
        memory_intent = _QUERY_INTENT_TO_MEMORY_INTENT.get(intent_str.lower(), IntentType.OPEN)

        # Create a simple object with the intent attribute
        class ClassificationResult:
            intent = memory_intent

        return ClassificationResult()


@dataclass
class MemoryServiceConfig:
    """Configuration for MemoryIntegrationService.

    Maps to MemorySettings in settings.py.
    """

    fast_path_enabled: bool = True
    slow_path_enabled: bool = True
    causal_confidence_threshold: float = 0.7
    max_traversal_depth: int = 5
    beam_width: int = 10
    token_budget: int = 4000


class EmbeddingServiceProtocol(Protocol):
    """Protocol for embedding service."""

    async def embed(self, text: str) -> list[float]: ...


class MemoryIntegrationService:
    """Unified interface for MAGMA multi-graph memory system.

    This service orchestrates all memory components:
    1. Fast Path: Synchronous ingestion with SynapticIngestionService
    2. Slow Path: Background consolidation with StructuralConsolidationWorker
    3. Retrieval: Intent-aware search with AdaptiveSearchEngine

    Usage:
        # Ingest a pipeline state
        event = await memory_service.ingest(pipeline_state)

        # Search with intent
        results = await memory_service.search("Why did X happen?")

        # Run consolidation
        results = await memory_service.consolidate(batch_size=10)
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        llm_client: LLMClient,
        redis_client: Any,
        embedding_service: EmbeddingServiceProtocol,
        intent_classifier: IntentClassifier,
        config: MemoryServiceConfig | None = None,
        vector_repo: Any = None,
        entity_repo: Any = None,
    ) -> None:
        """Initialize the memory integration service.

        Args:
            neo4j_pool: Neo4j connection pool.
            llm_client: LLM client for causal inference.
            redis_client: Redis client for consolidation queue.
            embedding_service: Service for computing embeddings.
            intent_classifier: Classifier for query intent.
            config: Service configuration.
            vector_repo: Optional vector repository for embedding indexing.
            entity_repo: Optional entity graph repository for entity linking.
        """
        self._config = config or MemoryServiceConfig()

        # Initialize repositories
        self._temporal_repo = TemporalGraphRepo(pool=neo4j_pool)
        self._causal_repo = CausalGraphRepo(pool=neo4j_pool)

        # Initialize consolidation queue
        self._consolidation_queue = ConsolidationQueue(redis=redis_client)

        # Initialize fast path with optional repos
        self._fast_path = SynapticIngestionService(
            temporal_repo=self._temporal_repo,
            vector_repo=vector_repo,
            entity_repo=entity_repo,
            consolidation_queue=self._consolidation_queue,
        )

        # Initialize slow path
        self._slow_path = StructuralConsolidationWorker(
            temporal_repo=self._temporal_repo,
            causal_repo=self._causal_repo,
            consolidation_queue=self._consolidation_queue,
            llm_client=llm_client,
            confidence_threshold=self._config.causal_confidence_threshold,
        )

        # Initialize adaptive search with intent classifier adapter
        intent_adapter = IntentClassifierAdapter(intent_classifier)
        self._search_engine = AdaptiveSearchEngine(
            temporal_repo=self._temporal_repo,
            causal_repo=self._causal_repo,
            embedding_service=embedding_service,
            intent_classifier=intent_adapter,
            max_depth=self._config.max_traversal_depth,
            beam_width=self._config.beam_width,
            token_budget=self._config.token_budget,
        )

        # Store for retrieval components
        self._llm_client = llm_client
        self._entity_repo = entity_repo

        # Initialize retrieval components (optional)
        self._entity_aggregator: Any = None
        self._narrative_synthesizer: Any = None
        self._response_builder: Any = None

        if entity_repo is not None:
            from modules.memory.retrieval.entity_aggregator import EntityAggregator
            from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer
            from modules.memory.retrieval.response_builder import SearchResponseBuilder

            self._entity_aggregator = EntityAggregator(
                entity_repo=entity_repo,
                llm=llm_client,
            )
            self._narrative_synthesizer = NarrativeSynthesizer(
                llm=llm_client,
            )
            self._response_builder = SearchResponseBuilder(
                search_engine=self._search_engine,
                entity_aggregator=self._entity_aggregator,
                synthesizer=self._narrative_synthesizer,
                llm=llm_client,
            )

        log.info(
            "memory_service_initialized",
            fast_path_enabled=self._config.fast_path_enabled,
            slow_path_enabled=self._config.slow_path_enabled,
        )

    @property
    def temporal_repo(self) -> TemporalGraphRepo:
        """Get temporal graph repository."""
        return self._temporal_repo

    @property
    def causal_repo(self) -> CausalGraphRepo:
        """Get causal graph repository."""
        return self._causal_repo

    @property
    def search_engine(self) -> AdaptiveSearchEngine:
        """Get adaptive search engine."""
        return self._search_engine

    async def initialize(self) -> None:
        """Initialize the memory system.

        Creates constraints and indexes in Neo4j.
        """
        await self._temporal_repo.ensure_constraints()
        await self._causal_repo.ensure_constraints()
        log.info("memory_constraints_created")

    async def ingest(self, state: dict[str, Any]) -> EventNode | None:
        """Ingest a pipeline state into memory (Fast Path).

        This is the main entry point for synchronous event ingestion.
        It creates an EventNode and adds it to the temporal graph,
        then triggers slow path consolidation.

        Args:
            state: Pipeline state dictionary from article processing.

        Returns:
            The created EventNode, or None if ingestion failed.
        """
        if not self._config.fast_path_enabled:
            log.debug("fast_path_disabled")
            return None

        return await self._fast_path.ingest(state)

    async def consolidate(self, batch_size: int = 10) -> list[ConsolidationResult]:
        """Run slow path consolidation (Slow Path).

        Processes pending events from the consolidation queue,
        inferring causal relationships using LLM.

        Args:
            batch_size: Maximum number of events to process.

        Returns:
            List of ConsolidationResults for processed events.
        """
        if not self._config.slow_path_enabled:
            log.debug("slow_path_disabled")
            return []

        return await self._slow_path.process_batch(batch_size)

    async def search(
        self,
        query: str,
        anchors: list[str] | None = None,
        intent: IntentType | None = None,
    ) -> list[dict[str, Any]]:
        """Search memory with intent-aware retrieval.

        Uses MAGMA's Heuristic Beam Search to find relevant events
        based on query intent.

        Args:
            query: The search query.
            anchors: Optional list of anchor event IDs.
            intent: Optional pre-classified intent.

        Returns:
            List of relevant events with scores.
        """
        return await self._search_engine.search(query, anchors, intent)

    async def search_with_context(
        self,
        query: str,
        anchors: list[str] | None = None,
        intent: IntentType | None = None,
        output_mode: str = "context",
        enrich_entities: bool = False,
    ) -> dict[str, Any]:
        """Search memory with enriched context and narrative synthesis.

        This method extends the basic search with:
        - Entity aggregation (if enrich_entities=True)
        - Narrative synthesis for coherent response

        Args:
            query: The search query.
            anchors: Optional list of anchor event IDs.
            intent: Optional pre-classified intent.
            output_mode: "context" for raw snippets, "narrative" for LLM synthesis.
            enrich_entities: Whether to enrich results with entity information.

        Returns:
            Dictionary containing:
            - results: List of relevant events
            - synthesis: Synthesized narrative (if output_mode="narrative")
            - entities: Aggregated entity info (if enrich_entities=True)

        Raises:
            RuntimeError: If retrieval components are not initialized.
        """
        if self._response_builder is None:
            raise RuntimeError(
                "search_with_context() requires entity_repo to be injected. "
                "Initialize MemoryIntegrationService with entity_repo parameter."
            )

        from modules.memory.core.graph_types import OutputMode

        mode = OutputMode.NARRATIVE if output_mode == "narrative" else OutputMode.CONTEXT

        return await self._response_builder.build(
            query=query,
            output_mode=mode,
            enrich_entities=enrich_entities,
        )

    async def get_queue_depth(self) -> int:
        """Get the number of pending consolidation events.

        Returns:
            Queue depth.
        """
        return await self._consolidation_queue.length()

    async def health_check(self) -> dict[str, Any]:
        """Check health of memory system components.

        Returns:
            Health status dictionary.
        """
        queue_depth = await self.get_queue_depth()

        return {
            "status": "healthy",
            "fast_path_enabled": self._config.fast_path_enabled,
            "slow_path_enabled": self._config.slow_path_enabled,
            "queue_depth": queue_depth,
        }
