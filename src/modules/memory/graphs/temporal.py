# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Temporal Graph Repository.

Manages EVENT_FOLLOWED_BY edges representing chronological ordering of events.
This is the immutable temporal backbone of MAGMA's memory system.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from core.constants import DatabaseType
from core.observability import get_logger
from modules.memory.core.event_node import EventNode
from modules.memory.core.traversal import _cosine_similarity
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
            e.attributes = $attributes,
            e.embedding = $embedding
        ON MATCH SET
            e.updated_at = datetime(),
            e.embedding = CASE WHEN $embedding IS NOT NULL THEN $embedding ELSE e.embedding END

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
            # D2 / Task 6.2-6.3: persist embedding when available (from
            # state.vectors.content via EventNode.from_pipeline_state).
            # None for legacy pipeline states without vectors — write does
            # not fail (Neo4j accepts null property).
            "embedding": event.embedding,
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
            attributes: $attributes,
            embedding: $embedding
        })
        RETURN e.id
        """

        create_params = {
            "id": event.id,
            "content": event.content,
            "event_time": event_time,
            "created_at": now,
            "attributes": json.dumps(event.attributes) if event.attributes else None,
            # D2 / Task 6.2-6.3: persist embedding when available.
            # LadybugDB stores as DOUBLE[] (see ladybug_schema.py).
            # None for legacy pipeline states without vectors — write does
            # not fail (LadybugDB accepts null property).
            "embedding": event.embedding,
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
               e.attributes AS attributes,
               e.embedding AS embedding
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
        start_time: int | None = None,
        end_time: int | None = None,
        embedding_service: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Search events by content similarity and return ranked by relevance.

        Implements D1 hybrid strategy: when ``query_embedding`` is provided,
        CONTAINS is used to fetch candidates (avoiding full-table scan), then
        in-memory cosine similarity re-ranks them against ``query_embedding``.

        Args:
            query: Search query string.
            limit: Maximum number of events to return.
            query_embedding: Optional query embedding for semantic ranking.
                When provided, results are re-ranked by cosine similarity
                against each candidate's content embedding (D1).
            start_time: Optional start timestamp (INT64). When both start_time
                and end_time are provided, filters events to [start_time, end_time].
            end_time: Optional end timestamp (INT64). See start_time.
            embedding_service: Optional embedding service used to compute
                candidate content embeddings when EventNode ``embedding``
                property is missing (Q2 fallback, mirrors the
                ``_semantic_temporal_search`` strategy).

        Returns:
            List of event dictionaries. When ``query_embedding`` is provided,
            results are sorted by descending similarity and include a
            ``similarity_score`` field. Otherwise results keep legacy
            behavior: ordered by timestamp ascending (D1 / spec
            ``search-engine#temporal-search-semantic-ranking``).

        """
        # LadybugDB uses event_time (INT64), Neo4j uses timestamp (datetime)
        time_field = "event_time" if self._is_ladybug else "timestamp"

        # Build optional time-window predicate (backward compat: omit when None)
        time_predicate = ""
        if start_time is not None and end_time is not None:
            time_predicate = f" AND e.{time_field} >= $start_time AND e.{time_field} <= $end_time"

        # Simple content-based search (CONTAINS is case-sensitive in Neo4j)
        # Use toLower for case-insensitive matching.
        # D2: RETURN e.embedding AS embedding so callers can construct
        # EventNode without an extra query (None for legacy data, Q2).
        query_cypher = f"""
        MATCH (e:EventNode)
        WHERE toLower(e.content) CONTAINS toLower($query){time_predicate}
        RETURN e.id AS id,
               e.content AS content,
               e.{time_field} AS timestamp,
               e.attributes AS attributes,
               e.embedding AS embedding
        ORDER BY e.{time_field} ASC
        LIMIT $limit
        """

        params: dict[str, Any] = {"query": query, "limit": limit}
        if start_time is not None and end_time is not None:
            # Neo4j timestamp is datetime type — convert int params to datetime
            if self._is_ladybug:
                params["start_time"] = start_time
                params["end_time"] = end_time
            else:
                params["start_time"] = datetime.fromtimestamp(start_time, tz=UTC)
                params["end_time"] = datetime.fromtimestamp(end_time, tz=UTC)
        results = await self._pool.execute_query(query_cypher, params)

        # Parse JSON string attributes back to dict
        for record in results:
            attr = record.get("attributes")
            if isinstance(attr, str):
                try:
                    record["attributes"] = json.loads(attr)
                except (json.JSONDecodeError, TypeError):
                    pass

        # D1 / Task 2.3-2.5: semantic re-ranking when query_embedding provided.
        # When query_embedding is None (Task 2.4), keep legacy behavior:
        # CONTAINS + timestamp ordering.
        if query_embedding is None or not results:
            return results

        # Resolve candidate embeddings (Q2 fallback):
        # ① Prefer EventNode embedding persisted via D2 (task 6.x writes it).
        # ② If None and embedding_service provided, compute on-the-fly
        #    via embed_batch (mirrors _semantic_temporal_search).
        candidate_embeddings: list[list[float] | None] = []
        missing_idx: list[int] = []
        for idx, record in enumerate(results):
            emb = record.get("embedding")
            if isinstance(emb, list) and emb:
                candidate_embeddings.append(emb)
            else:
                candidate_embeddings.append(None)
                missing_idx.append(idx)

        if missing_idx and embedding_service is not None:
            missing_contents = [results[i].get("content", "") for i in missing_idx]
            try:
                computed = await embedding_service.embed_batch(missing_contents)
            except Exception:
                log.warning(
                    "temporal_search_embed_batch_failed",
                    query=query,
                    missing_count=len(missing_idx),
                    exc_info=True,
                )
                computed = []
            for offset, idx in enumerate(missing_idx):
                if offset < len(computed):
                    candidate_embeddings[idx] = computed[offset]
                    results[idx]["embedding"] = computed[offset]

        # Compute cosine similarity and attach similarity_score (Task 2.5)
        scored: list[tuple[float, dict[str, Any]]] = []
        for record, emb in zip(results, candidate_embeddings, strict=True):
            sim = _cosine_similarity(emb, query_embedding)
            record["similarity_score"] = round(sim, 4)
            scored.append((sim, record))

        # Re-rank by similarity descending (D1)
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]

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
            embedding: prev.embedding,
            direction: 'previous'
        }}) AS prev_neighbors

        // Get following events
        OPTIONAL MATCH (center)-[:EVENT_FOLLOWED_BY*1..{after}]->(next:EventNode)
        WITH prev_neighbors, collect(DISTINCT {{
            id: next.id,
            content: next.content,
            timestamp: next.{time_field},
            embedding: next.embedding,
            direction: 'next'
        }}) AS next_neighbors

        UNWIND prev_neighbors + next_neighbors AS neighbor
        RETURN neighbor
        ORDER BY neighbor.timestamp
        """

        params = {"event_id": event_id}
        result = await self._pool.execute_query(query, params)
        return [r.get("neighbor", r) for r in result]

    async def get_events_by_timerange(
        self,
        start_time: int,
        end_time: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get events within a time range.

        Filters EventNode by [start_time, end_time] inclusive.
        Used by /api/v1/search/temporal endpoint for time-window filtering.

        Args:
            start_time: Start timestamp (INT64 seconds since epoch).
            end_time: End timestamp (INT64 seconds since epoch).
            limit: Maximum number of events to return.

        Returns:
            List of events within the time range, ordered by timestamp ASC.
        """
        # LadybugDB uses event_time (INT64), Neo4j uses timestamp (datetime)
        time_field = "event_time" if self._is_ladybug else "timestamp"

        # Neo4j timestamp is datetime type — convert int params to datetime
        if self._is_ladybug:
            params: dict[str, Any] = {
                "start_time": start_time,
                "end_time": end_time,
                "limit": limit,
            }
        else:
            params = {
                "start_time": datetime.fromtimestamp(start_time, tz=UTC),
                "end_time": datetime.fromtimestamp(end_time, tz=UTC),
                "limit": limit,
            }

        query = f"""
        MATCH (e:EventNode)
        WHERE e.{time_field} >= $start_time AND e.{time_field} <= $end_time
        RETURN e.id AS id,
               e.content AS content,
               e.{time_field} AS timestamp,
               e.attributes AS attributes,
               e.embedding AS embedding
        ORDER BY e.{time_field} ASC
        LIMIT $limit
        """

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
