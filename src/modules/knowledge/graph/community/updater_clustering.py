# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Subgraph clustering service collaborator for the incremental community updater.

Extracted from ``IncrementalCommunityUpdater``. Owns subgraph extraction around
affected communities and the clustering algorithms (Leiden with a connected
components fallback), plus the incremental/full rebuild orchestration that
drives the diff writer and modularity calculator.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from core.constants import DatabaseType
from core.observability import get_logger
from modules.knowledge.graph.community.graph_utils import (
    assign_components_to_uuids,
    build_adjacency,
    find_connected_components_dfs,
)
from modules.knowledge.graph.community.ladybug_dialect import LadybugDialect

# Optional: Leiden algorithm for better community detection
try:
    import igraph as ig
    import leidenalg

    LEIDEN_AVAILABLE = True
except ImportError:
    LEIDEN_AVAILABLE = False

if TYPE_CHECKING:
    from core.llm import LLMClient
    from core.protocols import GraphPool
    from modules.knowledge.graph.community.updater import (
        IncrementalCommunityUpdater,
        IncrementalUpdateResult,
    )
    from modules.knowledge.graph.community.updater_diff import DiffWriter
    from modules.knowledge.graph.community.updater_modularity import ModularityCalculator

log = get_logger(__name__)


class SubgraphClusteringService:
    """Extract local subgraphs and cluster nodes into communities.

    Single responsibility: identify pending entities, extract the 2-hop
    subgraph around affected communities, cluster nodes via Leiden (falling
    back to connected components), and orchestrate the incremental update and
    full rebuild flows by delegating diff writes and modularity scoring.

    Args:
        pool: Graph database connection pool.
        max_subgraph_size: Maximum nodes in extracted subgraph.
        database_type: Graph database type string (e.g. neo4j or ladybug).
        llm_client: Optional LLM client forwarded to the community detector.
        modularity_calculator: Collaborator that computes graph modularity.
        diff_writer: Collaborator that persists community assignment diffs.
        updater: Owning incremental updater, used to update community metadata.
    """

    def __init__(
        self,
        pool: GraphPool,
        max_subgraph_size: int,
        database_type: str,
        llm_client: LLMClient | None,
        modularity_calculator: ModularityCalculator,
        diff_writer: DiffWriter,
        updater: IncrementalCommunityUpdater,
    ) -> None:
        self._pool = pool
        self.max_subgraph_size = max_subgraph_size
        self._database_type = database_type
        self._llm = llm_client
        self._modularity_calculator = modularity_calculator
        self._diff_writer = diff_writer
        self._updater = updater

    def _run_local_clustering(
        self,
        nodes: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Run local clustering using connected components.

        Uses connected component analysis for local clustering.
        Each component gets a UUID as its community_id.
        Falls back to connected components when leidenalg is unavailable.

        Args:
            nodes: List of entity IDs.
            edges: List of (source, target, weight) tuples.

        Returns:
            Dict mapping node_id -> community_id (UUID string).
        """
        adjacency, all_nodes = build_adjacency(edges)
        all_nodes.update(nodes)

        components = find_connected_components_dfs(adjacency, all_nodes)
        assignments = assign_components_to_uuids(components)

        log.debug(
            "local_clustering_complete",
            components=len(set(assignments.values())),
            entities=len(assignments),
        )
        return assignments

    async def run_incremental_update(
        self,
        entity_names: list[str] | None = None,
    ) -> IncrementalUpdateResult:
        """Run incremental community update.

        Args:
            entity_names: Optional list of new/updated entity names.
                If None, will query for pending entities.

        Returns:
            IncrementalUpdateResult with statistics.
        """
        import time

        from modules.knowledge.graph.community.updater import IncrementalUpdateResult

        start = time.monotonic()
        result = IncrementalUpdateResult()

        log.info("incremental_community_update_start")

        # Get modularity before
        result.modularity_before = await self._modularity_calculator._calculate_modularity()

        # If entity names not provided, get pending entities
        if entity_names is None:
            entity_names = await self._get_pending_entity_names()

        if not entity_names:
            log.info("incremental_community_update_no_pending")
            await self._updater._update_metadata(result)
            result.duration_seconds = time.monotonic() - start
            return result

        # Step 1: Identify affected communities
        affected_communities = await self._identify_affected_communities(entity_names)
        result.affected_communities = len(affected_communities)

        if not affected_communities:
            log.info("incremental_community_update_no_affected")
            # Create new communities for new entities
            new_communities = await self._diff_writer._create_communities_for_entities(entity_names)
            result.communities_created = new_communities
            await self._updater._update_metadata(result)
            result.duration_seconds = time.monotonic() - start
            return result

        # Step 2: Extract subgraph
        node_ids, edges = await self._extract_subgraph(affected_communities)

        if not node_ids:
            log.warning("incremental_community_update_empty_subgraph")
            result.duration_seconds = time.monotonic() - start
            return result

        # Step 3: Get current assignments
        old_assignments = await self._get_current_assignments(node_ids)

        # Step 4: Run clustering to get new assignments
        new_assignments = await self._cluster_communities(node_ids, edges)

        # Step 4.5: Delete affected communities to prevent duplicate accumulation
        await self._diff_writer._delete_communities_by_ids(affected_communities)

        # Step 5: Write new assignments (creates fresh communities)
        diff_result = await self._diff_writer._write_new_assignments(new_assignments)
        result.entities_reassigned = diff_result["reassigned"]
        result.communities_created = diff_result["created"]
        result.communities_emptied = diff_result["emptied"]

        # Step 6: Mark stale reports
        result.reports_marked_stale = await self._diff_writer._mark_stale_reports(
            affected_communities, diff_result["entity_count_changes"]
        )

        # Get modularity after
        result.modularity_after = await self._modularity_calculator._calculate_modularity()

        # Update metadata
        await self._updater._update_metadata(result)

        result.duration_seconds = time.monotonic() - start

        log.info(
            "incremental_community_update_complete",
            affected=result.affected_communities,
            reassigned=result.entities_reassigned,
            created=result.communities_created,
            emptied=result.communities_emptied,
            stale=result.reports_marked_stale,
            duration=result.duration_seconds,
        )

        return result

    async def run_full_rebuild(self) -> IncrementalUpdateResult:
        """Run full community rebuild on the entire graph.

        Delegates to CommunityDetector.rebuild_communities() which uses
        Hierarchical Leiden algorithm for high-quality community detection.

        Returns:
            IncrementalUpdateResult with statistics.
        """
        import time

        from modules.knowledge.graph.community.updater import IncrementalUpdateResult

        start = time.monotonic()
        result = IncrementalUpdateResult()

        log.info("full_community_rebuild_start")

        # Get modularity before
        result.modularity_before = await self._modularity_calculator._calculate_modularity()

        # Delegate to CommunityDetector for Leiden-based rebuild
        from core.db.graph_query_builders import GraphDatabaseType
        from modules.knowledge.graph.community.detector import CommunityDetector

        db_type = (
            GraphDatabaseType.LADYBUG
            if self._database_type == DatabaseType.LADYBUG.value
            else GraphDatabaseType.NEO4J
        )
        detector = CommunityDetector(pool=self._pool, llm_client=self._llm, database_type=db_type)
        detection_result = await detector.rebuild_communities()

        result.communities_created = detection_result.total_communities
        result.entities_reassigned = detection_result.total_entities
        result.modularity_after = detection_result.modularity

        # Update metadata including entity count
        await self._updater._update_full_rebuild_metadata()

        result.duration_seconds = time.monotonic() - start

        log.info(
            "full_community_rebuild_complete",
            communities=result.communities_created,
            entities=result.entities_reassigned,
            modularity=result.modularity_after,
            duration=result.duration_seconds,
        )

        return result

    async def _get_pending_entity_names(self) -> list[str]:
        """Get names of entities pending community assignment.

        Returns:
            List of entity canonical names.
        """
        query = """
        MATCH (e:Entity)
        WHERE NOT (e)<-[:HAS_ENTITY]-(:Community)
          AND (e.pruned IS NULL OR e.pruned = false)
        RETURN e.canonical_name AS name
        LIMIT $limit
        """

        try:
            results = await self._pool.execute_query(query, {"limit": self.max_subgraph_size})
            return [r["name"] for r in results if r.get("name")]
        except Exception as exc:
            log.error("get_pending_entities_failed", error=str(exc))
            return []

    async def _identify_affected_communities(
        self,
        entity_names: list[str],
    ) -> list[str]:
        """Find communities affected by new/updated entities via 2-hop traversal.

        Args:
            entity_names: List of entity canonical names.

        Returns:
            List of affected community IDs.
        """
        if not entity_names:
            return []

        rel_pattern = LadybugDialect.related_to_pattern(self._database_type)
        pruned_cond = LadybugDialect.pruned_condition(self._database_type, "e2")
        if pruned_cond:
            # Neo4j: explicit type exclusion + pruned filter
            where_clause = (
                f"WHERE NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY'] AND {pruned_cond}"
            )
        else:
            # LadybugDB: [r:RELATED_TO] pattern filters type, no pruned field
            where_clause = ""

        query = f"""
        MATCH (e:Entity)-[:HAS_ENTITY]-(c:Community)
        WHERE e.canonical_name IN $names
        WITH DISTINCT c.id AS community_id
        MATCH (c:Community)-[:HAS_ENTITY]-(e1:Entity)-{rel_pattern}-(e2:Entity)-[:HAS_ENTITY]-(c2:Community)
        {where_clause}
        RETURN DISTINCT community_id, c2.id AS neighbor_community_id
        """

        try:
            results = await self._pool.execute_query(query, {"names": entity_names})
            community_ids = set()
            for row in results:
                if row.get("community_id"):
                    community_ids.add(row["community_id"])
                if row.get("neighbor_community_id"):
                    community_ids.add(row["neighbor_community_id"])
            return list(community_ids)
        except Exception as exc:
            log.error("identify_affected_communities_failed", error=str(exc))
            return []

    async def _extract_subgraph(
        self,
        community_ids: list[str],
    ) -> tuple[list[str], list[tuple[str, str, float]]]:
        """Extract 2-hop subgraph around affected communities.

        Args:
            community_ids: List of community IDs to extract around.

        Returns:
            Tuple of (node_ids, edges_with_weights).
        """
        if not community_ids:
            return [], []

        rel_pattern = LadybugDialect.related_to_pattern(self._database_type)
        pruned_cond_e1 = LadybugDialect.pruned_condition(self._database_type, "e1")
        pruned_cond_e2 = LadybugDialect.pruned_condition(self._database_type, "e2")
        is_ladybug = LadybugDialect.is_ladybug(self._database_type)

        # LadybugDB uses id property; Neo4j uses elementId() function
        id_expr1 = "e1.id" if is_ladybug else "elementId(e1)"
        id_expr2 = "e2.id" if is_ladybug else "elementId(e2)"

        # First WHERE clause: Neo4j adds pruned filter for e1
        if pruned_cond_e1:
            where1 = f"WHERE c.id IN $community_ids AND {pruned_cond_e1}"
        else:
            where1 = "WHERE c.id IN $community_ids"

        # Second WHERE clause: Neo4j needs type exclusion + pruned filter for e2
        if pruned_cond_e2:
            where2 = (
                "WHERE NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY'] "
                f"AND {pruned_cond_e2}"
            )
        else:
            where2 = ""

        query = f"""
        MATCH (c:Community)-[:HAS_ENTITY]-(e1:Entity)
        {where1}
        WITH e1
        MATCH (e1)-{rel_pattern}-(e2:Entity)
        {where2}
        RETURN DISTINCT
               {id_expr1} AS id1,
               {id_expr2} AS id2,
               coalesce(r.weight, 1.0) AS weight
        LIMIT $max_edges
        """

        try:
            results = await self._pool.execute_query(
                query,
                {"community_ids": community_ids, "max_edges": self.max_subgraph_size * 2},
            )

            node_ids: set[str] = set()
            edges: list[tuple[str, str, float]] = []

            for row in results:
                id1 = row.get("id1")
                id2 = row.get("id2")
                weight = row.get("weight", 1.0)
                if id1 and id2:
                    node_ids.add(id1)
                    node_ids.add(id2)
                    edges.append((id1, id2, float(weight)))

                    # Enforce max subgraph size
                    if len(node_ids) >= self.max_subgraph_size:
                        break

            log.debug(
                "subgraph_extracted",
                nodes=len(node_ids),
                edges=len(edges),
            )
            return list(node_ids), edges

        except Exception as exc:
            log.error("extract_subgraph_failed", error=str(exc))
            return [], []

    async def _get_current_assignments(
        self,
        node_ids: list[str],
    ) -> dict[str, str]:
        """Get current community assignments for nodes.

        Args:
            node_ids: List of Neo4j element IDs for entities.

        Returns:
            Dict mapping node_id to community_id.
        """
        if not node_ids:
            return {}

        query = """
        MATCH (e)<-[:HAS_ENTITY]-(c:Community)
        WHERE elementId(e) IN $node_ids
        RETURN elementId(e) AS node_id, c.id AS community_id
        """

        try:
            results = await self._pool.execute_query(query, {"node_ids": node_ids})
            return {r["node_id"]: r["community_id"] for r in results if r.get("node_id")}
        except Exception as exc:
            log.error("get_current_assignments_failed", error=str(exc))
            return {}

    async def _cluster_communities(
        self,
        node_ids: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Cluster nodes into communities using Leiden algorithm.

        Uses Leiden algorithm for optimal community detection with modularity
        optimization. Falls back to connected components when leidenalg is unavailable.

        Args:
            node_ids: List of node IDs.
            edges: List of (source, target, weight) tuples.

        Returns:
            Dict mapping node_id to new community_id.
        """
        if not node_ids:
            return {}

        # Try Leiden algorithm first
        if LEIDEN_AVAILABLE:
            return self._cluster_with_leiden(node_ids, edges)
        else:
            log.debug("leiden_unavailable_using_connected_components")
            return self._cluster_with_connected_components(node_ids, edges)

    def _cluster_with_leiden(
        self,
        node_ids: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Cluster nodes using Leiden algorithm for optimal modularity.

        Args:
            node_ids: List of node IDs.
            edges: List of (source, target, weight) tuples.

        Returns:
            Dict mapping node_id to community_id.
        """
        try:
            # Create node ID to index mapping
            node_id_to_idx = {node_id: idx for idx, node_id in enumerate(node_ids)}

            # Build edge list for igraph (using indices)
            edge_list = []
            weights = []
            node_id_set = set(node_ids)

            for source, target, weight in edges:
                if source in node_id_set and target in node_id_set:
                    edge_list.append((node_id_to_idx[source], node_id_to_idx[target]))
                    weights.append(weight)

            if not edge_list:
                # No edges - each node is its own community
                return {node_id: str(uuid.uuid4()) for node_id in node_ids}

            # Create igraph graph
            g = ig.Graph(n=len(node_ids), edges=edge_list, directed=False)
            g.es["weight"] = weights

            # Apply Leiden algorithm with modularity optimization
            partition = leidenalg.find_partition(
                g,
                leidenalg.ModularityVertexPartition,
                weights="weight",
                seed=42,  # Reproducible results
            )

            # Map nodes to communities
            assignments = {}
            for idx, community_id in enumerate(partition.membership):
                node_id = node_ids[idx]
                # Use community index as part of UUID for reproducibility
                community_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"community_{community_id}"))
                assignments[node_id] = community_uuid

            log.debug(
                "leiden_clustering_complete",
                communities=len(set(partition.membership)),
                nodes=len(assignments),
                modularity=partition.q,
            )

            return assignments

        except Exception as exc:
            log.warning(
                "leiden_clustering_failed_using_fallback",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            # Fall back to connected components
            return self._cluster_with_connected_components(node_ids, edges)

    def _cluster_with_connected_components(
        self,
        node_ids: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Cluster nodes using connected components (fallback method).

        Args:
            node_ids: List of node IDs.
            edges: List of (source, target, weight) tuples.

        Returns:
            Dict mapping node_id to community_id.
        """
        if not node_ids:
            return {}

        # Build adjacency list (filtered by node_id_set)
        node_id_set = set(node_ids)
        adjacency, _ = build_adjacency(edges, node_filter=node_id_set)

        # Find connected components and assign UUIDs
        components = find_connected_components_dfs(adjacency, node_id_set)
        assignments = assign_components_to_uuids(components)
        community_num = len(components)

        log.debug(
            "clustering_complete",
            communities=community_num,
            nodes=len(assignments),
        )

        return assignments
