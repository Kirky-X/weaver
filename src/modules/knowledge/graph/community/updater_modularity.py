# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Modularity calculator collaborator for the incremental community updater.

Extracted from ``IncrementalCommunityUpdater`` to give modularity scoring a
single, focused home. Computes graph modularity over the entity graph using
the shared ``_compute_modularity`` helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.knowledge.graph.community.modularity import _compute_modularity

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class ModularityCalculator:
    """Calculate graph modularity for the community structure.

    Single responsibility: query the entity graph edges and current community
    assignments, then compute a modularity score via ``_compute_modularity``.

    Args:
        pool: Graph database connection pool.
        database_type: Database type string ("neo4j" or "ladybug").
    """

    def __init__(self, pool: GraphPool, database_type: str | None = None) -> None:
        from core.constants import DatabaseType

        self._pool = pool
        self._database_type = database_type or DatabaseType.NEO4J.value

    async def _calculate_modularity(self) -> float | None:
        """Calculate current graph modularity.

        Returns:
            Modularity score or None if calculation fails.
        """
        from modules.knowledge.graph.community.ladybug_dialect import LadybugDialect

        is_ladybug = LadybugDialect.is_ladybug(self._database_type)
        # LadybugDB uses r.edge_type instead of type(r)
        type_expr = "r.edge_type" if is_ladybug else "type(r)"
        # LadybugDB has no pruned property on Entity nodes
        pruned_cond_e1 = LadybugDialect.pruned_condition(self._database_type, "e1")
        pruned_cond_e2 = LadybugDialect.pruned_condition(self._database_type, "e2")

        where_parts = [f"NOT {type_expr} IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']"]
        if pruned_cond_e1:
            where_parts.append(f"({pruned_cond_e1})")
        if pruned_cond_e2:
            where_parts.append(f"({pruned_cond_e2})")
        where_clause = " AND ".join(where_parts)

        query = f"""
        MATCH (e1:Entity)-[r]->(e2:Entity)
        WHERE {where_clause}
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               coalesce(r.weight, 1.0) AS weight
        """

        try:
            results = await self._pool.execute_query(query)
            if not results:
                return None

            edges = [(r["source"], r["target"], r["weight"]) for r in results]
            if not edges:
                return None

            # Get community assignments for modularity calculation
            assignments = await self._get_community_assignments_for_modularity()

            return _compute_modularity(edges, assignments)

        except Exception as exc:
            log.debug("calculate_modularity_failed", error=str(exc))
            return None

    async def _get_community_assignments_for_modularity(self) -> dict[str, int]:
        """Get community assignments for modularity calculation.

        Returns:
            Dict mapping entity canonical name to community ID (int).
        """
        from modules.knowledge.graph.community.ladybug_dialect import LadybugDialect

        pruned_cond = LadybugDialect.pruned_condition(self._database_type, "e")
        where_clause = f"WHERE {pruned_cond}" if pruned_cond else ""

        query = f"""
        MATCH (e:Entity)<-[:HAS_ENTITY]-(c:Community)
        {where_clause}
        RETURN e.canonical_name AS entity_name, c.id AS community_id
        """

        try:
            results = await self._pool.execute_query(query)
            # Convert community IDs to integers for modularity calculation
            unique_communities: dict[str, int] = {}
            next_id = 0
            assignments: dict[str, int] = {}

            for r in results:
                comm_id = r.get("community_id")
                entity_name = r.get("entity_name")
                if comm_id and entity_name:
                    if comm_id not in unique_communities:
                        unique_communities[comm_id] = next_id
                        next_id += 1
                    assignments[entity_name] = unique_communities[comm_id]

            return assignments

        except Exception as exc:
            log.debug("get_community_assignments_failed", error=str(exc))
            return {}
