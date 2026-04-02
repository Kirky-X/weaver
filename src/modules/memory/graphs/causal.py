# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Causal Graph Repository.

Manages CAUSES, ENABLES, and PREVENTS edges representing causal relationships
between events. This is the core of MAGMA's causal reasoning capability.
"""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger
from modules.memory.core.graph_types import CausalRelationType
from modules.memory.graphs.base import BaseGraphRepo

log = get_logger("causal_repo")


class CausalGraphRepo(BaseGraphRepo):
    """Repository for causal graph operations.

    The Causal Graph enables "Why?" queries by storing LLM-inferred
    causal relationships between events.
    """

    def __init__(self, pool: Any, confidence_threshold: float = 0.7) -> None:
        """Initialize causal repository.

        Args:
            pool: Neo4j connection pool.
            confidence_threshold: Minimum confidence for storing edges.
        """
        super().__init__(pool)
        self._confidence_threshold = confidence_threshold

    async def ensure_constraints(self) -> None:
        """Create indexes for causal edges."""
        indexes = [
            """
            CREATE INDEX causal_source_idx IF NOT EXISTS
            FOR ()-[r:CAUSES|ENABLES|PREVENTS]-() ON r.confidence
            """,
        ]

        for index in indexes:
            try:
                await self._pool.execute_query(index)
                log.debug("causal_index_created")
            except Exception as exc:
                log.debug("causal_index_check", error=str(exc))

    async def add_causal_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: CausalRelationType,
        confidence: float,
        evidence: str | None = None,
    ) -> bool:
        """Add a causal edge between two events.

        Args:
            source_id: Source event ID (cause).
            target_id: Target event ID (effect).
            relation_type: Type of causal relationship.
            confidence: Confidence score (0.0-1.0).
            evidence: Explanation for the relationship.

        Returns:
            True if edge was created, False if filtered or failed.
        """
        # Filter by confidence threshold
        if confidence < self._confidence_threshold:
            log.debug(
                "causal_edge_filtered",
                source=source_id,
                target=target_id,
                confidence=confidence,
                threshold=self._confidence_threshold,
            )
            return False

        rel_type = relation_type.value
        query = f"""
        MATCH (source:EventNode {{id: $source_id}})
        MATCH (target:EventNode {{id: $target_id}})
        MERGE (source)-[r:{rel_type}]->(target)
        ON CREATE SET
            r.confidence = $confidence,
            r.evidence = $evidence,
            r.created_at = datetime()
        ON MATCH SET
            r.confidence = CASE WHEN $confidence > r.confidence THEN $confidence ELSE r.confidence END,
            r.evidence = CASE WHEN $evidence IS NOT NULL THEN $evidence ELSE r.evidence END,
            r.updated_at = datetime()
        RETURN r
        """

        params = {
            "source_id": source_id,
            "target_id": target_id,
            "confidence": confidence,
            "evidence": evidence,
        }

        try:
            result = await self._pool.execute_query(query, params)
            log.info(
                "causal_edge_created",
                source=source_id,
                target=target_id,
                type=rel_type,
                confidence=confidence,
            )
            return bool(result)
        except Exception as exc:
            log.error(
                "causal_edge_failed",
                source=source_id,
                target=target_id,
                error=str(exc),
            )
            return False

    async def get_causal_chain(
        self,
        event_id: str,
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        """Get the causal chain leading to an event.

        Args:
            event_id: The target event.
            max_depth: Maximum traversal depth.

        Returns:
            List of events in the causal chain.
        """
        query = f"""
        MATCH path = (cause:EventNode)-[:CAUSES|ENABLES*1..{max_depth}]->(effect:EventNode {{id: $event_id}})
        UNWIND nodes(path) AS node
        WITH DISTINCT node
        RETURN node.id AS id,
               node.content AS content,
               node.timestamp AS timestamp
        """

        params = {"event_id": event_id}
        return await self._pool.execute_query(query, params)

    async def get_causes(self, event_id: str) -> list[dict[str, Any]]:
        """Get all events that caused this event.

        Args:
            event_id: The target event.

        Returns:
            List of cause events with relationship metadata.
        """
        query = """
        MATCH (cause:EventNode)-[r:CAUSES|ENABLES]->(effect:EventNode {id: $event_id})
        RETURN cause.id AS id,
               cause.content AS content,
               cause.timestamp AS timestamp,
               type(r) AS relation_type,
               r.confidence AS confidence,
               r.evidence AS evidence
        ORDER BY r.confidence DESC
        """

        params = {"event_id": event_id}
        return await self._pool.execute_query(query, params)

    async def get_effects(self, event_id: str) -> list[dict[str, Any]]:
        """Get all events that this event caused.

        Args:
            event_id: The source event.

        Returns:
            List of effect events with relationship metadata.
        """
        query = """
        MATCH (cause:EventNode {id: $event_id})-[r:CAUSES|ENABLES]->(effect:EventNode)
        RETURN effect.id AS id,
               effect.content AS content,
               effect.timestamp AS timestamp,
               type(r) AS relation_type,
               r.confidence AS confidence,
               r.evidence AS evidence
        ORDER BY r.confidence DESC
        """

        params = {"event_id": event_id}
        return await self._pool.execute_query(query, params)
