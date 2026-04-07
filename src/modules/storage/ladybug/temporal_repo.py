# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB temporal repository for event chain operations.

LadybugDB is a Kuzu fork with Cypher support. Key differences from Neo4j:
- No datetime() function - use INT64 timestamp integers
- No elementId() function - use id property as string
- No duration.between() - calculate time gaps in application code
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from core.observability.logging import get_logger
from core.protocols import GraphPool

log = get_logger("ladybug_temporal_repo")


class LadybugTemporalRepo:
    """LadybugDB temporal repository.

    Handles temporal event chain operations in LadybugDB graph database.
    Uses INT64 timestamps instead of Neo4j datetime functions.

    Implements:
        - TemporalGraphRepo: Event chain and temporal reasoning operations

    Args:
        pool: Graph database connection pool.
    """

    def __init__(self, pool: GraphPool) -> None:
        self._pool = pool

    async def ensure_constraints(self) -> None:
        """Create EventNode constraints and indexes.

        Note: LadybugDB schema is created via schema.py initialization.
        This method is a no-op for compatibility.
        """
        pass  # Schema is initialized separately

    async def append_to_chain(
        self,
        event_id: str | None = None,
        content: str | None = None,
        timestamp: int | None = None,
        event_type: str | None = None,
        name: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> bool:
        """Append an event to the temporal chain.

        Creates the EventNode and links it to the previous event
        in the chain via FOLLOWED_BY relationship.

        Args:
            event_id: Optional event ID (auto-generated if not provided).
            content: Event content/description.
            timestamp: Event timestamp as INT64 (auto-generated if not provided).
            event_type: Type of event.
            name: Event name.
            attributes: Additional attributes.

        Returns:
            True if successful, False otherwise.
        """

        now = int(time.time())
        event_id = event_id or str(uuid.uuid4())
        timestamp = timestamp or now

        # Check if event already exists
        check_query = """
        MATCH (e:EventNode {id: $id})
        RETURN e.id
        """
        existing = await self._pool.execute_query(check_query, {"id": event_id})
        if existing:
            log.debug("temporal_event_exists", event_id=event_id)
            return True

        # Find the most recent event
        find_prev_query = """
        MATCH (prev:EventNode)
        WHERE NOT (prev)-[:FOLLOWED_BY]->(:EventNode)
        RETURN prev.id AS prev_id, prev.event_time AS prev_time
        ORDER BY prev.event_time DESC
        LIMIT 1
        """
        prev_result = await self._pool.execute_query(find_prev_query)

        # Create new event node
        create_query = """
        CREATE (e:EventNode {
            id: $id,
            event_type: $event_type,
            name: $name,
            description: $description,
            event_time: $event_time,
            created_at: $created_at
        })
        RETURN e.id
        """
        create_params = {
            "id": event_id,
            "event_type": event_type or "generic",
            "name": name or "",
            "description": content or "",
            "event_time": timestamp,
            "created_at": now,
        }

        try:
            await self._pool.execute_query(create_query, create_params)

            # Create FOLLOWED_BY relationship if there was a previous event
            if prev_result and prev_result[0].get("prev_id"):
                prev_id = prev_result[0]["prev_id"]
                prev_time = prev_result[0].get("prev_time", timestamp)
                time_gap_hours = (timestamp - prev_time) / 3600.0 if prev_time else 0.0

                link_query = """
                MATCH (prev:EventNode {id: $prev_id})
                MATCH (curr:EventNode {id: $curr_id})
                CREATE (prev)-[r:FOLLOWED_BY {time_gap_hours: $time_gap}]->(curr)
                """
                await self._pool.execute_query(
                    link_query,
                    {
                        "prev_id": prev_id,
                        "curr_id": event_id,
                        "time_gap": time_gap_hours,
                    },
                )

            log.info("temporal_event_appended", event_id=event_id)
            return True

        except Exception as exc:
            log.error("temporal_append_failed", event_id=event_id, error=str(exc))
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
            List of event dictionaries ordered by event_time.
        """
        query = """
        MATCH (e:EventNode)
        RETURN e.id AS id,
               e.event_type AS event_type,
               e.name AS name,
               e.description AS content,
               e.event_time AS timestamp,
               e.created_at AS created_at
        ORDER BY e.event_time ASC
        SKIP $offset
        LIMIT $limit
        """

        params = {"limit": limit, "offset": offset}
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

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
        neighbors = []

        # Get preceding events
        if before > 0:
            prev_query = f"""
            MATCH (prev:EventNode)-[:FOLLOWED_BY*1..{before}]->(curr:EventNode {{id: $event_id}})
            RETURN DISTINCT prev.id AS id,
                   prev.event_type AS event_type,
                   prev.name AS name,
                   prev.description AS content,
                   prev.event_time AS timestamp,
                   'previous' AS direction
            ORDER BY prev.event_time DESC
            LIMIT $before
            """
            prev_result = await self._pool.execute_query(
                prev_query, {"event_id": event_id, "before": before}
            )
            neighbors.extend([dict(r) for r in prev_result])

        # Get following events
        if after > 0:
            next_query = f"""
            MATCH (curr:EventNode {{id: $event_id}})-[:FOLLOWED_BY*1..{after}]->(next:EventNode)
            RETURN DISTINCT next.id AS id,
                   next.event_type AS event_type,
                   next.name AS name,
                   next.description AS content,
                   next.event_time AS timestamp,
                   'next' AS direction
            ORDER BY next.event_time ASC
            LIMIT $after
            """
            next_result = await self._pool.execute_query(
                next_query, {"event_id": event_id, "after": after}
            )
            neighbors.extend([dict(r) for r in next_result])

        # Sort by timestamp
        neighbors.sort(key=lambda x: x.get("timestamp", 0))
        return neighbors

    async def get_event_by_id(self, event_id: str) -> dict[str, Any] | None:
        """Get an event by its ID.

        Args:
            event_id: The event ID.

        Returns:
            Event dict if found, None otherwise.
        """
        query = """
        MATCH (e:EventNode {id: $id})
        RETURN e.id AS id,
               e.event_type AS event_type,
               e.name AS name,
               e.description AS content,
               e.event_time AS timestamp,
               e.created_at AS created_at
        """
        result = await self._pool.execute_query(query, {"id": event_id})
        if result:
            return dict(result[0])
        return None

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event by its ID.

        Args:
            event_id: The event ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        query = """
        MATCH (e:EventNode {id: $id})
        DELETE e
        """
        try:
            await self._pool.execute_query(query, {"id": event_id})
            return True
        except Exception:
            return False

    async def count_events(self) -> int:
        """Count total events in the temporal chain.

        Returns:
            Total number of EventNode records.
        """
        query = """
        MATCH (e:EventNode)
        RETURN COUNT(e) AS count
        """
        result = await self._pool.execute_query(query)
        return result[0]["count"] if result else 0

    async def get_events_by_timerange(
        self,
        start_time: int,
        end_time: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get events within a time range.

        Args:
            start_time: Start timestamp (INT64).
            end_time: End timestamp (INT64).
            limit: Maximum number of events to return.

        Returns:
            List of events within the time range.
        """
        query = """
        MATCH (e:EventNode)
        WHERE e.event_time >= $start_time AND e.event_time <= $end_time
        RETURN e.id AS id,
               e.event_type AS event_type,
               e.name AS name,
               e.description AS content,
               e.event_time AS timestamp,
               e.created_at AS created_at
        ORDER BY e.event_time ASC
        LIMIT $limit
        """
        params = {
            "start_time": start_time,
            "end_time": end_time,
            "limit": limit,
        }
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]
