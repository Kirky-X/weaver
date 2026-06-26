# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Temporal Graph Repository.

Manages EVENT_FOLLOWED_BY edges representing chronological ordering of events.
This is the immutable temporal backbone of MAGMA's memory system.
"""

from __future__ import annotations

import json
import time
from typing import Any

from core.constants import DatabaseType
from core.observability import get_logger
from modules.memory.core.event_node import EventNode
from modules.memory.graphs.base import BaseGraphRepo

log = get_logger(__name__)


class TemporalGraphRepo(BaseGraphRepo):
    """Repository for temporal graph operations.

    The Temporal Graph provides the ground truth for chronological reasoning.
    Edges are strictly ordered pairs (n_i, n_j) where τ_i < τ_j.

    Supports both Neo4j and LadybugDB backends by detecting pool type
    and using appropriate query syntax.
    """

    def __init__(self, pool) -> None:
        """Initialize with graph pool.

        Args:
            pool: Graph database connection pool (Neo4j or LadybugDB).
        """
        super().__init__(pool)
        self._is_ladybug = pool.database_type == DatabaseType.LADYBUG.value

    async def ensure_constraints(self) -> None:
        """Create EventNode constraints and indexes."""
        if self._is_ladybug:
            # LadybugDB schema is created via separate schema initialization
            log.debug("temporal_constraints_skip_ladybug")
            return

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
        in the chain via EVENT_FOLLOWED_BY relationship.

        Args:
            event: The event node to append.

        Returns:
            True if successful, False otherwise.
        """
        if self._is_ladybug:
            return await self._append_to_chain_ladybug(event)
        return await self._append_to_chain_neo4j(event)

    async def _append_to_chain_neo4j(self, event: EventNode) -> bool:
        """Append event using Neo4j-specific syntax."""
        query = """
        // Create the new EventNode
        MERGE (e:EventNode {id: $id})
        ON CREATE SET
            e.content = $content,
            e.timestamp = datetime($timestamp),
            e.created_at = datetime(),
            e.attributes = $attributes
        ON MATCH SET
            e.updated_at = datetime()

        // Pass created node to next clause
        WITH e

        // Find the most recent event (if any)
        OPTIONAL MATCH (prev:EventNode)
        WHERE NOT (prev)-[:EVENT_FOLLOWED_BY]->(:EventNode)
          AND prev.timestamp < datetime($timestamp)

        // Create EVENT_FOLLOWED_BY relationship
        WITH e, prev
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            CREATE (prev)-[r:EVENT_FOLLOWED_BY {
                time_gap_hours: duration.between(prev.timestamp, datetime($timestamp)).hours
            }]->(e)
        )

        RETURN e.id AS created
        """

        params = {
            "id": event.id,
            "content": event.content,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "attributes": json.dumps(event.attributes) if event.attributes else None,
        }

        try:
            result = await self._pool.execute_query(query, params)
            log.info("temporal_event_appended", event_id=event.id)
            return bool(result)
        except Exception as exc:
            log.error("temporal_append_failed", event_id=event.id, error=str(exc))
            return False

    async def _append_to_chain_ladybug(self, event: EventNode) -> bool:
        """Append event using LadybugDB-compatible syntax.

        LadybugDB uses INT64 timestamps instead of datetime functions.
        """
        now = int(time.time())
        event_time = int(event.timestamp.timestamp()) if event.timestamp else now

        # Check if event already exists
        check_query = """
        MATCH (e:EventNode {id: $id})
        RETURN e.id
        """
        try:
            existing = await self._pool.execute_query(check_query, {"id": event.id})
            if existing:
                log.debug("temporal_event_exists", event_id=event.id)
                return True
        except Exception:
            log.warning("temporal_event_exists_check_failed", event_id=event.id, exc_info=True)
            pass  # Continue to create

        # Find the most recent event
        find_prev_query = """
        MATCH (prev:EventNode)
        WHERE NOT (prev)-[:EVENT_FOLLOWED_BY]->(:EventNode)
        RETURN prev.id AS prev_id, prev.event_time AS prev_time
        ORDER BY prev.event_time DESC
        LIMIT 1
        """

        prev_result = []
        try:
            prev_result = await self._pool.execute_query(find_prev_query)
        except Exception:
            log.warning("find_previous_event_failed", exc_info=True)
            pass  # No previous events

        # Create new event node
        create_query = """
        CREATE (e:EventNode {
            id: $id,
            content: $content,
            event_time: $event_time,
            created_at: $created_at,
            attributes: $attributes
        })
        RETURN e.id
        """

        create_params = {
            "id": event.id,
            "content": event.content,
            "event_time": event_time,
            "created_at": now,
            "attributes": json.dumps(event.attributes) if event.attributes else None,
        }

        try:
            await self._pool.execute_query(create_query, create_params)

            # Create EVENT_FOLLOWED_BY relationship if there was a previous event
            if prev_result and prev_result[0].get("prev_id"):
                prev_id = prev_result[0]["prev_id"]
                prev_time = prev_result[0].get("prev_time", event_time)
                time_gap_hours = (event_time - prev_time) / 3600.0 if prev_time else 0.0

                link_query = """
                MATCH (prev:EventNode {id: $prev_id})
                MATCH (curr:EventNode {id: $curr_id})
                CREATE (prev)-[r:EVENT_FOLLOWED_BY {time_gap_hours: $time_gap}]->(curr)
                """
                await self._pool.execute_query(
                    link_query,
                    {
                        "prev_id": prev_id,
                        "curr_id": event.id,
                        "time_gap": time_gap_hours,
                    },
                )

            log.info("temporal_event_appended", event_id=event.id)
            return True

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
        # LadybugDB uses event_time (INT64), Neo4j uses timestamp (datetime)
        time_field = "event_time" if self._is_ladybug else "timestamp"

        query = f"""
        MATCH (e:EventNode)
        RETURN e.id AS id,
               e.content AS content,
               e.{time_field} AS timestamp,
               e.attributes AS attributes
        ORDER BY e.{time_field} ASC
        SKIP $offset
        LIMIT $limit
        """

        params = {"limit": limit, "offset": offset}
        results = await self._pool.execute_query(query, params)

        # Parse JSON string attributes back to dict
        for record in results:
            attr = record.get("attributes")
            if isinstance(attr, str):
                try:
                    record["attributes"] = json.loads(attr)
                except (json.JSONDecodeError, TypeError):
                    pass
        return results

    async def search_temporal_events(
        self,
        query: str,
        limit: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Search events by content similarity and return in temporal order.

        Args:
            query: Search query string.
            limit: Maximum number of events to return.
            query_embedding: Optional query embedding for semantic ranking.
                When provided, callers can use it to re-rank results by
                computing cosine similarity against event content embeddings.

        Returns:
            List of event dictionaries matching query, ordered by timestamp.
        """
        # LadybugDB uses event_time (INT64), Neo4j uses timestamp (datetime)
        time_field = "event_time" if self._is_ladybug else "timestamp"

        # Simple content-based search (CONTAINS is case-sensitive in Neo4j)
        # Use toLower for case-insensitive matching
        query_cypher = f"""
        MATCH (e:EventNode)
        WHERE toLower(e.content) CONTAINS toLower($query)
        RETURN e.id AS id,
               e.content AS content,
               e.{time_field} AS timestamp,
               e.attributes AS attributes
        ORDER BY e.{time_field} ASC
        LIMIT $limit
        """

        params = {"query": query, "limit": limit}
        results = await self._pool.execute_query(query_cypher, params)

        # Parse JSON string attributes back to dict
        for record in results:
            attr = record.get("attributes")
            if isinstance(attr, str):
                try:
                    record["attributes"] = json.loads(attr)
                except (json.JSONDecodeError, TypeError):
                    pass
        return results

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
        # LadybugDB uses event_time (INT64), Neo4j uses timestamp (datetime)
        time_field = "event_time" if self._is_ladybug else "timestamp"

        query = f"""
        MATCH (center:EventNode {{id: $event_id}})

        // Get preceding events
        OPTIONAL MATCH (prev:EventNode)-[:EVENT_FOLLOWED_BY*1..{before}]->(center)
        WITH center, collect(DISTINCT {{
            id: prev.id,
            content: prev.content,
            timestamp: prev.{time_field},
            direction: 'previous'
        }}) AS prev_neighbors

        // Get following events
        OPTIONAL MATCH (center)-[:EVENT_FOLLOWED_BY*1..{after}]->(next:EventNode)
        WITH prev_neighbors, collect(DISTINCT {{
            id: next.id,
            content: next.content,
            timestamp: next.{time_field},
            direction: 'next'
        }}) AS next_neighbors

        UNWIND prev_neighbors + next_neighbors AS neighbor
        RETURN neighbor
        ORDER BY neighbor.timestamp
        """

        params = {"event_id": event_id}
        result = await self._pool.execute_query(query, params)
        return [r.get("neighbor", r) for r in result]

    async def count_events(self) -> int:
        """Count total EventNodes in the temporal graph.

        Returns:
            Total count of EventNode nodes.
        """
        query = "MATCH (e:EventNode) RETURN count(e) as count"
        result = await self._pool.execute_query(query, {})
        if result and len(result) > 0:
            return int(result[0].get("count", 0))
        return 0
