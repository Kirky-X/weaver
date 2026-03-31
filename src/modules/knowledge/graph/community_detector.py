# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community detector using Hierarchical Leiden algorithm."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from graspologic.partition import hierarchical_leiden

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger
from modules.knowledge.graph.community_models import (
    Community,
    CommunityDetectionResult,
    HierarchicalCluster,
)
from modules.knowledge.graph.community_repo import Neo4jCommunityRepo

log = get_logger("community_detector")


class CommunityDetector:
    """Detects communities in the knowledge graph using Hierarchical Leiden.

    Uses the graspologic library's implementation of the Hierarchical Leiden
    algorithm to partition entities into hierarchical communities based on
    their RELATED_TO relationships.

    Args:
        pool: Neo4j connection pool.
        max_cluster_size: Maximum size of leaf clusters.
        default_seed: Random seed for reproducibility.
    """

    def __init__(
        self,
        pool: Neo4jPool,
        max_cluster_size: int = 10,
        default_seed: int = 42,
    ) -> None:
        self._pool = pool
        self._repo = Neo4jCommunityRepo(pool)
        self._max_cluster_size = max_cluster_size
        self._default_seed = default_seed

    async def detect_communities(
        self,
        max_cluster_size: int | None = None,
        use_lcc: bool = True,
        seed: int | None = None,
    ) -> CommunityDetectionResult:
        """Run community detection on the knowledge graph.

        Args:
            max_cluster_size: Maximum size of leaf clusters.
            use_lcc: Whether to use largest connected component only.
            seed: Random seed for reproducibility.

        Returns:
            CommunityDetectionResult with detected communities.
        """
        start_time = time.time()
        max_cluster_size = max_cluster_size or self._max_cluster_size
        seed = seed if seed is not None else self._default_seed

        log.info(
            "community_detection_start",
            max_cluster_size=max_cluster_size,
            use_lcc=use_lcc,
            seed=seed,
        )

        # Step 1: Extract edges from Neo4j
        edges = await self._build_edge_list()
        log.info("community_detection_edges_extracted", edge_count=len(edges))

        if not edges:
            log.warning("community_detection_no_edges")
            return CommunityDetectionResult(
                communities=[],
                total_entities=0,
                total_communities=0,
                modularity=0.0,
                levels=0,
                orphan_count=0,
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        # Step 2: Run Hierarchical Leiden
        clusters = self._run_hierarchical_leiden(
            edges=edges,
            max_cluster_size=max_cluster_size,
            seed=seed,
        )
        log.info("community_detection_leiden_complete", cluster_count=len(clusters))

        # Step 3: Process orphan entities (no relationships)
        orphan_entities = await self._get_orphan_entities()
        orphan_count = len(orphan_entities)

        # Step 4: Build community hierarchy
        communities = self._build_communities_from_clusters(clusters)
        log.info(
            "community_detection_communities_built",
            community_count=len(communities),
        )

        # Step 5: Calculate modularity
        modularity = self._calculate_modularity(edges, clusters)

        # Step 6: Create orphan community if needed
        if orphan_entities:
            orphan_community = self._create_orphan_community(orphan_entities)
            communities.append(orphan_community)

        # Determine max level
        levels = max((c.level for c in communities), default=0) + 1 if communities else 0

        execution_time = (time.time() - start_time) * 1000

        log.info(
            "community_detection_complete",
            total_communities=len(communities),
            total_entities=sum(c.entity_count for c in communities),
            modularity=modularity,
            levels=levels,
            orphan_count=orphan_count,
            execution_time_ms=execution_time,
        )

        return CommunityDetectionResult(
            communities=communities,
            total_entities=sum(c.entity_count for c in communities),
            total_communities=len(communities),
            modularity=modularity,
            levels=levels,
            orphan_count=orphan_count,
            execution_time_ms=execution_time,
        )

    async def rebuild_communities(
        self,
        max_cluster_size: int | None = None,
        seed: int | None = None,
    ) -> CommunityDetectionResult:
        """Delete existing communities and rebuild from scratch.

        Args:
            max_cluster_size: Maximum size of leaf clusters.
            seed: Random seed for reproducibility.

        Returns:
            CommunityDetectionResult with new communities.
        """
        log.info("community_rebuild_start")

        # Delete existing communities
        deleted_count = await self._repo.delete_all_communities()
        log.info("community_rebuild_deleted", deleted_count=deleted_count)

        # Run detection
        result = await self.detect_communities(
            max_cluster_size=max_cluster_size,
            seed=seed,
        )

        # Persist to Neo4j
        await self._persist_communities(result.communities)

        return result

    async def _build_edge_list(self) -> list[tuple[str, str, float]]:
        """Extract entity relationships from Neo4j.

        Matches all relationship types except non-entity relationships
        (HAS_ENTITY, MENTIONS, FOLLOWED_BY), covering both legacy RELATED_TO
        and new semantic edge types (PARTNERS_WITH, REGULATES, etc.).

        Returns:
            List of (source, target, weight) tuples.
        """
        query = """
        MATCH (e1:Entity)-[r]->(e2:Entity)
        WHERE NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']
          AND (e1.pruned IS NULL OR e1.pruned = false)
          AND (e2.pruned IS NULL OR e2.pruned = false)
        RETURN e1.canonical_name AS source,
               e2.canonical_name AS target,
               coalesce(r.weight, 1.0) AS weight
        """
        results = await self._pool.execute_query(query)

        # Normalize edges (undirected) and deduplicate
        edge_map: dict[tuple[str, str], float] = {}
        for r in results:
            source = r.get("source", "")
            target = r.get("target", "")
            weight = float(r.get("weight", 1.0))

            # Normalize direction (smaller node first)
            lo, hi = sorted([source, target])
            key = (lo, hi)

            # Keep highest weight if duplicate
            if key not in edge_map or weight > edge_map[key]:
                edge_map[key] = weight

        return [(s, t, w) for (s, t), w in edge_map.items()]

    async def _get_orphan_entities(self) -> list[str]:
        """Get entities with no entity relationships.

        An orphan entity has no relationships to other entities
        (excluding HAS_ENTITY, MENTIONS, FOLLOWED_BY).

        Returns:
            List of orphan entity canonical names.
        """
        # Find entities that either:
        # 1. Have no relationships to other entities at all, OR
        # 2. Only have HAS_ENTITY, MENTIONS, or FOLLOWED_BY relationships
        query = """
        MATCH (e:Entity)
        WHERE NOT EXISTS((e)-[:HAS_ENTITY|MENTIONS|FOLLOWED_BY]-(:Entity))
        RETURN e.canonical_name AS name
        """
        results = await self._pool.execute_query(query)
        return [r.get("name", "") for r in results if r.get("name")]

    def _run_hierarchical_leiden(
        self,
        edges: list[tuple[str, str, float]],
        max_cluster_size: int,
        seed: int,
    ) -> list[HierarchicalCluster]:
        """Run graspologic's Hierarchical Leiden algorithm.

        Args:
            edges: List of (source, target, weight) tuples.
            max_cluster_size: Maximum cluster size.
            seed: Random seed.

        Returns:
            List of HierarchicalCluster results.
        """
        # Convert to graspologic format
        # hierarchical_leiden returns HierarchicalClusters object
        result = hierarchical_leiden(
            graph=edges,  # Edge list format: List[Tuple[node, node, weight]]
            max_cluster_size=max_cluster_size,
            random_seed=seed,
        )

        clusters = []
        # result is a HierarchicalClusters object with __iter__
        for partition in result:
            clusters.append(
                HierarchicalCluster(
                    node=partition.node,
                    cluster=partition.cluster,
                    level=partition.level,
                    parent_cluster=(
                        partition.parent_cluster if hasattr(partition, "parent_cluster") else None
                    ),
                    is_final_cluster=(
                        partition.is_final_cluster
                        if hasattr(partition, "is_final_cluster")
                        else False
                    ),
                )
            )

        return clusters

    def _build_communities_from_clusters(
        self,
        clusters: list[HierarchicalCluster],
    ) -> list[Community]:
        """Build Community objects from Leiden clusters.

        Args:
            clusters: List of HierarchicalCluster results.

        Returns:
            List of Community objects.
        """
        # Group by (level, cluster)
        level_cluster_map: dict[tuple[int, int], list[str]] = defaultdict(list)
        parent_map: dict[int, int] = {}  # cluster_id -> parent_cluster_id

        for c in clusters:
            key = (c.level, c.cluster)
            level_cluster_map[key].append(c.node)
            if c.parent_cluster is not None:
                parent_map[c.cluster] = c.parent_cluster

        # Find cluster IDs for each level
        level_clusters: dict[int, set[int]] = defaultdict(set)
        for c in clusters:
            level_clusters[c.level].add(c.cluster)

        # Build community hierarchy
        communities: list[Community] = []
        community_id_map: dict[tuple[int, int], str] = {}  # (level, cluster) -> community_id

        period = datetime.now(UTC).date().isoformat()

        # Process levels from 0 (leaf) to max
        for level in sorted(level_clusters.keys()):
            for cluster_id in level_clusters[level]:
                key = (level, cluster_id)
                entity_ids = level_cluster_map[key]

                # Generate community ID
                community_id = str(uuid.uuid4())
                community_id_map[key] = community_id

                # Find parent community ID
                parent_community_id: str | None = None
                if cluster_id in parent_map:
                    parent_key = (level + 1, parent_map[cluster_id])
                    parent_community_id = community_id_map.get(parent_key)

                # Calculate rank based on entity count and connections
                rank = len(entity_ids) / 10.0  # Normalize

                community = Community(
                    id=community_id,
                    title=f"Community {cluster_id}",
                    level=level,
                    parent_id=parent_community_id,
                    entity_ids=entity_ids,
                    entity_count=len(entity_ids),
                    rank=min(rank, 10.0),  # Cap at 10
                    period=period,
                )
                communities.append(community)

        return communities

    def _create_orphan_community(self, orphan_entities: list[str]) -> Community:
        """Create a special community for orphan entities.

        Args:
            orphan_entities: List of orphan entity names.

        Returns:
            Community for orphans.
        """
        return Community(
            id=str(uuid.uuid4()),
            title="Orphan Entities",
            level=-1,  # Special level for orphans
            parent_id=None,
            entity_ids=orphan_entities,
            entity_count=len(orphan_entities),
            rank=0.0,  # Lowest rank
            period=datetime.now(UTC).date().isoformat(),
        )

    def _calculate_modularity(
        self,
        edges: list[tuple[str, str, float]],
        clusters: list[HierarchicalCluster],
    ) -> float:
        """Calculate graph modularity.

        Args:
            edges: Edge list.
            clusters: Cluster assignments.

        Returns:
            Modularity score.
        """
        if not edges or not clusters:
            return 0.0

        # Build node -> cluster mapping (using level 0 for leaf clusters)
        node_to_cluster: dict[str, int] = {}
        for c in clusters:
            if c.level == 0:  # Leaf level
                node_to_cluster[c.node] = c.cluster

        if not node_to_cluster:
            return 0.0

        # Calculate total edge weight
        total_weight = sum(w for _, _, w in edges)
        if total_weight == 0:
            return 0.0

        # Calculate community degree sums
        community_degree: dict[int, float] = defaultdict(float)
        community_internal: dict[int, float] = defaultdict(float)

        for source, target, weight in edges:
            source_cluster = node_to_cluster.get(source)
            target_cluster = node_to_cluster.get(target)

            if source_cluster is not None:
                community_degree[source_cluster] += weight
            if target_cluster is not None:
                community_degree[target_cluster] += weight

            # Internal edges
            if source_cluster is not None and source_cluster == target_cluster:
                community_internal[source_cluster] += weight * 2

        # Calculate modularity
        modularity = 0.0
        for cluster in set(node_to_cluster.values()):
            internal = community_internal.get(cluster, 0.0)
            degree = community_degree.get(cluster, 0.0)
            modularity += internal - (degree * degree) / (2 * total_weight)

        modularity /= 2 * total_weight
        return modularity

    async def _persist_communities(self, communities: list[Community]) -> int:
        """Persist communities to Neo4j.

        Args:
            communities: List of communities to persist.

        Returns:
            Number of communities created.
        """
        # Ensure constraints exist
        await self._repo.ensure_constraints()

        created = 0
        for community in communities:
            try:
                await self._repo.create_community(
                    community_id=community.id,
                    title=community.title,
                    level=community.level,
                    parent_id=community.parent_id,
                    entity_count=community.entity_count,
                    rank=community.rank,
                    period=community.period,
                    modularity=community.modularity,
                )

                # Add HAS_ENTITY relationships
                if community.entity_ids:
                    # Get entity types from Neo4j
                    entity_types = await self._get_entity_types(community.entity_ids)
                    assignments = [
                        {
                            "community_id": community.id,
                            "entity_name": name,
                            "entity_type": entity_types.get(name, "未知"),
                        }
                        for name in community.entity_ids
                    ]
                    await self._repo.add_entities_batch(assignments)

                created += 1
            except Exception as exc:
                log.error(
                    "community_persist_failed",
                    community_id=community.id,
                    error=str(exc),
                )

        return created

    async def _get_entity_types(self, entity_names: list[str]) -> dict[str, str]:
        """Get entity types for a list of entity names.

        Args:
            entity_names: List of entity canonical names.

        Returns:
            Mapping from name to type.
        """
        if not entity_names:
            return {}

        query = """
        UNWIND $names AS name
        MATCH (e:Entity {canonical_name: name})
        RETURN e.canonical_name AS name, e.type AS type
        """
        results = await self._pool.execute_query(query, {"names": entity_names})
        return {r.get("name", ""): r.get("type", "未知") for r in results}
