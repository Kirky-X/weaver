# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Modularity calculator collaborator for the incremental community updater.

Extracted from ``IncrementalCommunityUpdater`` to give modularity scoring a
single, focused home. Computes graph modularity over the entity graph using
the shared ``_compute_modularity`` helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.constants import DatabaseType
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
        self._pool = pool
        self._database_type = database_type or DatabaseType.NEO4J.value

    async def modularity_inputs(
        self,
    ) -> tuple[list[tuple[str, str, float]], dict[str, int]]:
        """Query the edge snapshot and current assignments.

        The Entity-Entity edge set is not touched by community updates
        (HAS_ENTITY/MENTIONS/FOLLOWED_BY are excluded), so within one update
        flow the edges can be fetched once and reused for both the before and
        after scores — only the assignment map changes.

        Returns:
            (edges, assignments): canonicalized undirected edges and
            entity_name → int community_id mapping.
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

            # Canonicalize undirected edges (dedupe both-direction rows and
            # accidental duplicates, keep max weight) so _compute_modularity's
            # undirected formulation counts each edge exactly once.
            edge_map: dict[tuple[str, str], float] = {}
            for r in results or []:
                source, target = r["source"], r["target"]
                weight = r["weight"]
                lo, hi = (source, target) if source < target else (target, source)
                if (lo, hi) not in edge_map or weight > edge_map[(lo, hi)]:
                    edge_map[(lo, hi)] = weight
            edges = [(lo, hi, w) for (lo, hi), w in edge_map.items()]
            # Lazy: no edges → modularity is None regardless of assignments,
            # so skip the assignment query entirely (legacy behavior).
            if not edges:
                return [], {}

            assignments = await self.community_assignments()
            return edges, assignments

        except Exception as exc:
            log.debug("modularity_inputs_failed", error=str(exc))
            return [], {}

    async def community_assignments(self) -> dict[str, int]:
        """Get current entity → community assignments (fresh from the graph)."""
        return await self._get_community_assignments_for_modularity()

    def modularity_from(
        self,
        edges: list[tuple[str, str, float]],
        assignments: dict[str, int],
    ) -> float | None:
        """Pure computation: modularity for the given edges and assignments."""
        if not edges:
            return None
        return _compute_modularity(edges, assignments)

    async def _calculate_modularity(self) -> float | None:
        """Calculate current graph modularity (legacy entry point).

        Equivalent to ``modularity_from(*await modularity_inputs())``.
        """
        edges, assignments = await self.modularity_inputs()
        return self.modularity_from(edges, assignments)

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
