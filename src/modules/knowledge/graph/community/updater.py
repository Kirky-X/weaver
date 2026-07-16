# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Incremental community updater for knowledge graph.

Periodically updates community assignments based on new entities and relationships,
avoiding full graph rebuilds. Uses 2 hop subgraph extraction and Leiden algorithm
for optimal community detection (falls back to connected components if unavailable).

The updater is now a thin orchestrator composed of four collaborators, each with a
single responsibility:

- ``UpdateTriggerPolicy`` — decides when updates/rebuilds run.
- ``SubgraphClusteringService`` — extracts subgraphs and clusters communities.
- ``DiffWriter`` — persists assignment diffs to the graph database.
- ``ModularityCalculator`` — computes graph modularity.

Public and private methods that previously lived here are preserved as delegating
wrappers so existing callers and tests keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.knowledge.graph.community.health.checker import CommunityHealthChecker
from modules.knowledge.graph.community.health.models import HealthIssue
from modules.knowledge.graph.community.ladybug_dialect import LadybugDialect
from modules.knowledge.graph.community.repair_service import CommunityRepairService
from modules.knowledge.graph.community.updater_clustering import SubgraphClusteringService
from modules.knowledge.graph.community.updater_diff import DiffWriter
from modules.knowledge.graph.community.updater_modularity import ModularityCalculator
from modules.knowledge.graph.community.updater_trigger import UpdateTriggerPolicy

if TYPE_CHECKING:
    from core.llm import LLMClient
    from core.protocols import GraphPool

