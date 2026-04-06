# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Structural Consolidation Worker (Slow Path).

Background worker for compute-intensive structural inference.
Runs asynchronously via APScheduler, processing events from ConsolidationQueue.

Operations performed:
1. Get 2-hop neighborhood of event
2. LLM Causal Inference
3. Filter by confidence threshold
4. Write to Causal Graph
5. Entity Link Discovery
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from core.observability.logging import get_logger
from modules.memory.core.graph_types import CausalRelationType
from modules.memory.evolution.result import ConsolidationResult

if TYPE_CHECKING:
    from modules.memory.graphs.causal import CausalGraphRepo
    from modules.memory.graphs.temporal import TemporalGraphRepo

    from .queue import ConsolidationQueue

log = get_logger("consolidation_worker")


class LLMClientProtocol(Protocol):
    """Protocol for LLM client."""

    async def call(
        self,
        call_point: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | str: ...


class EntityGraphRepoProtocol(Protocol):
    """Protocol for entity graph repository."""

    async def link_event_to_entities(
        self,
        event_id: str,
        entities: list[dict[str, Any]],
    ) -> int: ...

    async def extract_entities_from_text(
        self,
        text: str,
    ) -> list[dict[str, Any]]: ...


class StructuralConsolidationWorker:
    """Background worker for slow path structural consolidation.

    This worker implements the "structural consolidation" phase of MAGMA's
    dual-stream memory evolution. It runs asynchronously to perform
    compute-intensive LLM inference for causal relationships.
    """

    def __init__(
        self,
        temporal_repo: TemporalGraphRepo,
        causal_repo: CausalGraphRepo,
        consolidation_queue: ConsolidationQueue,
        llm_client: LLMClientProtocol,
        entity_repo: EntityGraphRepoProtocol | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        """Initialize the consolidation worker.

        Args:
            temporal_repo: Repository for temporal graph operations.
            causal_repo: Repository for causal graph operations.
            consolidation_queue: Queue for pending events.
            llm_client: LLM client for causal inference.
            entity_repo: Repository for entity graph operations (optional).
            confidence_threshold: Minimum confidence for storing edges.
        """
        self._temporal_repo = temporal_repo
        self._causal_repo = causal_repo
        self._queue = consolidation_queue
        self._llm = llm_client
        self._entity_repo = entity_repo
        self._confidence_threshold = confidence_threshold

    async def process_event(self, event_id: str) -> ConsolidationResult:
        """Process a single event for consolidation.

        Args:
            event_id: ID of the event to process.

        Returns:
            ConsolidationResult with counts of added edges and links.
        """
        log.info("consolidation_started", event_id=event_id)

        try:
            # 1. Get 2-hop neighborhood
            neighborhood = await self._temporal_repo.get_neighbors(event_id, before=2, after=2)

            if not neighborhood:
                log.debug("consolidation_no_neighbors", event_id=event_id)
                return ConsolidationResult(event_id=event_id)

            # 2. LLM Causal Inference
            causal_edges = await self._infer_causal_relations(event_id, neighborhood)

            # 3. Filter by confidence threshold and write to Causal Graph
            edges_added = 0
            total_confidence = 0.0

            for edge in causal_edges:
                if edge["confidence"] >= self._confidence_threshold:
                    success = await self._causal_repo.add_causal_edge(
                        source_id=edge["source_id"],
                        target_id=edge["target_id"],
                        relation_type=CausalRelationType(edge["relation_type"]),
                        confidence=edge["confidence"],
                        evidence=edge.get("evidence"),
                    )
                    if success:
                        edges_added += 1
                        total_confidence += edge["confidence"]

            # 4. Entity Link Discovery
            entity_links_added = 0
            if self._entity_repo:
                entity_links_added = await self._discover_entity_links(event_id, neighborhood)

            avg_confidence = total_confidence / edges_added if edges_added > 0 else 0.0

            log.info(
                "consolidation_complete",
                event_id=event_id,
                edges_added=edges_added,
                links_added=entity_links_added,
            )

            return ConsolidationResult(
                event_id=event_id,
                causal_edges_added=edges_added,
                entity_links_added=entity_links_added,
                confidence_avg=avg_confidence,
            )

        except Exception as exc:
            log.error(
                "consolidation_failed",
                event_id=event_id,
                error=str(exc),
            )
            return ConsolidationResult(event_id=event_id)

    async def _infer_causal_relations(
        self,
        center_id: str,
        neighborhood: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Use LLM to infer causal relationships.

        Args:
            center_id: ID of the center event.
            neighborhood: List of neighbor events.

        Returns:
            List of inferred causal edges.
        """
        try:
            response = await self._llm.call(
                call_point="CAUSAL_INFERENCE",
                payload={
                    "center_id": center_id,
                    "events": neighborhood,
                    "phase": "causal_inference",
                },
            )

            # Parse LLM response
            if isinstance(response, str):
                import json

                result = json.loads(response)
            else:
                result = response

            return result.get("causal_edges", [])

        except Exception as exc:
            log.warning(
                "causal_inference_failed",
                center_id=center_id,
                error=str(exc),
            )
            return []

    async def process_batch(self, batch_size: int = 10) -> list[ConsolidationResult]:
        """Process a batch of events from the queue.

        Args:
            batch_size: Maximum number of events to process.

        Returns:
            List of ConsolidationResults for processed events.
        """
        results: list[ConsolidationResult] = []

        for _ in range(batch_size):
            event_id = await self._queue.dequeue()
            if event_id is None:
                break

            result = await self.process_event(event_id)
            results.append(result)

        return results

    async def _discover_entity_links(
        self,
        event_id: str,
        neighborhood: list[dict[str, Any]],
    ) -> int:
        """Discover and create entity links for an event.

        Extracts entities from the event's neighborhood content and creates
        MENTIONS relationships between the event and discovered entities.

        Args:
            event_id: ID of the event to process.
            neighborhood: List of neighbor events with content.

        Returns:
            Number of entity links created.
        """
        if not self._entity_repo:
            return 0

        try:
            # Combine content from neighborhood for entity extraction
            combined_text = " ".join(
                event.get("content", "") for event in neighborhood[:5] if event.get("content")
            )

            if not combined_text:
                return 0

            # Extract entities from text
            entities = await self._entity_repo.extract_entities_from_text(combined_text)

            if not entities:
                return 0

            # Create MENTIONS relationships
            links_created = await self._entity_repo.link_event_to_entities(
                event_id=event_id,
                entities=entities,
            )

            if links_created > 0:
                log.debug(
                    "entity_links_discovered",
                    event_id=event_id,
                    links_count=links_created,
                )

            return links_created

        except Exception as exc:
            log.warning(
                "entity_link_discovery_failed",
                event_id=event_id,
                error=str(exc),
            )
            return 0
