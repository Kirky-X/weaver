# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Diff writer collaborator for the incremental community updater.

Extracted from ``IncrementalCommunityUpdater``. Persists community assignment
changes to the graph database: reassigning entities, creating/emptying/deleting
communities, writing fresh assignments, and marking stale reports.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING

from core.constants import DatabaseType
from core.observability import get_logger
from modules.knowledge.graph.community.graph_utils import (
    find_connected_components_dfs,
)
from modules.knowledge.graph.community.ladybug_dialect import LadybugDialect

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class DiffWriter:
    """Write community assignment diffs to the graph database.

    Single responsibility: persist only the changed community assignments
    (reassignments, community creation/deletion, stale report marking) so the
    incremental updater avoids full graph rewrites.

    Args:
        pool: Graph database connection pool.
        database_type: Graph database type string (e.g. neo4j or ladybug).
    """

    def __init__(
        self,
        pool: GraphPool,
        database_type: str | None = None,
        reassign_concurrency: int = 10,
    ) -> None:
        self._pool = pool
        self._database_type = database_type or DatabaseType.NEO4J.value
        self._reassign_concurrency = reassign_concurrency

    async def _write_diff(
        self,
        old_assignments: dict[str, str],
        new_assignments: dict[str, str],
    ) -> dict[str, int | dict[str, float]]:
        """Compare old and new assignments, write only changes.

        Args:
            old_assignments: Dict mapping node_id to old community_id.
            new_assignments: Dict mapping node_id to new community_id.

        Returns:
            Dict with reassigned, created, emptied counts and entity_count_changes.
        """
        reassigned = 0
        created = 0
        emptied = 0
        entity_count_changes: dict[str, float] = defaultdict(float)

        # Track communities that lost entities
        old_communities: set[str] = set(old_assignments.values())
        new_communities: set[str] = set(new_assignments.values())

        # New communities created
        created = len(new_communities - old_communities)

        # Find changed assignments
        for node_id, new_comm in new_assignments.items():
            old_comm = old_assignments.get(node_id)
            if old_comm != new_comm:
                reassigned += 1
                if old_comm:
                    entity_count_changes[old_comm] -= 1
                entity_count_changes[new_comm] += 1

        # Write changes to Neo4j — concurrent with a bounded semaphore; each
        # coroutine keeps its own delete→create pairing so per-entity ordering
        # is preserved.
        moved = {
            node_id: (old_assignments.get(node_id), new_comm)
            for node_id, new_comm in new_assignments.items()
            if old_assignments.get(node_id) != new_comm
        }
        sem = asyncio.Semaphore(self._reassign_concurrency)

        async def reassign(node_id: str, old_comm: str | None, new_comm: str) -> None:
            async with sem:
                await self._reassign_entity(node_id, old_comm, new_comm)

        await asyncio.gather(*(reassign(nid, old, new) for nid, (old, new) in moved.items()))

        # Check for emptied communities — one grouped aggregate instead of a
        # count query per community.
        candidate_ids = list(entity_count_changes.keys())
        counts: dict[str, int] = {}
        if candidate_ids:
            aggregate_query = """
            MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)
            WHERE c.id IN $community_ids AND (e.pruned IS NULL OR e.pruned = false)
            RETURN c.id AS community_id, count(e) AS count
            """
            try:
                rows = await self._pool.execute_query(
                    aggregate_query, {"community_ids": candidate_ids}
                )
                counts = {row["community_id"]: row["count"] for row in rows or []}
            except Exception as exc:
                log.warning("batch_empty_community_check_failed", error=str(exc))

            for comm_id in candidate_ids:
                if counts.get(comm_id, 0) == 0:
                    await self._mark_community_empty(comm_id)
                    emptied += 1

        log.debug(
            "write_diff_complete",
            reassigned=reassigned,
            created=created,
            emptied=emptied,
        )

        return {
            "reassigned": reassigned,
            "created": created,
            "emptied": emptied,
            "entity_count_changes": dict(entity_count_changes),
        }

    async def _reassign_entity(
        self,
        node_id: str,
        old_community_id: str | None,
        new_community_id: str,
    ) -> None:
        """Reassign entity from old community to new community.

        Args:
            node_id: Neo4j element ID of the entity.
            old_community_id: Old community ID (may be None).
            new_community_id: New community ID.
        """
        # Delete old HAS_ENTITY relationship
        if old_community_id:
            delete_query = """
            MATCH (c:Community {id: $community_id})-[r:HAS_ENTITY]-(e)
            WHERE elementId(e) = $node_id
            DELETE r
            """
            try:
                await self._pool.execute_query(
                    delete_query, {"community_id": old_community_id, "node_id": node_id}
                )
            except Exception as exc:
                log.warning(
                    "delete_old_relationship_failed",
                    node_id=node_id,
                    community_id=old_community_id,
                    error=str(exc),
                )

        # Create new HAS_ENTITY relationship and community if needed.
        # Pattern predicate BEFORE the MERGE decides whether this is a new
        # link: count(r) after MERGE is always 1 and would double-count
        # entity_count when the old-relationship delete failed above.
        create_query = """
        MERGE (c:Community {id: $community_id})
        ON CREATE SET
            c.created_at = datetime(),
            c.level = 0,
            c.title = "Community " + substring($community_id, 0, 8),
            c.entity_count = 0
        WITH c
        MATCH (e)
        WHERE elementId(e) = $node_id
        WITH c, e, NOT (c)-[:HAS_ENTITY]->(e) AS is_new
        MERGE (c)-[r:HAS_ENTITY]->(e)
        WITH c, CASE WHEN is_new THEN 1 ELSE 0 END AS added
        SET c.entity_count = c.entity_count + added
        """

        try:
            await self._pool.execute_query(
                create_query, {"community_id": new_community_id, "node_id": node_id}
            )
        except Exception as exc:
            log.error(
                "create_new_relationship_failed",
                node_id=node_id,
                community_id=new_community_id,
                error=str(exc),
            )

    async def _mark_community_empty(self, community_id: str) -> None:
        """Mark a community as empty.

        Args:
            community_id: Community ID to mark.
        """
        query = """
        MATCH (c:Community {id: $community_id})
        SET c.status = 'empty',
            c.emptied_at = datetime()
        """

        try:
            await self._pool.execute_query(query, {"community_id": community_id})
        except Exception as exc:
            log.warning("mark_community_empty_failed", community_id=community_id, error=str(exc))

    async def _mark_stale_reports(
        self,
        community_ids: list[str],
        entity_count_changes: dict[str, float],
    ) -> int:
        """Mark reports stale for communities with >10% entity count change.

        Args:
            community_ids: List of community IDs to check.
            entity_count_changes: Dict mapping community_id to change amount.

        Returns:
            Number of reports marked stale.
        """
        if not community_ids:
            return 0

        # Get current entity counts
        pruned_cond = LadybugDialect.pruned_condition(self._database_type, "e")
        pruned_clause = f"AND ({pruned_cond})" if pruned_cond else ""
        counts_query = f"""
        MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)
        WHERE c.id IN $community_ids
          {pruned_clause}
        RETURN c.id AS community_id, count(e) AS entity_count
        """

        try:
            results = await self._pool.execute_query(counts_query, {"community_ids": community_ids})
            current_counts = {r["community_id"]: r["entity_count"] for r in results}
        except Exception as exc:
            log.error("get_entity_counts_failed", error=str(exc))
            return 0

        # Find communities with >10% change
        stale_communities: list[str] = []
        for comm_id, current_count in current_counts.items():
            change = entity_count_changes.get(comm_id, 0)
            if current_count > 0 and abs(change) / current_count > 0.1:
                stale_communities.append(comm_id)

        if not stale_communities:
            return 0

        # Mark reports stale
        now_expr = LadybugDialect.now_expression(self._database_type)
        stale_params: dict[str, object] = LadybugDialect.now_param(self._database_type)
        stale_query = f"""
        MATCH (c:Community)<-[:REPORTS_ON]-(r:CommunityReport)
        WHERE c.id IN $community_ids
        SET r.stale = true,
            r.stale_at = {now_expr}
        RETURN count(r) AS stale_count
        """

        try:
            exec_params = {"community_ids": stale_communities}
            exec_params.update(stale_params)
            results = await self._pool.execute_query(stale_query, exec_params)
            count = results[0]["stale_count"] if results else 0
            log.info("reports_marked_stale", count=count, communities=stale_communities)
            return count
        except Exception as exc:
            log.warning("mark_stale_reports_failed", error=str(exc))
            return 0

    async def _create_communities_for_entities(
        self,
        entity_names: list[str],
    ) -> int:
        """Create new communities for entities without assignments.

        Args:
            entity_names: List of entity names to assign.

        Returns:
            Number of communities created.
        """
        if not entity_names:
            return 0

        # Group entities by relationships to create communities
        # For now, create one community per connected component
        rel_pattern = LadybugDialect.related_to_pattern(self._database_type)
        pruned_cond_e = LadybugDialect.pruned_condition(self._database_type, "e")
        pruned_cond_other = LadybugDialect.pruned_condition(self._database_type, "other")

        # First WHERE clause: Neo4j adds pruned filter for e
        if pruned_cond_e:
            where1 = f"WHERE e.canonical_name IN $names AND {pruned_cond_e}"
        else:
            where1 = "WHERE e.canonical_name IN $names"

        # Second WHERE clause (OPTIONAL MATCH): Neo4j needs type exclusion + pruned for other
        if pruned_cond_other:
            where2 = (
                "WHERE NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY'] "
                f"AND other.canonical_name IN $names AND {pruned_cond_other}"
            )
        else:
            where2 = "WHERE other.canonical_name IN $names"

        query = f"""
        MATCH (e:Entity)
        {where1}
        OPTIONAL MATCH (e)-{rel_pattern}-(other:Entity)
        {where2}
        WITH e, collect(DISTINCT other.canonical_name) AS neighbors
        RETURN e.canonical_name AS entity, neighbors
        """

        try:
            results = await self._pool.execute_query(query, {"names": entity_names})

            # Build adjacency from query results
            adjacency: dict[str, set[str]] = defaultdict(set)
            all_entities: set[str] = set()

            for row in results:
                entity = row.get("entity")
                neighbors = row.get("neighbors", [])
                if entity:
                    all_entities.add(entity)
                    for neighbor in neighbors:
                        if neighbor:
                            adjacency[entity].add(neighbor)
                            adjacency[neighbor].add(entity)
                            all_entities.add(neighbor)

            # Find connected components and create communities
            components = find_connected_components_dfs(adjacency, all_entities)
            created = 0

            for component in components:
                community_id = str(uuid.uuid4())
                component_entities = list(component)
                await self._create_community_with_entities(community_id, component_entities)
                created += 1

            if created:
                log.info(
                    "incremental_communities_created",
                    count=created,
                    note="unoptimised components flagged incremental for full rebuild",
                )

            return created

        except Exception as exc:
            log.error("create_communities_failed", error=str(exc))
            return 0

    async def _create_community_with_entities(
        self,
        community_id: str,
        entity_names: list[str],
    ) -> None:
        """Create a community and assign entities to it.

        Args:
            community_id: Community ID to create.
            entity_names: List of entity names to assign.
        """
        # `incremental = true` flags communities formed per connected
        # component without Leiden optimisation — the periodic full rebuild
        # uses this to re-cluster them at the proper granularity.
        query = """
        MERGE (c:Community {id: $community_id})
        ON CREATE SET
            c.created_at = datetime(),
            c.level = 0,
            c.entity_count = 0,
            c.incremental = true
        WITH c
        MATCH (e:Entity)
        WHERE e.canonical_name IN $names
        MERGE (c)-[r:HAS_ENTITY]->(e)
        WITH c, count(r) AS added
        SET c.entity_count = c.entity_count + added
        """

        try:
            await self._pool.execute_query(
                query, {"community_id": community_id, "names": entity_names}
            )
        except Exception as exc:
            log.error(
                "create_community_with_entities_failed",
                community_id=community_id,
                error=str(exc),
            )

    async def _delete_communities_by_ids(self, community_ids: list[str]) -> None:
        """Delete specific communities by their IDs to prevent duplicate accumulation.

        Args:
            community_ids: List of community IDs to delete.
        """
        if not community_ids:
            return

        query = """
        UNWIND $ids AS cid
        MATCH (c:Community {id: cid})
        DETACH DELETE c
        """

        try:
            await self._pool.execute_query(query, {"ids": community_ids})
            log.debug(
                "deleted_affected_communities",
                count=len(community_ids),
            )
        except Exception as exc:
            log.warning(
                "delete_communities_by_ids_failed",
                count=len(community_ids),
                error=str(exc),
            )

    async def _write_new_assignments(
        self,
        new_assignments: dict[str, str],
    ) -> dict[str, int]:
        """Write new community assignments after clearing old ones.

        Unlike _write_diff which compares old vs new, this simply
        creates fresh communities for all new assignments.

        Args:
            new_assignments: Dict mapping node_id to community_id.

        Returns:
            Dict with created and reassigned counts.
        """
        created_communities: set[str] = set()
        reassigned = 0

        is_ladybug = LadybugDialect.is_ladybug(self._database_type)
        now_expr = LadybugDialect.now_expression(self._database_type)
        # LadybugDB doesn't support elementId(), use id property instead
        id_expr = "e.id" if is_ladybug else "elementId(e)"
        params: dict[str, object] = LadybugDialect.now_param(self._database_type)

        for node_id, community_id in new_assignments.items():
            try:
                query = f"""
                MERGE (c:Community {{id: $community_id}})
                ON CREATE SET
                    c.created_at = {now_expr},
                    c.level = 0,
                    c.title = "Community " + substring($community_id, 0, 8),
                    c.entity_count = 0
                WITH c
                MATCH (e)
                WHERE {id_expr} = $node_id
                WITH c, e, NOT (c)-[:HAS_ENTITY]->(e) AS is_new
                MERGE (c)-[r:HAS_ENTITY]->(e)
                WITH c, CASE WHEN is_new THEN 1 ELSE 0 END AS added
                SET c.entity_count = c.entity_count + added
                """
                exec_params = {"community_id": community_id, "node_id": node_id}
                exec_params.update(params)
                await self._pool.execute_query(query, exec_params)
                created_communities.add(community_id)
                reassigned += 1
            except Exception as exc:
                log.warning(
                    "write_new_assignment_failed",
                    node_id=node_id,
                    community_id=community_id,
                    error=str(exc),
                )

        log.debug(
            "write_new_assignments_complete",
            communities_created=len(created_communities),
            entities_assigned=reassigned,
        )

        return {
            "created": len(created_communities),
            "reassigned": reassigned,
            "emptied": 0,
            "entity_count_changes": {},
        }
