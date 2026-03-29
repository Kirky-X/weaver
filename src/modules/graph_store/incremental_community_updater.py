# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Incremental community updater for knowledge graph.

Periodically updates community assignments based on new entities and relationships,
avoiding full graph rebuilds. Uses 2-hop subgraph extraction and connected component
clustering (can be replaced with Leiden algorithm).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger

log = get_logger("incremental_community_updater")


@dataclass
class IncrementalUpdateResult:
    """Result of incremental community update operation."""

    affected_communities: int = 0
    entities_reassigned: int = 0
    communities_created: int = 0
    communities_emptied: int = 0
    reports_marked_stale: int = 0
    modularity_before: float | None = None
    modularity_after: float | None = None
    duration_seconds: float = 0.0


@dataclass
class CommunityStats:
    """Statistics for community update tracking."""

    last_full_rebuild_at: datetime | None = None
    last_incremental_update_at: datetime | None = None
    pending_entity_count: int = 0
    total_communities: int = 0
    modularity_history: list[float] = field(default_factory=list)


class IncrementalCommunityUpdater:
    """Incremental community updater for knowledge graph.

    Updates community assignments efficiently by:
    1. Tracking pending entities since last update
    2. Identifying affected communities via 2-hop traversal
    3. Extracting local subgraph for reclustering
    4. Writing only the diff (changed assignments)
    5. Marking stale reports for communities with significant changes

    Triggers incremental update when:
    - Pending entity count >= update_threshold, OR
    - Time since last update >= interval_minutes AND pending > 0

    Triggers full rebuild when:
    - Time since last full rebuild >= full_rebuild_interval_days, OR
    - Entity count changed > ENTITY_CHANGE_THRESHOLD since last rebuild
    - Modularity has degraded (>0.05 cumulative drop over 3 checks)

    Args:
        pool: Neo4j connection pool.
        update_threshold: Minimum pending entities to trigger update (default: 50).
        interval_minutes: Minimum minutes between incremental updates (default: 30).
        max_subgraph_size: Maximum nodes in extracted subgraph (default: 2000).
        full_rebuild_interval_days: Days between full rebuilds (default: 7).
    """

    ENTITY_CHANGE_THRESHOLD: float = 0.10
    REBUILD_INTERVAL_DAYS: int = 7
    LAST_REBUILD_KEY: str = "community:last_rebuild"
    ENTITY_COUNT_KEY: str = "community:entity_count"

    def __init__(
        self,
        pool: Neo4jPool,
        update_threshold: int = 50,
        interval_minutes: int = 30,
        max_subgraph_size: int = 2000,
        full_rebuild_interval_days: int = 7,
    ) -> None:
        self._pool = pool
        self.update_threshold = update_threshold
        self.interval_minutes = interval_minutes
        self.max_subgraph_size = max_subgraph_size
        self.full_rebuild_interval_days = full_rebuild_interval_days

    async def should_trigger(
        self,
        pending_count: int,
        last_update_at: datetime | None,
    ) -> bool:
        """Check if incremental update should be triggered.

        Args:
            pending_count: Number of pending entities since last update.
            last_update_at: Timestamp of last incremental update.

        Returns:
            True if update should be triggered.
        """
        # Condition 1: pending count >= threshold
        if pending_count >= self.update_threshold:
            log.info(
                "should_trigger_count_threshold",
                pending_count=pending_count,
                threshold=self.update_threshold,
            )
            return True

        # Condition 2: time interval passed AND has pending data
        if last_update_at and pending_count > 0:
            minutes_since = (datetime.now(UTC) - last_update_at).total_seconds() / 60
            if minutes_since >= self.interval_minutes:
                log.info(
                    "should_trigger_time_threshold",
                    minutes_since=minutes_since,
                    pending_count=pending_count,
                )
                return True

        return False

    async def check_and_run(self) -> dict[str, object]:
        """Unified entry point for community auto-scheduling.

        Checks all trigger conditions and runs full rebuild if any is met.

        Returns:
            Dict with triggered, reason, and optional details.
        """
        # Check if any communities exist
        community_count = await self._get_community_count()
        if community_count == 0:
            log.info("check_and_run_no_communities")
            result = await self.run_full_rebuild()
            return {
                "triggered": True,
                "reason": "no_communities_exist",
                "communities_created": result.communities_created,
                "entities_reassigned": result.entities_reassigned,
                "duration_seconds": result.duration_seconds,
            }

        # Check entity percentage change
        entity_change_exceeded, current_count, previous_count = await self._check_entity_change()
        if entity_change_exceeded:
            log.info(
                "check_and_run_entity_change_exceeded",
                current_count=current_count,
                previous_count=previous_count,
            )
            result = await self.run_full_rebuild()
            return {
                "triggered": True,
                "reason": "entity_change_exceeded",
                "current_entity_count": current_count,
                "previous_entity_count": previous_count,
                "communities_created": result.communities_created,
                "duration_seconds": result.duration_seconds,
            }

        # Check rebuild interval
        if await self.check_full_rebuild_needed():
            log.info("check_and_run_interval_exceeded")
            result = await self.run_full_rebuild()
            return {
                "triggered": True,
                "reason": "rebuild_interval_exceeded",
                "communities_created": result.communities_created,
                "duration_seconds": result.duration_seconds,
            }

        # No conditions met
        return {"triggered": False, "reason": None}

    async def force_rebuild(self) -> dict[str, object]:
        """Force full community rebuild unconditionally.

        Returns:
            Dict with triggered=True, reason='forced', and rebuild results.
        """
        log.info("force_rebuild_start")
        result = await self.run_full_rebuild()
        return {
            "triggered": True,
            "reason": "forced",
            "communities_created": result.communities_created,
            "modularity": result.modularity_after,
            "duration_seconds": result.duration_seconds,
        }

    async def _get_community_count(self) -> int:
        """Get total number of Community nodes.

        Returns:
            Count of Community nodes in Neo4j.
        """
        query = "MATCH (c:Community) RETURN count(c) AS total"
        try:
            result = await self._pool.execute_query(query)
            return result[0]["total"] if result and result[0] else 0
        except Exception:
            return 0

    async def _check_entity_change(self) -> tuple[bool, int, int]:
        """Check if entity count change exceeds threshold.

        Compares current entity count with the count stored at last rebuild.

        Returns:
            Tuple of (exceeded, current_count, previous_count).
        """
        # Get current entity count
        current_query = """
        MATCH (e:Entity)
        WHERE (e.pruned IS NULL OR e.pruned = false)
        RETURN count(e) AS total
        """
        try:
            result = await self._pool.execute_query(current_query)
            current_count = result[0]["total"] if result and result[0] else 0
        except Exception:
            return False, 0, 0

        # Get previous count from metadata
        previous_query = """
        MATCH (m:_CommunityMetadata)
        RETURN m.entity_count AS previous_count
        """
        try:
            result = await self._pool.execute_query(previous_query)
            previous_count = result[0].get("previous_count", 0) if result and result[0] else 0
        except Exception:
            return False, current_count, 0

        if previous_count is None:
            previous_count = 0

        # Calculate change ratio
        if previous_count > 0:
            change_ratio = abs(current_count - previous_count) / previous_count
            if change_ratio > self.ENTITY_CHANGE_THRESHOLD:
                return True, current_count, previous_count

        return False, current_count, previous_count

    async def get_stats(self) -> CommunityStats:
        """Get current community update statistics.

        Returns:
            CommunityStats with current state.
        """
        stats = CommunityStats()

        # Get last update timestamps from metadata
        metadata_query = """
        MATCH (m:_CommunityMetadata)
        RETURN m.last_full_rebuild_at AS last_full_rebuild,
               m.last_incremental_update_at AS last_incremental,
               m.pending_entity_count AS pending_count
        """

        try:
            result = await self._pool.execute_query(metadata_query)
            if result and result[0]:
                row = result[0]
                stats.last_full_rebuild_at = row.get("last_full_rebuild")
                stats.last_incremental_update_at = row.get("last_incremental")
                stats.pending_entity_count = row.get("pending_count", 0)
        except Exception as exc:
            log.debug("get_community_stats_failed", error=str(exc))

        # Also get current community count
        community_count_query = """
        MATCH (c:Community)
        RETURN count(c) AS total
        """

        try:
            result = await self._pool.execute_query(community_count_query)
            stats.total_communities = result[0]["total"] if result and result[0] else 0
        except Exception:
            stats.total_communities = 0

        return stats

    async def check_full_rebuild_needed(self) -> bool:
        """Check if full rebuild is needed.

        Returns:
            True if full rebuild is needed.
        """
        stats = await self.get_stats()

        # Condition 1: Time since last full rebuild
        if stats.last_full_rebuild_at:
            days_since = (datetime.now(UTC) - stats.last_full_rebuild_at).total_seconds() / 86400
            if days_since >= self.full_rebuild_interval_days:
                log.info(
                    "full_rebuild_needed_time",
                    days_since=days_since,
                    threshold=self.full_rebuild_interval_days,
                )
                return True
        else:
            # Never done a full rebuild
            log.info("full_rebuild_needed_never")
            return True

        # Condition 2: Modularity degradation
        # Check if modularity has dropped cumulatively >0.05 over last 3 checks
        if len(stats.modularity_history) >= 3:
            recent = stats.modularity_history[-3:]
            if len(recent) >= 3:
                drop = recent[0] - recent[-1]
                if drop > 0.05:
                    log.info("full_rebuild_needed_modularity", drop=drop)
                    return True

        return False

    async def execute(self, entity_names: list[str]) -> IncrementalUpdateResult:
        """Main entry point for incremental community update.

        Identifies affected communities, extracts subgraph, clusters,
        writes diff, and marks stale reports.

        Args:
            entity_names: List of new/updated entity canonical names.

        Returns:
            IncrementalUpdateResult with update statistics.
        """
        if not entity_names:
            log.debug("execute_no_entities")
            return IncrementalUpdateResult()

        log.info("incremental_execute_start", entity_count=len(entity_names))

        # Calculate modularity before
        modularity_before = await self._calculate_modularity()

        # Step 1: Identify affected communities
        affected_communities = await self._identify_affected_communities(entity_names)

        if not affected_communities:
            log.info("execute_no_affected_communities")
            return IncrementalUpdateResult(
                modularity_before=modularity_before,
            )

        # Step 2: Extract subgraph
        nodes, edges = await self._extract_subgraph(affected_communities)

        if not nodes:
            log.warning("execute_empty_subgraph")
            return IncrementalUpdateResult(
                affected_communities=len(affected_communities),
                modularity_before=modularity_before,
            )

        # Step 3: Get current assignments
        old_assignments = await self._get_current_assignments(nodes)

        # Step 4: Run local clustering (synchronous)
        new_assignments = self._run_local_clustering(nodes, edges)

        # Step 5: Write diff
        diff_result = await self._write_diff(old_assignments, new_assignments)

        # Step 6: Mark stale reports
        stale_count = await self._mark_stale_reports(
            affected_communities, diff_result.get("entity_count_changes", {})
        )

        # Calculate modularity after
        modularity_after = await self._calculate_modularity()

        result = IncrementalUpdateResult(
            affected_communities=len(affected_communities),
            entities_reassigned=diff_result.get("reassigned", 0),
            communities_created=diff_result.get("created", 0),
            communities_emptied=diff_result.get("emptied", 0),
            reports_marked_stale=stale_count,
            modularity_before=modularity_before,
            modularity_after=modularity_after,
        )

        log.info(
            "incremental_execute_complete",
            affected=result.affected_communities,
            reassigned=result.entities_reassigned,
            created=result.communities_created,
            emptied=result.communities_emptied,
            stale=result.reports_marked_stale,
        )

        return result

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
        adjacency: dict[str, set[str]] = defaultdict(set)
        all_nodes: set[str] = set(nodes)

        for source, target, _ in edges:
            adjacency[source].add(target)
            adjacency[target].add(source)
            all_nodes.add(source)
            all_nodes.add(target)

        visited: set[str] = set()
        assignments: dict[str, str] = {}

        def dfs(start: str, comm_uuid: str) -> None:
            stack = [start]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                assignments[node] = comm_uuid
                for neighbor in adjacency.get(node, []):
                    if neighbor not in visited:
                        stack.append(neighbor)

        for node in all_nodes:
            if node not in visited:
                comm_uuid = str(uuid.uuid4())
                dfs(node, comm_uuid)

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

        start = time.monotonic()
        result = IncrementalUpdateResult()

        log.info("incremental_community_update_start")

        # Get modularity before
        result.modularity_before = await self._calculate_modularity()

        # If entity names not provided, get pending entities
        if entity_names is None:
            entity_names = await self._get_pending_entity_names()

        if not entity_names:
            log.info("incremental_community_update_no_pending")
            await self._update_metadata(result)
            result.duration_seconds = time.monotonic() - start
            return result

        # Step 1: Identify affected communities
        affected_communities = await self._identify_affected_communities(entity_names)
        result.affected_communities = len(affected_communities)

        if not affected_communities:
            log.info("incremental_community_update_no_affected")
            # Create new communities for new entities
            new_communities = await self._create_communities_for_entities(entity_names)
            result.communities_created = new_communities
            await self._update_metadata(result)
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

        # Step 5: Write diff
        diff_result = await self._write_diff(old_assignments, new_assignments)
        result.entities_reassigned = diff_result["reassigned"]
        result.communities_created = diff_result["created"]
        result.communities_emptied = diff_result["emptied"]

        # Step 6: Mark stale reports
        result.reports_marked_stale = await self._mark_stale_reports(
            affected_communities, diff_result["entity_count_changes"]
        )

        # Get modularity after
        result.modularity_after = await self._calculate_modularity()

        # Update metadata
        await self._update_metadata(result)

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

        start = time.monotonic()
        result = IncrementalUpdateResult()

        log.info("full_community_rebuild_start")

        # Get modularity before
        result.modularity_before = await self._calculate_modularity()

        # Delegate to CommunityDetector for Leiden-based rebuild
        from modules.graph_store.community_detector import CommunityDetector

        detector = CommunityDetector(pool=self._pool)
        detection_result = await detector.rebuild_communities()

        result.communities_created = detection_result.total_communities
        result.entities_reassigned = detection_result.total_entities
        result.modularity_after = detection_result.modularity

        # Update metadata including entity count
        await self._update_full_rebuild_metadata()

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

        # First, find communities directly containing these entities
        # Then, find neighboring communities through 2-hop entity relationships
        query = """
        MATCH (e:Entity)-[:HAS_ENTITY]-(c:Community)
        WHERE e.canonical_name IN $names
        WITH DISTINCT c.id AS community_id
        MATCH (c:Community)-[:HAS_ENTITY]-(e1:Entity)-[r]-(e2:Entity)-[:HAS_ENTITY]-(c2:Community)
        WHERE NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']
          AND (e2.pruned IS NULL OR e2.pruned = false)
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

        query = """
        MATCH (c:Community)-[:HAS_ENTITY]-(e1:Entity)
        WHERE c.id IN $community_ids
          AND (e1.pruned IS NULL OR e1.pruned = false)
        WITH e1
        MATCH (e1)-[r]-(e2:Entity)
        WHERE NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']
          AND (e2.pruned IS NULL OR e2.pruned = false)
        RETURN DISTINCT
               elementId(e1) AS id1,
               elementId(e2) AS id2,
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
        """Cluster nodes into communities using connected components.

        TODO: Replace with Leiden algorithm for better community detection.
        Install python-igraph and leidenalg, then use:
            import igraph as ig
            from leidenalg import find_partition
            g = ig.Graph(len(node_ids), edges=(...))
            partition = find_partition(g, leidenalg.ModularityVertexPartition)

        Args:
            node_ids: List of node IDs.
            edges: List of (source, target, weight) tuples.

        Returns:
            Dict mapping node_id to new community_id.
        """
        if not node_ids:
            return {}

        # Build adjacency list
        adjacency: dict[str, set[str]] = defaultdict(set)
        node_id_set = set(node_ids)

        for source, target, _weight in edges:
            if source in node_id_set and target in node_id_set:
                adjacency[source].add(target)
                adjacency[target].add(source)

        # Find connected components
        visited: set[str] = set()
        assignments: dict[str, str] = {}
        community_num = 0

        for node_id in node_ids:
            if node_id in visited:
                continue

            # Start a new community
            community_id = str(uuid.uuid4())
            stack = [node_id]

            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                assignments[current] = community_id

                for neighbor in adjacency.get(current, []):
                    if neighbor not in visited and neighbor in node_id_set:
                        stack.append(neighbor)

            community_num += 1

        log.debug(
            "clustering_complete",
            communities=community_num,
            nodes=len(assignments),
        )

        return assignments

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

        # Write changes to Neo4j
        for node_id, new_comm in new_assignments.items():
            old_comm = old_assignments.get(node_id)
            if old_comm != new_comm:
                await self._reassign_entity(node_id, old_comm, new_comm)

        # Check for emptied communities
        for comm_id, change in entity_count_changes.items():
            # Get current entity count for the community
            count_query = """
            MATCH (c:Community {id: $community_id})<-[:HAS_ENTITY]-(e:Entity)
            WHERE (e.pruned IS NULL OR e.pruned = false)
            RETURN count(e) AS count
            """
            try:
                result = await self._pool.execute_query(count_query, {"community_id": comm_id})
                if result and result[0]["count"] == 0:
                    await self._mark_community_empty(comm_id)
                    emptied += 1
            except Exception as exc:
                log.warning("check_empty_community_failed", comm_id=comm_id, error=str(exc))

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

        # Create new HAS_ENTITY relationship and community if needed
        create_query = """
        MERGE (c:Community {id: $community_id})
        ON CREATE SET
            c.created_at = datetime(),
            c.level = 0
        WITH c
        MATCH (e)
        WHERE elementId(e) = $node_id
        MERGE (c)-[r:HAS_ENTITY]->(e)
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
        counts_query = """
        MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)
        WHERE c.id IN $community_ids
          AND (e.pruned IS NULL OR e.pruned = false)
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
        stale_query = """
        MATCH (c:Community)-[:HAS_REPORT]->(r:CommunityReport)
        WHERE c.id IN $community_ids
        SET r.stale = true,
            r.stale_at = datetime()
        RETURN count(r) AS stale_count
        """

        try:
            results = await self._pool.execute_query(
                stale_query, {"community_ids": stale_communities}
            )
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
        query = """
        MATCH (e:Entity)
        WHERE e.canonical_name IN $names
          AND (e.pruned IS NULL OR e.pruned = false)
        OPTIONAL MATCH (e)-[r]-(other:Entity)
        WHERE NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']
          AND other.canonical_name IN $names
          AND (other.pruned IS NULL OR other.pruned = false)
        WITH e, collect(DISTINCT other.canonical_name) AS neighbors
        RETURN e.canonical_name AS entity, neighbors
        """

        try:
            results = await self._pool.execute_query(query, {"names": entity_names})

            # Build adjacency
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

            # Find connected components
            visited: set[str] = set()
            created = 0

            for entity in all_entities:
                if entity in visited:
                    continue

                # Create new community for this component
                community_id = str(uuid.uuid4())
                stack = [entity]
                component_entities: list[str] = []

                while stack:
                    current = stack.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    component_entities.append(current)

                    for neighbor in adjacency.get(current, []):
                        if neighbor not in visited:
                            stack.append(neighbor)

                # Create community and assign entities
                if component_entities:
                    await self._create_community_with_entities(community_id, component_entities)
                    created += 1

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
        query = """
        MERGE (c:Community {id: $community_id})
        ON CREATE SET
            c.created_at = datetime(),
            c.level = 0,
            c.entity_count = 0
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

    async def _delete_all_communities(self) -> None:
        """Delete all community nodes and relationships."""
        query = """
        MATCH (c:Community)
        DETACH DELETE c
        """

        try:
            await self._pool.execute_query(query)
        except Exception as exc:
            log.warning("delete_all_communities_failed", error=str(exc))

    async def _calculate_modularity(self) -> float | None:
        """Calculate current graph modularity.

        Returns:
            Modularity score or None if calculation fails.
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

        try:
            results = await self._pool.execute_query(query)
            if not results:
                return None

            edges = [(r["source"], r["target"], r["weight"]) for r in results]
            if not edges:
                return None

            # Get community assignments for modularity calculation
            assignments = await self._get_community_assignments_for_modularity()

            return self._compute_modularity(edges, assignments)

        except Exception as exc:
            log.debug("calculate_modularity_failed", error=str(exc))
            return None

    async def _get_community_assignments_for_modularity(self) -> dict[str, int]:
        """Get community assignments for modularity calculation.

        Returns:
            Dict mapping entity canonical name to community ID (int).
        """
        query = """
        MATCH (e:Entity)<-[:HAS_ENTITY]-(c:Community)
        WHERE (e.pruned IS NULL OR e.pruned = false)
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

    def _compute_modularity(
        self,
        edges: list[tuple[str, str, float]],
        partitions: dict[str, int],
        resolution: float = 1.0,
    ) -> float:
        """Compute modularity score from edges and partitions.

        Based on the standard modularity formula.

        Args:
            edges: List of (source, target, weight) tuples.
            partitions: Dict mapping node name to community ID.
            resolution: Resolution parameter.

        Returns:
            Modularity score.
        """
        if not edges or not partitions:
            return 0.0

        total_weight = sum(e[2] for e in edges)
        if total_weight == 0:
            return 0.0

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

    async def _update_metadata(self, result: IncrementalUpdateResult) -> None:
        """Update community metadata after incremental update.

        Args:
            result: Update result to record.
        """
        query = """
        MERGE (m:_CommunityMetadata)
        SET m.last_incremental_update_at = datetime(),
            m.pending_entity_count = 0
        """

        try:
            await self._pool.execute_query(query)
        except Exception as exc:
            log.warning("update_metadata_failed", error=str(exc))

    async def _update_full_rebuild_metadata(self) -> None:
        """Update metadata after full rebuild, including entity count."""
        modularity = await self._calculate_modularity()

        query = """
        MATCH (e:Entity)
        WHERE (e.pruned IS NULL OR e.pruned = false)
        WITH count(e) AS entity_count
        MERGE (m:_CommunityMetadata)
        SET m.last_full_rebuild_at = datetime(),
            m.last_incremental_update_at = datetime(),
            m.pending_entity_count = 0,
            m.entity_count = entity_count,
            m.modularity = coalesce($modularity, m.modularity)
        """

        try:
            await self._pool.execute_query(query, {"modularity": modularity})
        except Exception as exc:
            log.warning("update_full_rebuild_metadata_failed", error=str(exc))

    async def increment_pending_count(self, count: int = 1) -> None:
        """Increment the pending entity count.

        Args:
            count: Number to add (default: 1).
        """
        query = """
        MERGE (m:_CommunityMetadata)
        SET m.pending_entity_count = coalesce(m.pending_entity_count, 0) + $count
        """

        try:
            await self._pool.execute_query(query, {"count": count})
        except Exception as exc:
            log.warning("increment_pending_count_failed", error=str(exc))
