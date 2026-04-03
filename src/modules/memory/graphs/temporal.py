# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Temporal Graph Repository.

Manages FOLLOWED_BY edges representing chronological ordering of events.
This is the immutable temporal backbone of MAGMA's memory system.
"""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger
from modules.memory.core.event_node import EventNode
from modules.memory.graphs.base import BaseGraphRepo

log = get_logger("temporal_repo")


class TemporalGraphRepo(BaseGraphRepo):
    """Repository for temporal graph operations.

    The Temporal Graph provides the ground truth for chronological reasoning.
    Edges are strictly ordered pairs (n_i, n_j) where τ_i < τ_j.
    """

    async def ensure_constraints(self) -> None:
        """Create EventNode constraints and indexes."""
        constraints = [
            # EventNode uniqueness
            """
            CREATE CONSTRAINT event_node_id_unique IF NOT EXISTS
            FOR (e:EventNode) REQUIRE e.id IS UNIQUE
            """,
            # Timestamp index for temporal queries
            """
            CREATE INDEX event_node_timestamp IF NOT EXISTS
            FOR (e:EventNode) ON (e.timestamp)
            """,
        ]

        for constraint in constraints:
            try:
                await self._pool.execute_query(constraint)
                log.debug("temporal_constraint_created", constraint=constraint[:50])
            except Exception as exc:
                log.debug("temporal_constraint_check", error=str(exc))

    async def append_to_chain(self, event: EventNode) -> bool:
        """Append an event to the temporal chain.

        Creates the EventNode and links it to the previous event
        in the chain via FOLLOWED_BY relationship.

        Args:
            event: The event node to append.

        Returns:
            True if successful, False otherwise.
        """
        query = """
        // Create the new EventNode
        MERGE (e:EventNode {id: $id})
        ON CREATE SET
            e.content = $content,
            e.timestamp = datetime($timestamp),
            e.created_at = datetime(),
            e += $attributes
        ON MATCH SET
            e.updated_at = datetime()

        // Find the most recent event (if any)
        OPTIONAL MATCH (prev:EventNode)
        WHERE NOT (prev)-[:FOLLOWED_BY]->(:EventNode)
          AND prev.timestamp < datetime($timestamp)

        // Create FOLLOWED_BY relationship
        WITH e, prev
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            CREATE (prev)-[r:FOLLOWED_BY {
                time_gap_hours: duration.between(prev.timestamp, datetime($timestamp)).hours
            }]->(e)
        )

        RETURN e.id AS created
        """

        params = {
            "id": event.id,
            "content": event.content,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "attributes": event.attributes,
        }

        try:
            result = await self._pool.execute_query(query, params)
            log.info("temporal_event_appended", event_id=event.id)
            return bool(result)
        except Exception as exc:
            log.error("temporal_append_failed", event_id=event.id, error=str(exc))
            return False

    async def get_temporal_chain(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get the temporal chain of events in chronological order.

        Args:
            limit: Maximum number of events to return.
            offset: Number of events to skip.

        Returns:
            List of event dictionaries ordered by timestamp.
        """
        query = """
        MATCH (e:EventNode)
        RETURN e.id AS id,
               e.content AS content,
               e.timestamp AS timestamp,
               e.attributes AS attributes
        ORDER BY e.timestamp ASC
        SKIP $offset
        LIMIT $limit
        """

        params = {"limit": limit, "offset": offset}
        return await self._pool.execute_query(query, params)

    async def get_neighbors(
        self,
        event_id: str,
        before: int = 1,
        after: int = 1,
    ) -> list[dict[str, Any]]:
        """Get temporal neighbors of an event.

        Args:
            event_id: The event to find neighbors for.
            before: Number of preceding events.
            after: Number of following events.

        Returns:
            List of neighbor events with direction indicator.
        """
        query = f"""
        MATCH (center:EventNode {{id: $event_id}})

        // Get preceding events
        OPTIONAL MATCH (prev:EventNode)-[:FOLLOWED_BY*1..{before}]->(center)
        WITH center, collect(DISTINCT {{
            id: prev.id,
            content: prev.content,
            timestamp: prev.timestamp,
            direction: 'previous'
        }}) AS prev_neighbors

        // Get following events
        OPTIONAL MATCH (center)-[:FOLLOWED_BY*1..{after}]->(next:EventNode)
        WITH prev_neighbors, collect(DISTINCT {{
            id: next.id,
            content: next.content,
            timestamp: next.timestamp,
            direction: 'next'
        }}) AS next_neighbors

        UNWIND prev_neighbors + next_neighbors AS neighbor
        RETURN neighbor
        ORDER BY neighbor.timestamp
        """

        params = {"event_id": event_id}
        result = await self._pool.execute_query(query, params)
        return [r.get("neighbor", r) for r in result]
