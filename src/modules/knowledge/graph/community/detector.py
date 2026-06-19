# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community detector using Leiden algorithm."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import igraph as ig
import leidenalg

from core.db.graph_query_builders import GraphDatabaseType
from core.observability import get_logger
from core.observability.metrics import MetricsCollector
from modules.knowledge.graph.community.models import (
    Community,
    CommunityDetectionResult,
    HierarchicalCluster,
)
from modules.knowledge.graph.community.modularity import _compute_modularity
from modules.knowledge.graph.community.repo import Neo4jCommunityRepo

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class CommunityDetector:
    """Detects communities in the knowledge graph using Leiden algorithm.

    Uses the leidenalg + igraph libraries' implementation of the Hierarchical Leiden
    algorithm to partition entities into hierarchical communities based on
    their RELATED_TO relationships.

    Implements: CommunityDetectionStrategy

    Args:
        pool: Graph database connection pool.
        max_cluster_size: Maximum size of leaf clusters.
        default_seed: Random seed for reproducibility.
    """

    def __init__(
        self,
        pool: GraphPool,
        max_cluster_size: int = 10,
        default_seed: int = 42,
        database_type: GraphDatabaseType = GraphDatabaseType.NEO4J,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._pool = pool
        self._repo = Neo4jCommunityRepo(pool, database_type=database_type)
        self._max_cluster_size = max_cluster_size
        self._default_seed = default_seed
        self._database_type = database_type
        self._llm = llm_client

    async def detect_communities(
        self,
        max_cluster_size: int | None = None,
        use_lcc: bool = True,
        iterations: int = 1,
        seed: int | None = None,
    ) -> CommunityDetectionResult:
        """Run community detection on the knowledge graph.

        Args:
            max_cluster_size: Maximum size of leaf clusters.
            use_lcc: Whether to use largest connected component only.
            iterations: Number of Leiden optimisation iterations.
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
            iterations=iterations,
            seed=seed,
        )

        # Step 1: Extract edges from Neo4j
        edges = await self._build_edge_list()
        log.info("community_detection_edges_extracted", edge_count=len(edges))

        if not edges:
            log.warning("community_detection_no_edges")
            elapsed = (time.time() - start_time) * 1000
            MetricsCollector.community_detection_duration_seconds.labels(
                algorithm="leiden"
            ).observe(elapsed / 1000.0)
            return CommunityDetectionResult(
                communities=[],
                total_entities=0,
                total_communities=0,
                modularity=0.0,
                levels=0,
                orphan_count=0,
                execution_time_ms=elapsed,
            )

        # Step 2: Run Hierarchical Leiden
        clusters = self._run_hierarchical_leiden(
            edges=edges,
            max_cluster_size=max_cluster_size,
            use_lcc=use_lcc,
            iterations=iterations,
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

        MetricsCollector.community_detection_duration_seconds.labels(algorithm="leiden").observe(
            execution_time / 1000.0
        )

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

        # Generate LLM titles for communities
        if self._llm:
            await self._generate_community_titles(result.communities)

        # Persist to Neo4j
        await self._persist_communities(result.communities)

        return result

    async def _build_edge_list(self) -> list[tuple[str, str, float]]:
        """Extract entity relationships from graph database.

        Matches all relationship types except non-entity relationships
        (HAS_ENTITY, MENTIONS, FOLLOWED_BY), covering generic RELATED_TO
        and semantic edge types (PARTNERS_WITH, REGULATES, etc.).

        Returns:
            List of (source, target, weight) tuples.
        """
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: Entity-to-Entity edges all use RELATED_TO table
            # with edge_type field. No pruned field in LadybugDB schema.
            # Note: LadybugDB doesn't support IS NULL OR ... NOT IN syntax.
            # All RELATED_TO edges between entities are valid (MENTIONS is
            # Article->Entity only, HAS_ENTITY is Community->Entity only).
            query = """
            MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
            RETURN e1.canonical_name AS source,
                   e2.canonical_name AS target,
                   coalesce(r.weight, 1.0) AS weight
            """
        else:
            # Neo4j: Multiple relationship types, use type(r) function
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

        if not results:
            return []

        # Pure Python edge normalization and deduplication using defaultdict
        # Keep highest weight for duplicate undirected edges
        edge_map: dict[tuple[str, str], float] = {}
        for row in results:
            source = row.get("source", "")
            target = row.get("target", "")
            weight = row.get("weight", 1.0) or 1.0
            if not source or not target:
                continue
            # Normalize direction: smaller node name first (undirected graph)
            lo, hi = (source, target) if source < target else (target, source)
            key = (lo, hi)
            # Keep highest weight for duplicate edges
            if key not in edge_map or weight > edge_map[key]:
                edge_map[key] = weight

        return [(lo, hi, w) for (lo, hi), w in edge_map.items()]

    async def _get_orphan_entities(self) -> list[str]:
        """Get entities with no entity relationships.

        An orphan entity has no relationships to other entities
        (excluding HAS_ENTITY, MENTIONS, FOLLOWED_BY).

        Returns:
            List of orphan entity canonical names.
        """
        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: No NOT EXISTS support. Find all entities, then
            # subtract those with RELATED_TO relationships.
            query = """
            MATCH (e:Entity)
            WHERE NOT (e)-[:RELATED_TO]-(:Entity)
            RETURN e.canonical_name AS name
            """
        else:
            # Neo4j: Use NOT EXISTS pattern
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
        use_lcc: bool = True,
        iterations: int = 1,
    ) -> list[HierarchicalCluster]:
        """Run Hierarchical Leiden using leidenalg + igraph.

        Args:
            edges: List of (source, target, weight) tuples.
            max_cluster_size: Maximum cluster size.
            use_lcc: Whether to use largest connected component only.
            iterations: Number of optimisation iterations.
            seed: Random seed.

        Returns:
            List of HierarchicalCluster results.
        """
        if not edges:
            return []

        # Build igraph from edge list
        node_names = sorted({name for edge in edges for name in (edge[0], edge[1])})
        name_to_idx = {name: i for i, name in enumerate(node_names)}

        g = ig.Graph()
        g.add_vertices(len(node_names))
        g.vs["name"] = node_names
        g.add_edges([(name_to_idx[s], name_to_idx[t]) for s, t, _ in edges])
        g.es["weight"] = [w for _, _, w in edges]

        # LCC filtering: only process largest connected component
        if use_lcc and g.vcount() > 0:
            components = g.connected_components()
            if len(components) > 1:
                g = components.giant()
                # Update node_names to only include LCC nodes
                node_names = [node_names[i] for i in g.vs.indices]

        max_depth = 10
        clusters: list[HierarchicalCluster] = []

        def _recursive_partition(
            graph: ig.Graph,
            names: list[str],
            max_size: int,
            rng_seed: int,
            n_iterations: int,
            depth: int = 0,
            parent_cluster_id: int | None = None,
        ) -> None:
            current_level = max_depth - depth

            if graph.vcount() == 0:
                return

            # Run Leiden partitioning using Optimiser for iteration control
            optimiser = leidenalg.Optimiser()
            optimiser.set_rng_seed(rng_seed)
            optimiser.consider_comms = leidenalg.ALL_NEIGH_COMMS

            if "weight" in graph.edge_attributes():
                partition = leidenalg.ModularityVertexPartition(graph, weights="weight")
            else:
                partition = leidenalg.ModularityVertexPartition(graph)

            optimiser.optimise_partition(partition, n_iterations=n_iterations)

            # Generate clusters from partition
            for node_idx, cluster_id in enumerate(partition.membership):
                clusters.append(
                    HierarchicalCluster(
                        node=names[node_idx],
                        cluster=cluster_id,
                        level=current_level,
                        parent_cluster=parent_cluster_id,
                        is_final_cluster=True,  # Will be updated below
                    )
                )

            # Recursively split oversized clusters
            if depth < max_depth:
                for cid in range(len(partition)):
                    members = partition[cid]
                    if len(members) > max_size and len(members) > 1:
                        # Mark parent cluster as non-final
                        for c in clusters:
                            if c.cluster == cid and c.level == current_level:
                                # Use object.__setattr__ since it might be frozen
                                try:
                                    c.is_final_cluster = False
                                except (AttributeError, TypeError):
                                    pass

                        # Extract subgraph
                        sub_g = graph.subgraph(members)
                        sub_names = [names[i] for i in members]

                        _recursive_partition(
                            sub_g,
                            sub_names,
                            max_size,
                            rng_seed,
                            n_iterations,
                            depth=depth + 1,
                            parent_cluster_id=cid,
                        )

        _recursive_partition(g, node_names, max_cluster_size, seed, iterations)
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

        # Process levels from max (root) to 0 (leaf) to ensure parent communities exist first
        for level in sorted(level_clusters.keys(), reverse=True):
            for cluster_id in level_clusters[level]:
                key = (level, cluster_id)
                entity_ids = level_cluster_map[key]

                # Generate community ID
                community_id = str(uuid.uuid4())
                community_id_map[key] = community_id

                # Find parent community ID
                # Parent cluster is at level+1 (higher in hierarchy)
                parent_community_id: str | None = None
                if cluster_id in parent_map:
                    parent_cluster_id = parent_map[cluster_id]
                    parent_key = (level + 1, parent_cluster_id)
                    parent_community_id = community_id_map.get(parent_key)

                # Calculate rank based on entity count and connections
                rank = len(entity_ids) / 10.0  # Normalize

                # Generate meaningful title from top entities
                if entity_ids:
                    title_entities = entity_ids[:3]
                    title = ", ".join(title_entities)
                    if len(entity_ids) > 3:
                        title += f" +{len(entity_ids) - 3} more"
                else:
                    title = f"Community {cluster_id}"

                community = Community(
                    id=community_id,
                    title=title,
                    level=level,
                    parent_id=parent_community_id,
                    entity_ids=entity_ids,
                    entity_count=len(entity_ids),
                    rank=min(rank, 10.0),  # Cap at 10
                    period=period,
                )
                communities.append(community)

        # Build children_map (reverse of parent_id)
        children_map: dict[str, list[str]] = defaultdict(list)
        for community in communities:
            if community.parent_id:
                children_map[community.parent_id].append(community.id)

        # Fill children_ids for each community
        for community in communities:
            community.children_ids = children_map.get(community.id, [])

        return communities

    async def _generate_community_titles(self, communities: list[Community]) -> None:
        """Use LLM to generate meaningful titles for communities.

        Skips orphan communities (level < 0).

        Args:
            communities: List of communities to generate titles for.
        """
        from core.llm.types import CallPoint

        prompt_loader = self._llm._prompts
        system_prompt = prompt_loader.get("community_title", "system")
        user_template = prompt_loader.get("community_title", "user")

        for community in communities:
            if community.level < 0 or not community.entity_ids:
                continue

            entities_text = ", ".join(community.entity_ids[:20])
            user_content = user_template.format(entities=entities_text)

            try:
                title = await self._llm.call_at(
                    call_point=CallPoint.COMMUNITY_TITLE,
                    payload={
                        "system_prompt": system_prompt,
                        "user_content": user_content,
                    },
                )
                if title and isinstance(title, str):
                    title = title.strip().strip('"').strip("'")
                    if title:
                        community.title = title
                        log.debug(
                            "community_title_generated",
                            community_id=community.id,
                            title=title,
                        )
            except Exception as exc:
                log.warning(
                    "community_title_generation_failed",
                    community_id=community.id,
                    error=str(exc),
                )

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

        # Delegate to shared modularity function
        return _compute_modularity(edges, node_to_cluster)

    async def _persist_communities(self, communities: list[Community]) -> int:
        """Persist communities to Neo4j.

        Args:
            communities: List of communities to persist.

        Returns:
            Number of communities created.
        """
        # Ensure constraints exist
        await self._repo.ensure_constraints()

        # Collect all entity_ids upfront and batch query entity types (O(1) vs O(n))
        all_entity_ids: list[str] = []
        for community in communities:
            if community.entity_ids:
                all_entity_ids.extend(community.entity_ids)

        entity_types_map: dict[str, str] = {}
        if all_entity_ids:
            # Single batch query for all entity types
            entity_types_map = await self._get_entity_types(all_entity_ids)

        created = 0
        for community in communities:
            try:
                await self._repo.create_community(
                    community_id=community.id,
                    title=community.title,
                    level=community.level,
                    parent_id=community.parent_id,
                    children_ids=community.children_ids,
                    entity_count=community.entity_count,
                    rank=community.rank,
                    period=community.period,
                    modularity=community.modularity,
                )

                # Add HAS_ENTITY relationships using pre-fetched entity types
                if community.entity_ids:
                    assignments = [
                        {
                            "community_id": community.id,
                            "entity_name": name,
                            "entity_type": entity_types_map.get(name, "未知"),
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

        if self._database_type == GraphDatabaseType.LADYBUG:
            # LadybugDB: Use IN clause instead of UNWIND
            query = """
            MATCH (e:Entity)
            WHERE e.canonical_name IN $names
            RETURN e.canonical_name AS name, e.type AS type
            """
        else:
            query = """
            UNWIND $names AS name
            MATCH (e:Entity {canonical_name: name})
            RETURN e.canonical_name AS name, e.type AS type
            """
        results = await self._pool.execute_query(query, {"names": entity_names})
        return {r.get("name", ""): r.get("type", "未知") for r in results}