log = get_logger(__name__)


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

    Implements: CommunityUpdateStrategy

    Args:
        pool: Graph database connection pool.
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
        pool: GraphPool,
        update_threshold: int = 50,
        interval_minutes: int = 30,
        max_subgraph_size: int = 2000,
        full_rebuild_interval_days: int = 7,
        llm_client: LLMClient | None = None,
        database_type: str | None = None,
    ) -> None:
        self._pool = pool
        self.update_threshold = update_threshold
        self.interval_minutes = interval_minutes
        self.max_subgraph_size = max_subgraph_size
        self.full_rebuild_interval_days = full_rebuild_interval_days
        self._llm = llm_client
        # Detect database type from pool if not provided
        if database_type is None:
            self._database_type = pool.database_type
        else:
            self._database_type = database_type

        # Compose collaborators, sharing the same pool and wiring cross-service
        # references back to this updater (used only at call time).
        self._modularity_calculator = ModularityCalculator(pool, database_type=self._database_type)
        self._diff_writer = DiffWriter(pool, database_type=self._database_type)
        self._clustering_service = SubgraphClusteringService(
            pool=pool,
            max_subgraph_size=max_subgraph_size,
            database_type=self._database_type,
            llm_client=llm_client,
            modularity_calculator=self._modularity_calculator,
            diff_writer=self._diff_writer,
            updater=self,
        )
        self._trigger_policy = UpdateTriggerPolicy(
            pool=pool,
            update_threshold=update_threshold,
            interval_minutes=interval_minutes,
            full_rebuild_interval_days=full_rebuild_interval_days,
            clustering_service=self._clustering_service,
            updater=self,
        )

    # ------------------------------------------------------------------ #
    # Orchestration (kept on this class)
    # ------------------------------------------------------------------ #

    async def execute(self, entity_names: list[str]) -> IncrementalUpdateResult:
        """Provide main entry point for incremental community update.

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

    async def _update_metadata(self, result: IncrementalUpdateResult) -> None:
        """Update community metadata after incremental update.

        Args:
            result: Update result to record.
        """
        now_expr = LadybugDialect.now_expression(self._database_type)
        query = f"""
        MERGE (m:_CommunityMetadata {{id: 'singleton'}})
        SET m.last_incremental_update_at = {now_expr},
            m.pending_entity_count = 0
        """
        params: dict[str, object] = LadybugDialect.now_param(self._database_type)

        try:
            await self._pool.execute_query(query, params)
        except Exception as exc:
            log.warning("update_metadata_failed", error=str(exc))

    async def _update_full_rebuild_metadata(self) -> None:
        """Update metadata after full rebuild, including entity count."""
        modularity = await self._calculate_modularity()

        now_expr = LadybugDialect.now_expression(self._database_type)
        pruned_cond = LadybugDialect.pruned_condition(self._database_type, "e")
        if pruned_cond:
            # Neo4j: filter out pruned entities when counting
            where_clause = f"WHERE {pruned_cond}"
        else:
            # LadybugDB: no pruned field in schema
            where_clause = ""

        query = f"""
        MATCH (e:Entity)
        {where_clause}
        WITH count(e) AS entity_count
        MERGE (m:_CommunityMetadata {{id: 'singleton'}})
        SET m.last_full_rebuild_at = {now_expr},
            m.last_incremental_update_at = {now_expr},
            m.pending_entity_count = 0,
            m.entity_count = entity_count,
            m.modularity = coalesce($modularity, m.modularity)
        """

        params: dict[str, object] = {"modularity": modularity}
        params.update(LadybugDialect.now_param(self._database_type))

        try:
            await self._pool.execute_query(query, params)
        except Exception as exc:
            log.warning("update_full_rebuild_metadata_failed", error=str(exc))

    async def increment_pending_count(self, count: int = 1) -> None:
        """Increment the pending entity count.

        Args:
            count: Number to add (default: 1).
        """
        query = """
        MERGE (m:_CommunityMetadata {id: 'singleton'})
        SET m.pending_entity_count = coalesce(m.pending_entity_count, 0) + $count
        """

        try:
            await self._pool.execute_query(query, {"count": count})
        except Exception as exc:
            log.warning("increment_pending_count_failed", error=str(exc))

    async def _run_health_check(self):
        """Run community health check.

        Returns:
            CommunityHealthReport with diagnosis results.
        """

        checker = CommunityHealthChecker(self._pool, modularity_calculator=self)
        return await checker.diagnose_all()

    async def _auto_repair(self, issues: list[HealthIssue]):
        """Auto-repair health issues.

        Args:
            issues: List of HealthIssue to repair.

        Returns:
            RepairSummary with repair results.
        """
        from modules.knowledge.graph.community.health.models import RepairSummary

        # Filter to auto-repairable issues only
        repairable = [i for i in issues if i.auto_repairable]

        if not repairable:
            return RepairSummary()

        repair_service = CommunityRepairService(self._pool)
        return await repair_service.auto_repair(repairable)

    # ------------------------------------------------------------------ #
    # Delegating wrappers (backward compatibility)
    # ------------------------------------------------------------------ #

    # --- UpdateTriggerPolicy ---

    async def should_trigger(
        self,
        pending_count: int,
        last_update_at: datetime | None,
    ) -> bool:
        """Check if incremental update should be triggered. Delegates to trigger policy."""
        return await self._trigger_policy.should_trigger(pending_count, last_update_at)

    async def check_and_run(self) -> dict[str, object]:
        """Unified entry point for community auto-scheduling. Delegates to trigger policy."""
        return await self._trigger_policy.check_and_run()

    async def force_rebuild(self) -> dict[str, object]:
        """Force full community rebuild unconditionally. Delegates to trigger policy."""
        return await self._trigger_policy.force_rebuild()

    async def _get_community_count(self) -> int:
        """Get total number of Community nodes. Delegates to trigger policy."""
        return await self._trigger_policy._get_community_count()

    async def _check_entity_change(self) -> tuple[bool, int, int]:
        """Check if entity count change exceeds threshold. Delegates to trigger policy."""
        return await self._trigger_policy._check_entity_change()

    async def check_full_rebuild_needed(self) -> bool:
        """Check if full rebuild is needed. Delegates to trigger policy."""
        return await self._trigger_policy.check_full_rebuild_needed()

    async def get_stats(self) -> CommunityStats:
        """Get current community update statistics. Delegates to trigger policy."""
        return await self._trigger_policy.get_stats()

    # --- SubgraphClusteringService ---

    def _run_local_clustering(
        self,
        nodes: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Run local clustering using connected components. Delegates to clustering service."""
        return self._clustering_service._run_local_clustering(nodes, edges)

    async def run_incremental_update(
        self,
        entity_names: list[str] | None = None,
    ) -> IncrementalUpdateResult:
        """Run incremental community update. Delegates to clustering service."""
        return await self._clustering_service.run_incremental_update(entity_names)

    async def run_full_rebuild(self) -> IncrementalUpdateResult:
        """Run full community rebuild on the entire graph. Delegates to clustering service."""
        return await self._clustering_service.run_full_rebuild()

    async def _get_pending_entity_names(self) -> list[str]:
        """Get names of entities pending community assignment. Delegates to clustering service."""
        return await self._clustering_service._get_pending_entity_names()

    async def _identify_affected_communities(
        self,
        entity_names: list[str],
    ) -> list[str]:
        """Find communities affected by new/updated entities. Delegates to clustering service."""
        return await self._clustering_service._identify_affected_communities(entity_names)

    async def _extract_subgraph(
        self,
        community_ids: list[str],
    ) -> tuple[list[str], list[tuple[str, str, float]]]:
        """Extract 2-hop subgraph around affected communities. Delegates to clustering service."""
        return await self._clustering_service._extract_subgraph(community_ids)

    async def _get_current_assignments(
        self,
        node_ids: list[str],
    ) -> dict[str, str]:
        """Get current community assignments for nodes. Delegates to clustering service."""
        return await self._clustering_service._get_current_assignments(node_ids)

    async def _cluster_communities(
        self,
        node_ids: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Cluster nodes into communities. Delegates to clustering service."""
        return await self._clustering_service._cluster_communities(node_ids, edges)

    def _cluster_with_leiden(
        self,
        node_ids: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Cluster nodes using Leiden algorithm. Delegates to clustering service."""
        return self._clustering_service._cluster_with_leiden(node_ids, edges)

    def _cluster_with_connected_components(
        self,
        node_ids: list[str],
        edges: list[tuple[str, str, float]],
    ) -> dict[str, str]:
        """Cluster nodes using connected components. Delegates to clustering service."""
        return self._clustering_service._cluster_with_connected_components(node_ids, edges)

    # --- DiffWriter ---

    async def _write_diff(
        self,
        old_assignments: dict[str, str],
        new_assignments: dict[str, str],
    ) -> dict[str, int | dict[str, float]]:
        """Compare old and new assignments, write only changes. Delegates to diff writer."""
        return await self._diff_writer._write_diff(old_assignments, new_assignments)

    async def _reassign_entity(
        self,
        node_id: str,
        old_community_id: str | None,
        new_community_id: str,
    ) -> None:
        """Reassign entity from old community to new community. Delegates to diff writer."""
        await self._diff_writer._reassign_entity(node_id, old_community_id, new_community_id)

    async def _mark_community_empty(self, community_id: str) -> None:
        """Mark a community as empty. Delegates to diff writer."""
        await self._diff_writer._mark_community_empty(community_id)

    async def _mark_stale_reports(
        self,
        community_ids: list[str],
        entity_count_changes: dict[str, float],
    ) -> int:
        """Mark reports stale for communities with >10% entity count change. Delegates to diff writer."""
        return await self._diff_writer._mark_stale_reports(community_ids, entity_count_changes)

    async def _create_communities_for_entities(
        self,
        entity_names: list[str],
    ) -> int:
        """Create new communities for entities without assignments. Delegates to diff writer."""
        return await self._diff_writer._create_communities_for_entities(entity_names)

    async def _create_community_with_entities(
        self,
        community_id: str,
        entity_names: list[str],
    ) -> None:
        """Create a community and assign entities to it. Delegates to diff writer."""
        await self._diff_writer._create_community_with_entities(community_id, entity_names)

    async def _delete_communities_by_ids(self, community_ids: list[str]) -> None:
        """Delete specific communities by their IDs. Delegates to diff writer."""
        await self._diff_writer._delete_communities_by_ids(community_ids)

    async def _write_new_assignments(
        self,
        new_assignments: dict[str, str],
    ) -> dict[str, int]:
        """Write new community assignments after clearing old ones. Delegates to diff writer."""
        return await self._diff_writer._write_new_assignments(new_assignments)

    # --- ModularityCalculator ---

    async def _calculate_modularity(self) -> float | None:
        """Calculate current graph modularity. Delegates to modularity calculator."""
        return await self._modularity_calculator._calculate_modularity()

    async def _get_community_assignments_for_modularity(self) -> dict[str, int]:
        """Get community assignments for modularity calculation. Delegates to modularity calculator."""
        return await self._modularity_calculator._get_community_assignments_for_modularity()
