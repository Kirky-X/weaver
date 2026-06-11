# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Event Graph Repository.

Manages event-centric relationships:
- HAS_PARTICIPANT(role): Event → Entity with role attribute
- HAS_SUB_EVENT: Event → Event (parent-child hierarchy)
- HAS_NARRATIVE: Event → Narrative (framing perspective)

Supports both Neo4j and LadybugDB backends by detecting pool type
and using appropriate query syntax.
"""

from __future__ import annotations

import time
from typing import Any

from core.constants import DatabaseType
from core.observability import get_logger
from modules.memory.core.narrative_node import NarrativeNode
from modules.memory.graphs.base import BaseGraphRepo

log = get_logger(__name__)


class EventGraphRepo(BaseGraphRepo):
    """Repository for event-centric graph operations.

    Manages event relationships beyond the temporal and causal graphs:
    participant roles, sub-event hierarchies, and narrative framings.

    Supports both Neo4j and LadybugDB backends.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize event graph repository.

        Args:
            pool: Neo4j or LadybugDB connection pool.
        """
        super().__init__(pool)
        self._is_ladybug = pool.database_type == DatabaseType.LADYBUG.value

    async def ensure_constraints(self) -> None:
        """Create indexes for event-centric edges."""
        if self._is_ladybug:
            log.debug("event_constraints_skip_ladybug")
            return

        indexes = [
            """
            CREATE INDEX participant_role_idx IF NOT EXISTS
                FOR ()-[r:HAS_PARTICIPANT]-() ON r.role
            """,
            """
            CREATE INDEX sub_event_idx IF NOT EXISTS
                FOR ()-[r:HAS_SUB_EVENT]-() ON r.created_at
            """,
        ]

        for index in indexes:
            try:
                await self._pool.execute_query(index)
                log.debug("event_index_created")
            except Exception as exc:
                log.debug("event_index_check", error=str(exc))

    # ── HAS_PARTICIPANT ──────────────────────────────────────────────

    async def add_participant(
        self,
        event_id: str,
        entity_id: str,
        role: str,
    ) -> bool:
        """Add a HAS_PARTICIPANT edge from Event to Entity with role.

        Args:
            event_id: Source event ID.
            entity_id: Target entity ID.
            role: Participant role (initiator/target/observer/beneficiary).

        Returns:
            True if edge was created, False otherwise.
        """
        if self._is_ladybug:
            return await self._add_participant_ladybug(event_id, entity_id, role)
        return await self._add_participant_neo4j(event_id, entity_id, role)

    async def _add_participant_neo4j(self, event_id: str, entity_id: str, role: str) -> bool:
        """Add HAS_PARTICIPANT using Neo4j syntax."""
        query = """
        MATCH (e:EventNode {id: $event_id})
        MATCH (ent:Entity {id: $entity_id})
        MERGE (e)-[r:HAS_PARTICIPANT]->(ent)
        ON CREATE SET
            r.role = $role,
            r.created_at = datetime()
        ON MATCH SET
            r.role = $role,
            r.updated_at = datetime()
        RETURN e.id AS event_id, ent.id AS entity_id, r.role AS role
        """
        params = {"event_id": event_id, "entity_id": entity_id, "role": role}

        try:
            result = await self._pool.execute_query(query, params)
            log.info(
                "participant_added",
                event_id=event_id,
                entity_id=entity_id,
                role=role,
            )
            return bool(result)
        except Exception as exc:
            log.error(
                "add_participant_failed",
                event_id=event_id,
                entity_id=entity_id,
                error=str(exc),
            )
            return False

    async def _add_participant_ladybug(self, event_id: str, entity_id: str, role: str) -> bool:
        """Add HAS_PARTICIPANT using LadybugDB-compatible syntax."""
        now = int(time.time())
        query = """
        MATCH (e:EventNode {id: $event_id})
        MATCH (ent:Entity {id: $entity_id})
        CREATE (e)-[r:HAS_PARTICIPANT]->(ent)
        SET r.role = $role,
            r.created_at = $created_at
        RETURN e.id AS event_id, ent.id AS entity_id
        """
        params = {
            "event_id": event_id,
            "entity_id": entity_id,
            "role": role,
            "created_at": now,
        }

        try:
            result = await self._pool.execute_query(query, params)
            log.info(
                "participant_added",
                event_id=event_id,
                entity_id=entity_id,
                role=role,
            )
            return bool(result)
        except Exception as exc:
            log.error(
                "add_participant_failed",
                event_id=event_id,
                entity_id=entity_id,
                error=str(exc),
            )
            return False

    async def get_participants(
        self,
        event_id: str,
        role: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get participants of an event, optionally filtered by role.

        Args:
            event_id: The event to query.
            role: Optional role filter (initiator/target/observer/beneficiary).

        Returns:
            List of participant dicts with entity_id and role.
        """
        if self._is_ladybug:
            return await self._get_participants_ladybug(event_id, role)
        return await self._get_participants_neo4j(event_id, role)

    async def _get_participants_neo4j(
        self, event_id: str, role: str | None = None
    ) -> list[dict[str, Any]]:
        """Get participants using Neo4j syntax."""
        role_filter = " AND r.role = $role" if role else ""
        query = f"""
        MATCH (e:EventNode {{id: $event_id}})-[r:HAS_PARTICIPANT]->(ent:Entity)
        WHERE true{role_filter}
        RETURN ent.id AS entity_id, r.role AS role
        """
        params: dict[str, Any] = {"event_id": event_id}
        if role:
            params["role"] = role

        try:
            return await self._pool.execute_query(query, params)
        except Exception as exc:
            log.warning("get_participants_failed", event_id=event_id, error=str(exc))
            return []

    async def _get_participants_ladybug(
        self, event_id: str, role: str | None = None
    ) -> list[dict[str, Any]]:
        """Get participants using LadybugDB syntax."""
        role_filter = " AND r.role = $role" if role else ""
        query = f"""
        MATCH (e:EventNode {{id: $event_id}})-[r:HAS_PARTICIPANT]->(ent:Entity)
        WHERE true{role_filter}
        RETURN ent.id AS entity_id, r.role AS role
        """
        params: dict[str, Any] = {"event_id": event_id}
        if role:
            params["role"] = role

        try:
            return await self._pool.execute_query(query, params)
        except Exception as exc:
            log.warning("get_participants_failed", event_id=event_id, error=str(exc))
            return []

    # ── HAS_SUB_EVENT ────────────────────────────────────────────────

    async def add_sub_event(
        self,
        parent_id: str,
        child_id: str,
    ) -> bool:
        """Add a HAS_SUB_EVENT edge from parent to child event.

        Args:
            parent_id: Parent event ID.
            child_id: Child event ID.

        Returns:
            True if edge was created, False otherwise.
        """
        if self._is_ladybug:
            return await self._add_sub_event_ladybug(parent_id, child_id)
        return await self._add_sub_event_neo4j(parent_id, child_id)

    async def _add_sub_event_neo4j(self, parent_id: str, child_id: str) -> bool:
        """Add HAS_SUB_EVENT using Neo4j syntax."""
        query = """
        MATCH (parent:EventNode {id: $parent_id})
        MATCH (child:EventNode {id: $child_id})
        MERGE (parent)-[r:HAS_SUB_EVENT]->(child)
        ON CREATE SET
            r.created_at = datetime()
        ON MATCH SET
            r.updated_at = datetime()
        RETURN parent.id AS parent_id, child.id AS child_id
        """
        params = {"parent_id": parent_id, "child_id": child_id}

        try:
            result = await self._pool.execute_query(query, params)
            log.info(
                "sub_event_added",
                parent_id=parent_id,
                child_id=child_id,
            )
            return bool(result)
        except Exception as exc:
            log.error(
                "add_sub_event_failed",
                parent_id=parent_id,
                child_id=child_id,
                error=str(exc),
            )
            return False

    async def _add_sub_event_ladybug(self, parent_id: str, child_id: str) -> bool:
        """Add HAS_SUB_EVENT using LadybugDB-compatible syntax."""
        now = int(time.time())
        query = """
        MATCH (parent:EventNode {id: $parent_id})
        MATCH (child:EventNode {id: $child_id})
        CREATE (parent)-[r:HAS_SUB_EVENT]->(child)
        SET r.created_at = $created_at
        RETURN parent.id AS parent_id, child.id AS child_id
        """
        params = {
            "parent_id": parent_id,
            "child_id": child_id,
            "created_at": now,
        }

        try:
            result = await self._pool.execute_query(query, params)
            log.info(
                "sub_event_added",
                parent_id=parent_id,
                child_id=child_id,
            )
            return bool(result)
        except Exception as exc:
            log.error(
                "add_sub_event_failed",
                parent_id=parent_id,
                child_id=child_id,
                error=str(exc),
            )
            return False

    async def get_sub_events(
        self,
        event_id: str,
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        """Recursively get sub-events of an event.

        Args:
            event_id: The parent event to query.
            max_depth: Maximum traversal depth.

        Returns:
            List of sub-event dicts.
        """
        time_field = "event_time" if self._is_ladybug else "timestamp"

        query = f"""
        MATCH (parent:EventNode {{id: $event_id}})-[:HAS_SUB_EVENT*1..{max_depth}]->(child:EventNode)
        RETURN DISTINCT child.id AS id,
               child.content AS content
        """

        params = {"event_id": event_id}

        try:
            return await self._pool.execute_query(query, params)
        except Exception as exc:
            log.warning(
                "get_sub_events_failed",
                event_id=event_id,
                error=str(exc),
            )
            return []

    # ── HAS_NARRATIVE ────────────────────────────────────────────────

    async def add_narrative(
        self,
        event_id: str,
        narrative: NarrativeNode,
    ) -> bool:
        """Add a HAS_NARRATIVE edge from Event to NarrativeNode.

        Creates the NarrativeNode and links it to the event.

        Args:
            event_id: Source event ID.
            narrative: NarrativeNode instance with framing data.

        Returns:
            True if edge was created, False otherwise.
        """
        if self._is_ladybug:
            return await self._add_narrative_ladybug(event_id, narrative)
        return await self._add_narrative_neo4j(event_id, narrative)

    async def _add_narrative_neo4j(self, event_id: str, narrative: NarrativeNode) -> bool:
        """Add HAS_NARRATIVE using Neo4j syntax."""
        query = """
        MATCH (e:EventNode {id: $event_id})
        MERGE (n:NarrativeNode {id: $narrative_id})
        ON CREATE SET
            n.source_bias = $source_bias,
            n.frame = $frame,
            n.tone = $tone,
            n.emphasis = $emphasis,
            n.created_at = datetime()
        ON MATCH SET
            n.source_bias = $source_bias,
            n.frame = $frame,
            n.tone = $tone,
            n.emphasis = $emphasis,
            n.updated_at = datetime()
        MERGE (e)-[r:HAS_NARRATIVE]->(n)
        ON CREATE SET r.created_at = datetime()
        RETURN e.id AS event_id, n.id AS narrative_id
        """
        params = {
            "event_id": event_id,
            "narrative_id": narrative.id,
            "source_bias": narrative.source_bias,
            "frame": narrative.frame,
            "tone": narrative.tone,
            "emphasis": narrative.emphasis,
        }

        try:
            result = await self._pool.execute_query(query, params)
            log.info(
                "narrative_added",
                event_id=event_id,
                narrative_id=narrative.id,
            )
            return bool(result)
        except Exception as exc:
            log.error(
                "add_narrative_failed",
                event_id=event_id,
                error=str(exc),
            )
            return False

    async def _add_narrative_ladybug(self, event_id: str, narrative: NarrativeNode) -> bool:
        """Add HAS_NARRATIVE using LadybugDB-compatible syntax."""
        now = int(time.time())

        # Create NarrativeNode first
        create_query = """
        CREATE (n:NarrativeNode {
            id: $narrative_id,
            source_bias: $source_bias,
            frame: $frame,
            tone: $tone,
            emphasis: $emphasis,
            created_at: $created_at
        })
        RETURN n.id
        """
        create_params = {
            "narrative_id": narrative.id,
            "source_bias": narrative.source_bias,
            "frame": narrative.frame,
            "tone": narrative.tone,
            "emphasis": narrative.emphasis,
            "created_at": now,
        }

        try:
            await self._pool.execute_query(create_query, create_params)

            # Create HAS_NARRATIVE edge
            link_query = """
            MATCH (e:EventNode {id: $event_id})
            MATCH (n:NarrativeNode {id: $narrative_id})
            CREATE (e)-[r:HAS_NARRATIVE]->(n)
            SET r.created_at = $created_at
            RETURN e.id AS event_id, n.id AS narrative_id
            """
            link_params = {
                "event_id": event_id,
                "narrative_id": narrative.id,
                "created_at": now,
            }

            result = await self._pool.execute_query(link_query, link_params)
            log.info(
                "narrative_added",
                event_id=event_id,
                narrative_id=narrative.id,
            )
            return bool(result)
        except Exception as exc:
            log.error(
                "add_narrative_failed",
                event_id=event_id,
                error=str(exc),
            )
            return False

    async def get_narratives(
        self,
        event_id: str,
    ) -> list[dict[str, Any]]:
        """Get all narratives for an event.

        Args:
            event_id: The event to query.

        Returns:
            List of narrative dicts with id, source_bias, frame, tone, emphasis.
        """
        query = """
        MATCH (e:EventNode {id: $event_id})-[:HAS_NARRATIVE]->(n:NarrativeNode)
        RETURN n.id AS id,
               n.source_bias AS source_bias,
               n.frame AS frame,
               n.tone AS tone,
               n.emphasis AS emphasis
        """
        params = {"event_id": event_id}

        try:
            return await self._pool.execute_query(query, params)
        except Exception as exc:
            log.warning(
                "get_narratives_failed",
                event_id=event_id,
                error=str(exc),
            )
            return []
