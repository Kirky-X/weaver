# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Graph pruning pipeline for knowledge graph quality management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger

log = get_logger("graph_pruner")


@dataclass
class PruneResult:
    """Result of graph pruning operation."""

    total_entities: int = 0
    pruned_entities: int = 0
    total_edges: int = 0
    pruned_edges: int = 0
    strategies_applied: dict[str, int] = field(default_factory=dict)
    modularity_before: float | None = None
    modularity_after: float | None = None


class GraphPruner:
    """Graph pruning pipeline for knowledge graph quality management.

    Implements four pruning strategies executed in sequence:
    1. Frequency filtering: Remove entities with low mention counts
    2. Degree filtering: Remove entities with low connectivity
    3. Edge weight percentile: Remove weak edges
    4. Ego node removal: Remove highest-degree entities (optional)

    All pruning is reversible via the `pruned` boolean marker.
    """

    def __init__(
        self,
        pool: Neo4jPool,
        min_entity_frequency: int = 2,
        min_entity_degree: int = 1,
        min_edge_weight_pct: float = 40.0,
        remove_ego_nodes: bool = False,
    ) -> None:
        """Initialize the graph pruner.

        Args:
            pool: Neo4j connection pool.
            min_entity_frequency: Minimum MENTIONS inbound count (default: 2).
            min_entity_degree: Minimum relationship degree (default: 1).
            min_edge_weight_pct: Percentile threshold for edge weights (default: 40.0).
                Edges below this percentile are pruned. Higher = more aggressive.
            remove_ego_nodes: Whether to remove highest-degree nodes (default: False).
        """
        self._pool = pool
        self.min_entity_frequency = min_entity_frequency
        self.min_entity_degree = min_entity_degree
        self.min_edge_weight_pct = min_edge_weight_pct
        self.remove_ego_nodes = remove_ego_nodes

    async def prune(self) -> PruneResult:
        """Execute full pruning pipeline.

        Returns:
            PruneResult with statistics before and after pruning.
        """
        log.info(
            "graph_pruning_start",
            min_freq=self.min_entity_frequency,
            min_degree=self.min_entity_degree,
            weight_pct=self.min_edge_weight_pct,
            remove_ego=self.remove_ego_nodes,
        )

        stats: dict[str, int] = {}
        total_entities, total_edges = await self._get_counts()

        # Calculate modularity before pruning
        modularity_before = await self._calculate_modularity()

        # Execute strategies in order
        stats["frequency"] = await self.prune_by_frequency()
        log.info("prune_frequency_complete", count=stats["frequency"])

        stats["degree"] = await self.prune_by_degree()
        log.info("prune_degree_complete", count=stats["degree"])

        stats["edge_weight"] = await self.prune_by_edge_weight()
        log.info("prune_edge_weight_complete", count=stats["edge_weight"])

        if self.remove_ego_nodes:
            stats["ego"] = await self.prune_ego_nodes()
            log.info("prune_ego_complete", count=stats["ego"])

        pruned_entities, pruned_edges = await self._get_pruned_counts()

        # Calculate modularity after pruning
        modularity_after = await self._calculate_modularity()

        log.info(
            "graph_pruning_complete",
            entities_pruned=pruned_entities,
            edges_pruned=pruned_edges,
            modularity_before=modularity_before,
            modularity_after=modularity_after,
        )

        return PruneResult(
            total_entities=total_entities,
            pruned_entities=pruned_entities,
            total_edges=total_edges,
            pruned_edges=pruned_edges,
            strategies_applied=stats,
            modularity_before=modularity_before,
            modularity_after=modularity_after,
        )

    async def prune_by_frequency(self) -> int:
        """Mark entities with low MENTIONS count as pruned.

        Entities are pruned if:
        - They have no incoming MENTIONS relationships, OR
        - Their MENTIONS count is below min_entity_frequency

        Returns:
            Number of entities marked as pruned.
        """
        query = """
        MATCH (e:Entity)
        WHERE NOT ()-[:MENTIONS]->(e)
           OR size(()-[:MENTIONS]->(e)) < $min_freq
        SET e.pruned = true
        WITH e
        MATCH (e)-[r]-(other)
        SET r.pruned = true
        RETURN count(e) AS pruned_count
        """

        try:
            result = await self._pool.execute_query(query, {"min_freq": self.min_entity_frequency})
            count = result[0]["pruned_count"] if result else 0
            log.debug(
                "prune_by_frequency_result",
                count=count,
                min_freq=self.min_entity_frequency,
            )
            return count
        except Exception as exc:
            log.error("prune_by_frequency_failed", error=str(exc))
            return 0

    async def prune_by_degree(self) -> int:
        """Mark entities with low degree as pruned.

        Only considers entities not already pruned by frequency strategy.
        Degree counts RELATED_TO relationships only (excludes MENTIONS/FOLLOWED_BY).

        Returns:
            Number of entities marked as pruned.
        """
        query = """
        MATCH (e:Entity)
        WHERE e.pruned IS NULL OR e.pruned = false
        WITH e,
             size([(e)-[r:RELATED_TO]->() | r]) +
             size([()-[r:RELATED_TO]->(e) | r]) AS degree
        WHERE degree < $min_degree
        SET e.pruned = true
        WITH e
        MATCH (e)-[r:RELATED_TO]-(other)
        SET r.pruned = true
        RETURN count(e) AS pruned_count
        """

        try:
            result = await self._pool.execute_query(query, {"min_degree": self.min_entity_degree})
            count = result[0]["pruned_count"] if result else 0
            log.debug(
                "prune_by_degree_result",
                count=count,
                min_degree=self.min_entity_degree,
            )
            return count
        except Exception as exc:
            log.error("prune_by_degree_failed", error=str(exc))
            return 0

    async def prune_by_edge_weight(self) -> int:
        """Mark edges below weight percentile threshold as pruned.

        Calculates the percentile distribution of all edge weights,
        then marks edges below the threshold as pruned.

        Returns:
            Number of edges marked as pruned.
        """
        # First, get all edge weights
        weights_query = """
        MATCH ()-[r:RELATED_TO]->()
        WHERE r.pruned IS NULL OR r.pruned = false
        RETURN coalesce(r.weight, 1.0) AS weight
        """

        try:
            results = await self._pool.execute_query(weights_query)
            if not results:
                return 0

            weights = [r["weight"] for r in results]
            if not weights:
                return 0

            # Calculate percentile threshold
            threshold = np.percentile(weights, self.min_edge_weight_pct)

            # Mark edges below threshold
            prune_query = """
            MATCH ()-[r:RELATED_TO]->()
            WHERE (r.pruned IS NULL OR r.pruned = false)
              AND coalesce(r.weight, 1.0) < $threshold
            SET r.pruned = true
            RETURN count(r) AS pruned_count
            """

            result = await self._pool.execute_query(prune_query, {"threshold": float(threshold)})
            count = result[0]["pruned_count"] if result else 0

            log.debug(
                "prune_by_edge_weight_result",
                count=count,
                threshold=threshold,
                percentile=self.min_edge_weight_pct,
            )
            return count

        except Exception as exc:
            log.error("prune_by_edge_weight_failed", error=str(exc))
            return 0

    async def prune_ego_nodes(self) -> int:
        """Mark highest-degree entities as pruned.

        Finds the entity with the highest degree and marks it as pruned.
        Useful for removing hub nodes that dominate graph structure.

        Returns:
            Number of entities marked as pruned (typically 1).
        """
        query = """
        MATCH (e:Entity)
        WHERE e.pruned IS NULL OR e.pruned = false
        WITH e,
             size([(e)-[r:RELATED_TO]->() | r]) +
             size([()-[r:RELATED_TO]->(e) | r]) AS degree
        ORDER BY degree DESC
        LIMIT 1
        SET e.pruned = true
        WITH e
        MATCH (e)-[r:RELATED_TO]-(other)
        SET r.pruned = true
        RETURN count(e) AS pruned_count
        """

        try:
            result = await self._pool.execute_query(query)
            count = result[0]["pruned_count"] if result else 0
            log.debug("prune_ego_nodes_result", count=count)
            return count
        except Exception as exc:
            log.error("prune_ego_nodes_failed", error=str(exc))
            return 0

    async def undo_pruning(self) -> int:
        """Remove all pruned markers from entities and edges.

        Returns:
            Total count of unpruned items (entities + edges).
        """
        entity_query = """
        MATCH (e:Entity)
        WHERE e.pruned = true
        SET e.pruned = false
        RETURN count(e) AS count
        """

        edge_query = """
        MATCH ()-[r]->()
        WHERE r.pruned = true
        SET r.pruned = false
        RETURN count(r) AS count
        """

        try:
            entity_result = await self._pool.execute_query(entity_query)
            edge_result = await self._pool.execute_query(edge_query)

            entity_count = entity_result[0]["count"] if entity_result else 0
            edge_count = edge_result[0]["count"] if edge_result else 0

            total = entity_count + edge_count
            log.info(
                "undo_pruning_complete",
                entities=entity_count,
                edges=edge_count,
                total=total,
            )
            return total

        except Exception as exc:
            log.error("undo_pruning_failed", error=str(exc))
            return 0

    async def reapply_pruning(self, **kwargs: Any) -> PruneResult:
        """Undo all pruning, update parameters, and re-execute.

        Args:
            **kwargs: New parameter values (min_entity_frequency, min_entity_degree,
                min_edge_weight_pct, remove_ego_nodes).

        Returns:
            PruneResult from the new pruning operation.
        """
        log.info("reapply_pruning_start", new_params=kwargs)

        await self.undo_pruning()

        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                log.debug("param_updated", key=key, value=value)

        return await self.prune()

    async def _get_counts(self) -> tuple[int, int]:
        """Get total entity and edge counts.

        Returns:
            Tuple of (entity_count, edge_count).
        """
        entity_query = "MATCH (e:Entity) RETURN count(e) AS count"
        edge_query = "MATCH ()-[r:RELATED_TO]->() RETURN count(r) AS count"

        try:
            entity_result = await self._pool.execute_query(entity_query)
            edge_result = await self._pool.execute_query(edge_query)

            entity_count = entity_result[0]["count"] if entity_result else 0
            edge_count = edge_result[0]["count"] if edge_result else 0

            return entity_count, edge_count

        except Exception as exc:
            log.warning("get_counts_failed", error=str(exc))
            return 0, 0

    async def _get_pruned_counts(self) -> tuple[int, int]:
        """Get counts of pruned entities and edges.

        Returns:
            Tuple of (pruned_entity_count, pruned_edge_count).
        """
        entity_query = """
        MATCH (e:Entity)
        WHERE e.pruned = true
        RETURN count(e) AS count
        """

        edge_query = """
        MATCH ()-[r]->()
        WHERE r.pruned = true
        RETURN count(r) AS count
        """

        try:
            entity_result = await self._pool.execute_query(entity_query)
            edge_result = await self._pool.execute_query(edge_query)

            entity_count = entity_result[0]["count"] if entity_result else 0
            edge_count = edge_result[0]["count"] if edge_result else 0

            return entity_count, edge_count

        except Exception as exc:
            log.warning("get_pruned_counts_failed", error=str(exc))
            return 0, 0

    async def _calculate_modularity(self) -> float | None:
        """Calculate graph modularity score.

        Returns:
            Modularity score or None if calculation fails.
        """
        query = """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE (e1.pruned IS NULL OR e1.pruned = false)
          AND (e2.pruned IS NULL OR e2.pruned = false)
          AND (r.pruned IS NULL OR r.pruned = false)
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               coalesce(r.weight, 1.0) AS weight
        """

        try:
            results = await self._pool.execute_query(query)
            if not results:
                return None

            # Simple modularity based on connected components
            edges = [(r["source"], r["target"], r["weight"]) for r in results]
            if not edges:
                return None

            # Generate partitions based on connected components
            partitions = self._generate_partitions(edges)

            return self._compute_modularity(edges, partitions)

        except Exception as exc:
            log.debug("calculate_modularity_failed", error=str(exc))
            return None

    def _generate_partitions(self, edges: list[tuple[str, str, float]]) -> dict[str, int]:
        """Generate partitions based on connected components."""
        from collections import defaultdict

        adjacency: dict[str, set[str]] = defaultdict(set)
        all_nodes: set[str] = set()

        for source, target, _ in edges:
            adjacency[source].add(target)
            adjacency[target].add(source)
            all_nodes.add(source)
            all_nodes.add(target)

        visited: set[str] = set()
        partitions: dict[str, int] = {}
        community_id = 0

        def dfs(start: str) -> None:
            stack = [start]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                partitions[node] = community_id
                for neighbor in adjacency.get(node, []):
                    if neighbor not in visited:
                        stack.append(neighbor)

        for node in all_nodes:
            if node not in visited:
                dfs(node)
                community_id += 1

        return partitions

    def _compute_modularity(
        self,
        edges: list[tuple[str, str, float]],
        partitions: dict[str, int],
        resolution: float = 1.0,
    ) -> float:
        """Compute modularity score from edges and partitions."""
        if not edges or not partitions:
            return 0.0

        total_weight = sum(e[2] for e in edges)
        if total_weight == 0:
            return 0.0

        from collections import defaultdict

        degree_sums_within: dict[int, float] = defaultdict(float)
        degree_sums_for: dict[int, float] = defaultdict(float)

        for source, target, weight in edges:
            src_comm = partitions.get(source, -1)
            tgt_comm = partitions.get(target, -1)

            if src_comm == tgt_comm and src_comm != -1:
                degree_sums_within[src_comm] += weight * 2

            if src_comm != -1:
                degree_sums_for[src_comm] += weight
            if tgt_comm != -1:
                degree_sums_for[tgt_comm] += weight

        modularity = 0.0
        for comm in set(partitions.values()):
            if comm == -1:
                continue
            intra = degree_sums_within[comm]
            total = degree_sums_for[comm]
            modularity += intra - resolution * (total**2) / (2 * total_weight)

        return modularity / (2 * total_weight)
