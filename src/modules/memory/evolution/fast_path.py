# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Synaptic Ingestion Service (Fast Path).

Latency-sensitive event ingestion that runs synchronously on the
critical path of article processing. Target latency: < 500ms.

Operations performed:
1. Create EventNode from pipeline state
2. Append to Temporal Graph (deterministic)
3. Index embedding in Vector Database
4. Update Entity Graph (deterministic)
5. Trigger Slow Path (non-blocking)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

from core.observability.logging import get_logger
from modules.memory.core.event_node import EventNode

if TYPE_CHECKING:
    from modules.memory.graphs.temporal import TemporalGraphRepo

log = get_logger("synaptic_ingestion")


class VectorRepoProtocol(Protocol):
    """Protocol for vector repository."""

    async def upsert_event_embedding(self, event: EventNode) -> bool: ...


class ConsolidationQueueProtocol(Protocol):
    """Protocol for consolidation queue."""

    async def enqueue(self, event_id: str) -> bool: ...


class EntityGraphRepoProtocol(Protocol):
    """Protocol for entity graph repository."""

    async def link_entities(self, event: EventNode, entities: list[dict[str, Any]]) -> int: ...


class SynapticIngestionService:
    """Fast path service for latency-sensitive event ingestion.

    This service implements the "synaptic ingestion" phase of MAGMA's
    dual-stream memory evolution. It performs only non-blocking operations
    that can complete within strict latency constraints.
    """

    def __init__(
        self,
        temporal_repo: TemporalGraphRepo,
        vector_repo: VectorRepoProtocol | None = None,
        entity_repo: EntityGraphRepoProtocol | None = None,
        consolidation_queue: ConsolidationQueueProtocol | None = None,
    ) -> None:
        """Initialize the synaptic ingestion service.

        Args:
            temporal_repo: Repository for temporal graph operations.
            vector_repo: Repository for vector embedding storage.
            entity_repo: Repository for entity graph operations.
            consolidation_queue: Queue for triggering slow path.
        """
        self._temporal_repo = temporal_repo
        self._vector_repo = vector_repo
        self._entity_repo = entity_repo
        self._queue = consolidation_queue

    async def ingest(self, state: dict[str, Any]) -> EventNode | None:
        """Ingest a pipeline state into memory.

        This is the main entry point for Fast Path ingestion.

        Args:
            state: Pipeline state dictionary from article processing.

        Returns:
            The created EventNode, or None if ingestion failed.
        """
        start_time = time.monotonic()

        # 1. Create EventNode from pipeline state
        event = EventNode.from_pipeline_state(state)
        log.debug("fast_path_event_created", event_id=event.id)

        try:
            # 2. Append to Temporal Graph (deterministic, O(1))
            await self._temporal_repo.append_to_chain(event)

            # 3. Index embedding in Vector Database
            if event.embedding and self._vector_repo:
                await self._vector_repo.upsert_event_embedding(event)

            # 4. Update Entity Graph (deterministic extraction)
            entities = state.get("entities") or []
            if entities and self._entity_repo:
                await self._entity_repo.link_entities(event, entities)

            # 5. Trigger Slow Path (non-blocking)
            if self._queue:
                await self._queue.enqueue(event.id)

            latency_ms = (time.monotonic() - start_time) * 1000
            log.info(
                "fast_path_ingestion_complete",
                event_id=event.id,
                latency_ms=round(latency_ms, 2),
            )

            return event

        except Exception as exc:
            log.error(
                "fast_path_ingestion_failed",
                event_id=event.id,
                error=str(exc),
            )
            return None
