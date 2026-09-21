# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Community repair service for fixing detected health issues.

Provides methods to automatically repair common community health issues
including empty communities, entity count mismatches, stale reports,
and broken hierarchy references.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from core.constants import DatabaseType
from core.observability import get_logger
from modules.knowledge.graph.community.health.models import (
    HealthIssue,
    IssueType,
    RepairResult,
    RepairSummary,
)
from modules.knowledge.graph.community.ladybug_dialect import LadybugDialect

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger(__name__)


class CommunityRepairService:
    """Service for repairing community health issues.

    Provides automatic repair for:
    - Empty communities (delete)
    - Entity count mismatches (update)
    - Stale reports (regenerate)
    - Broken hierarchy references (clean up)

    Implements: CommunityRepairStrategy
    """

    def __init__(
        self,
        pool: GraphPool,
        report_generator: Any | None = None,
    ) -> None:
        """Initialize the repair service.

        Args:
            pool: Graph database connection pool.
            report_generator: Optional CommunityReportGenerator for regenerating reports.
        """
        self._pool = pool
        self._report_generator = report_generator
        # Detect database type for LadybugDB dialect handling (same pattern
        # as CommunityHealthRepo).
        self._database_type = getattr(pool, "database_type", DatabaseType.NEO4J.value)

    async def repair_empty_communities(self, dry_run: bool = False) -> RepairResult:
        """Delete communities with no associated entities.

        Args:
            dry_run: If True, only count without deleting.

        Returns:
            RepairResult with deletion count.
        """
        # First count the empty communities
        count_query = """
        MATCH (c:Community)
        WHERE NOT (c)-[:HAS_ENTITY]->(:Entity)
          AND c.level >= 0
        RETURN count(c) AS count
        """

        try:
            results = await self._pool.execute_query(count_query)
            count = results[0]["count"] if results and results[0] else 0

            if count == 0:
                return RepairResult(
                    repair_type="delete_empty_communities",
                    affected_count=0,
                    success=True,
                )

            if dry_run:
                log.info("dry_run_delete_empty_communities", count=count)
                return RepairResult(
                    repair_type="delete_empty_communities",
                    affected_count=count,
                    success=True,
                    error="dry_run",
                )

            # Actually delete
            delete_query = """
            MATCH (c:Community)
            WHERE NOT (c)-[:HAS_ENTITY]->(:Entity)
              AND c.level >= 0
            DETACH DELETE c
            RETURN count(c) AS deleted
            """

            await self._pool.execute_query(delete_query)
            log.info("deleted_empty_communities", count=count)

            return RepairResult(
                repair_type="delete_empty_communities",
                affected_count=count,
                success=True,
            )

        except Exception as exc:
            log.error("repair_empty_communities_failed", error=str(exc))
            return RepairResult(
                repair_type="delete_empty_communities",
                affected_count=0,
                success=False,
                error=str(exc),
            )

    async def repair_entity_count_mismatches(self, dry_run: bool = False) -> RepairResult:
        """Update entity_count to match actual HAS_ENTITY relationships.

        Args:
            dry_run: If True, only count without updating.

        Returns:
            RepairResult with update count.
        """
        # Count mismatches (LadybugDB has no pruned property / datetime())
        pruned_cond = LadybugDialect.pruned_condition(self._database_type, "e")
        pruned_clause = f"WHERE ({pruned_cond})" if pruned_cond else ""
        count_query = f"""
        MATCH (c:Community)
        OPTIONAL MATCH (c)-[:HAS_ENTITY]->(e:Entity)
        {pruned_clause}
        WITH c, count(e) AS actual_count
        WHERE c.entity_count <> actual_count
        RETURN count(c) AS count
        """

        try:
            results = await self._pool.execute_query(count_query)
            count = results[0]["count"] if results and results[0] else 0

            if count == 0:
                return RepairResult(
                    repair_type="update_entity_counts",
                    affected_count=0,
                    success=True,
                )

            if dry_run:
                log.info("dry_run_update_entity_counts", count=count)
                return RepairResult(
                    repair_type="update_entity_counts",
                    affected_count=count,
                    success=True,
                    error="dry_run",
                )

            # Actually update (datetime() touch is Neo4j-only)
            touch_clause = (
                ", c.updated_at = datetime()"
                if not LadybugDialect.is_ladybug(self._database_type)
                else ""
            )
            update_query = f"""
            MATCH (c:Community)
            OPTIONAL MATCH (c)-[:HAS_ENTITY]->(e:Entity)
            {pruned_clause}
            WITH c, count(e) AS actual_count
            WHERE c.entity_count <> actual_count
            SET c.entity_count = actual_count{touch_clause}
            RETURN count(c) AS updated
            """

            await self._pool.execute_query(update_query)
            log.info("updated_entity_counts", count=count)

            return RepairResult(
                repair_type="update_entity_counts",
                affected_count=count,
                success=True,
            )

        except Exception as exc:
            log.error("repair_entity_count_mismatches_failed", error=str(exc))
            return RepairResult(
                repair_type="update_entity_counts",
                affected_count=0,
                success=False,
                error=str(exc),
            )

    async def repair_hierarchy_breaks(self, dry_run: bool = False) -> RepairResult:
        """Clear parent_id references pointing to non-existent communities.

        Args:
            dry_run: If True, only count without updating.

        Returns:
            RepairResult with update count.
        """
        # LadybugDB doesn't support NOT EXISTS subqueries — use the same
        # OPTIONAL MATCH + WHERE r IS NULL pattern as CommunityHealthRepo.
        is_ladybug = LadybugDialect.is_ladybug(self._database_type)
        if is_ladybug:
            count_query = """
            MATCH (c:Community)
            WHERE c.parent_id IS NOT NULL
            OPTIONAL MATCH (p:Community {id: c.parent_id})
            WITH c, p
            WHERE p IS NULL
            RETURN count(c) AS count
            """
        else:
            count_query = """
            MATCH (c:Community)
            WHERE c.parent_id IS NOT NULL
              AND NOT EXISTS((:Community {id: c.parent_id}))
            RETURN count(c) AS count
            """

        try:
            results = await self._pool.execute_query(count_query)
            count = results[0]["count"] if results and results[0] else 0

            if count == 0:
                return RepairResult(
                    repair_type="clear_broken_parent_ids",
                    affected_count=0,
                    success=True,
                )

            if dry_run:
                log.info("dry_run_clear_broken_parent_ids", count=count)
                return RepairResult(
                    repair_type="clear_broken_parent_ids",
                    affected_count=count,
                    success=True,
                    error="dry_run",
                )

            # Actually clear (datetime() touch is Neo4j-only)
            touch_clause = ", c.updated_at = datetime()" if not is_ladybug else ""
            if is_ladybug:
                clear_query = f"""
                MATCH (c:Community)
                WHERE c.parent_id IS NOT NULL
                OPTIONAL MATCH (p:Community {{id: c.parent_id}})
                WITH c, p
                WHERE p IS NULL
                SET c.parent_id = null{touch_clause}
                RETURN count(c) AS cleared
                """
            else:
                clear_query = f"""
                MATCH (c:Community)
                WHERE c.parent_id IS NOT NULL
                  AND NOT EXISTS((:Community {{id: c.parent_id}}))
                SET c.parent_id = null{touch_clause}
                RETURN count(c) AS cleared
                """

            await self._pool.execute_query(clear_query)
            log.info("cleared_broken_parent_ids", count=count)

            return RepairResult(
                repair_type="clear_broken_parent_ids",
                affected_count=count,
                success=True,
            )

        except Exception as exc:
            log.error("repair_hierarchy_breaks_failed", error=str(exc))
            return RepairResult(
                repair_type="clear_broken_parent_ids",
                affected_count=0,
                success=False,
                error=str(exc),
            )

    async def repair_stale_reports(
        self,
        community_ids: list[str] | None = None,
        dry_run: bool = False,
    ) -> RepairResult:
        """Regenerate stale reports.

        Args:
            community_ids: Specific community IDs to regenerate, or None for all stale.
            dry_run: If True, only count without regenerating.

        Returns:
            RepairResult with regeneration count.
        """
        if self._report_generator is None:
            return RepairResult(
                repair_type="regenerate_stale_reports",
                affected_count=0,
                success=False,
                error="report_generator not configured",
            )

        # Find stale reports (LadybugDB: no duration() — stale flag only)
        if LadybugDialect.is_ladybug(self._database_type):
            if community_ids:
                query = """
                MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
                WHERE c.id IN $community_ids AND r.stale = true
                RETURN c.id AS community_id
                """
                params: dict[str, Any] = {"community_ids": community_ids}
            else:
                query = """
                MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
                WHERE r.stale = true
                RETURN c.id AS community_id
                """
                params = {}
        elif community_ids:
            query = """
            MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
            WHERE c.id IN $community_ids
              AND (r.stale = true OR r.updated_at < datetime() - duration('P7D'))
            RETURN c.id AS community_id
            """
            params = {"community_ids": community_ids}
        else:
            query = """
            MATCH (r:CommunityReport)-[:REPORTS_ON]->(c:Community)
            WHERE r.stale = true
               OR r.updated_at < datetime() - duration('P7D')
            RETURN c.id AS community_id
            """
            params = {}

        try:
            results = await self._pool.execute_query(query, params)
            stale_community_ids = [r["community_id"] for r in results if r.get("community_id")]
            count = len(stale_community_ids)

            if count == 0:
                return RepairResult(
                    repair_type="regenerate_stale_reports",
                    affected_count=0,
                    success=True,
                )

            if dry_run:
                log.info("dry_run_regenerate_stale_reports", count=count)
                return RepairResult(
                    repair_type="regenerate_stale_reports",
                    affected_count=count,
                    success=True,
                    error="dry_run",
                )

            # Regenerate reports
            success_count = 0
            failed_ids: list[str] = []

            for cid in stale_community_ids:
                try:
                    result = await self._report_generator.regenerate_report(cid)
                    if result.success:
                        success_count += 1
                    else:
                        failed_ids.append(cid)
                except Exception as exc:
                    log.warning(
                        "regenerate_report_failed",
                        community_id=cid,
                        error=str(exc),
                    )
                    failed_ids.append(cid)

            log.info(
                "regenerated_stale_reports",
                success=success_count,
                failed=len(failed_ids),
            )

            return RepairResult(
                repair_type="regenerate_stale_reports",
                affected_count=success_count,
                success=len(failed_ids) == 0,
                error=f"failed_ids: {failed_ids}" if failed_ids else None,
            )

        except Exception as exc:
            log.error("repair_stale_reports_failed", error=str(exc))
            return RepairResult(
                repair_type="regenerate_stale_reports",
                affected_count=0,
                success=False,
                error=str(exc),
            )

    async def auto_repair(
        self,
        issues: list[HealthIssue],
        dry_run: bool = False,
    ) -> RepairSummary:
        """Automatically repair all repairable issues.

        Args:
            issues: List of HealthIssue to repair.
            dry_run: If True, only count without making changes.

        Returns:
            RepairSummary with all repair results.
        """
        start = time.monotonic()
        results: list[RepairResult] = []
        total_repaired = 0

        # Filter to only auto-repairable issues
        repairable_issues = [i for i in issues if i.auto_repairable]

        # Group by issue type
        issue_types = {i.issue_type for i in repairable_issues}

        # Repair empty communities
        if IssueType.EMPTY_COMMUNITY in issue_types:
            result = await self.repair_empty_communities(dry_run)
            results.append(result)
            if result.success:
                total_repaired += result.affected_count

        # Repair entity count mismatches
        if IssueType.ENTITY_COUNT_MISMATCH in issue_types:
            result = await self.repair_entity_count_mismatches(dry_run)
            results.append(result)
            if result.success:
                total_repaired += result.affected_count

        # Repair hierarchy breaks
        if IssueType.HIERARCHY_BREAK in issue_types:
            result = await self.repair_hierarchy_breaks(dry_run)
            results.append(result)
            if result.success:
                total_repaired += result.affected_count

        # Repair stale reports (targeted: only the communities named in the issues)
        if IssueType.STALE_REPORT in issue_types:
            stale_community_ids = [
                i.community_id
                for i in repairable_issues
                if i.issue_type == IssueType.STALE_REPORT and i.community_id
            ]
            result = await self.repair_stale_reports(
                community_ids=stale_community_ids, dry_run=dry_run
            )
            results.append(result)
            if result.success:
                total_repaired += result.affected_count

        # Repair missing reports (generate reports for communities without them)
        if IssueType.MISSING_REPORT in issue_types:
            missing_community_ids = [
                i.community_id
                for i in repairable_issues
                if i.issue_type == IssueType.MISSING_REPORT and i.community_id
            ]
            result = await self.repair_missing_reports(
                community_ids=missing_community_ids, dry_run=dry_run
            )
            results.append(result)
            if result.success:
                total_repaired += result.affected_count

        duration = (time.monotonic() - start) * 1000

        log.info(
            "auto_repair_complete",
            total_repaired=total_repaired,
            operations=len(results),
            duration_ms=duration,
        )

        return RepairSummary(
            results=results,
            total_repaired=total_repaired,
            duration_ms=duration,
        )

    async def repair_missing_reports(
        self,
        community_ids: list[str],
        dry_run: bool = False,
    ) -> RepairResult:
        """Generate missing reports for communities without them.

        Args:
            community_ids: List of community IDs needing reports.
            dry_run: If True, only count without generating.

        Returns:
            RepairResult with count of reports generated.
        """
        if self._report_generator is None:
            return RepairResult(
                repair_type="generate_missing_reports",
                affected_count=0,
                success=False,
                error="report_generator not configured",
            )

        if dry_run:
            return RepairResult(
                repair_type="generate_missing_reports",
                affected_count=len(community_ids),
                success=True,
                error="dry_run",
            )

        success_count = 0
        failed_ids: list[str] = []

        for cid in community_ids:
            try:
                result = await self._report_generator.regenerate_report(cid)
                # ReportGenerationResult is always truthy — check .success
                # (same as repair_stale_reports) so failures are not
                # silently counted as successes.
                if result.success:
                    success_count += 1
                else:
                    failed_ids.append(cid)
            except Exception as exc:
                log.warning(
                    "missing_report_generation_failed",
                    community_id=cid,
                    error=str(exc),
                )
                failed_ids.append(cid)

        log.info(
            "generated_missing_reports",
            success=success_count,
            failed=len(failed_ids),
        )

        # Partial failures must surface: success only when nothing failed
        # (consistent with repair_stale_reports).
        return RepairResult(
            repair_type="generate_missing_reports",
            affected_count=success_count,
            success=len(failed_ids) == 0,
            error=f"failed_ids: {failed_ids}" if failed_ids else None,
        )
