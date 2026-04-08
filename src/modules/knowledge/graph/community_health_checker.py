# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community health checker for diagnosing community issues.

Performs comprehensive health diagnostics on the community system including
empty communities, missing reports, stale reports, hierarchy integrity, and modularity.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from core.observability.logging import get_logger
from modules.knowledge.graph.community_health_models import (
    CommunityHealthReport,
    CommunityHealthStatus,
    HealthIssue,
    IssueType,
)
from modules.knowledge.graph.community_health_repo import CommunityHealthRepo

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger("community_health_checker")


class CommunityHealthChecker:
    """Checker for community health diagnostics.

    Performs comprehensive health checks on the community system:
    - Empty communities (no entities)
    - Entity count mismatches
    - Missing reports
    - Stale reports
    - Hierarchy integrity
    - Modularity score

    The checker is read-only and does not modify any data.

    Implements: CommunityHealthDiagnostic
    """

    # Scoring thresholds
    EMPTY_COMMUNITY_CRITICAL_RATIO = 0.10  # 10% empty = critical
    EMPTY_COMMUNITY_WARNING_RATIO = 0.05  # 5% empty = warning
    ENTITY_MISMATCH_WARNING_RATIO = 0.20  # 20% mismatch = warning
    REPORT_MISSING_WARNING_RATIO = 0.30  # 30% missing = warning
    LOW_MODULARITY_THRESHOLD = 0.1
    CRITICAL_MODULARITY_THRESHOLD = 0.0

    # Score penalties
    PENALTY_EMPTY_CRITICAL = 30
    PENALTY_EMPTY_WARNING = 15
    PENALTY_ENTITY_MISMATCH = 10
    PENALTY_REPORT_MISSING = 10
    PENALTY_REPORT_STALE = 5
    PENALTY_HIERARCHY_BREAK = 15
    PENALTY_LOW_MODULARITY = 10
    PENALTY_CRITICAL_MODULARITY = 20

    def __init__(
        self,
        pool: GraphPool,
        modularity_calculator: object | None = None,
    ) -> None:
        """Initialize the health checker.

        Args:
            pool: Graph database connection pool.
            modularity_calculator: Optional object with _calculate_modularity() method.
                If None, modularity check will be skipped.
        """
        self._pool = pool
        self._repo = CommunityHealthRepo(pool)
        self._modularity_calculator = modularity_calculator

    async def diagnose_all(self) -> CommunityHealthReport:
        """Perform comprehensive community health diagnostics.

        Runs all diagnostic checks and aggregates the results into a health report.

        Returns:
            CommunityHealthReport with overall status, score, and issues.
        """
        start = time.monotonic()
        all_issues: list[HealthIssue] = []

        # Run all checks
        empty_issues = await self.check_empty_communities()
        all_issues.extend(empty_issues)

        count_issues = await self.check_entity_count_inconsistency()
        all_issues.extend(count_issues)

        missing_report_issues = await self.check_missing_reports()
        all_issues.extend(missing_report_issues)

        stale_issues = await self.check_stale_reports()
        all_issues.extend(stale_issues)

        hierarchy_issues = await self.check_hierarchy_integrity()
        all_issues.extend(hierarchy_issues)

        modularity_issues = await self.check_modularity_score()
        all_issues.extend(modularity_issues)

        # Get overall metrics
        metrics = await self._repo.get_overall_metrics()

        # Calculate health score
        score = self._calculate_health_score(all_issues, metrics)

        # Determine overall status
        status = self._determine_status(score)

        duration = (time.monotonic() - start) * 1000
        log.info(
            "community_health_diagnosis_complete",
            status=status.value,
            score=score,
            issues=len(all_issues),
            duration_ms=duration,
        )

        return CommunityHealthReport(
            status=status,
            score=score,
            issues=all_issues,
            metrics=metrics,
        )

    async def check_empty_communities(self) -> list[HealthIssue]:
        """Check for communities with no associated entities.

        Returns:
            List of HealthIssue for empty communities.
        """
        issues: list[HealthIssue] = []
        empty_communities = await self._repo.find_empty_communities()

        if not empty_communities:
            return issues

        for comm in empty_communities:
            issues.append(
                HealthIssue(
                    issue_type=IssueType.EMPTY_COMMUNITY,
                    severity="high",
                    community_id=comm.get("community_id"),
                    description=f"Community '{comm.get('title', 'Unknown')}' has no associated entities",
                    suggestion="Delete the empty community or run community detection to reassign entities",
                    auto_repairable=True,
                )
            )

        log.debug("found_empty_communities", count=len(empty_communities))
        return issues

    async def check_entity_count_inconsistency(self) -> list[HealthIssue]:
        """Check for communities where stored count doesn't match actual count.

        Returns:
            List of HealthIssue for count mismatches.
        """
        issues: list[HealthIssue] = []
        mismatches = await self._repo.find_entity_count_mismatches()

        if not mismatches:
            return issues

        for mismatch in mismatches:
            stored = mismatch.get("stored_count", 0)
            actual = mismatch.get("actual_count", 0)
            issues.append(
                HealthIssue(
                    issue_type=IssueType.ENTITY_COUNT_MISMATCH,
                    severity="low",
                    community_id=mismatch.get("community_id"),
                    description=f"Entity count mismatch: stored={stored}, actual={actual}",
                    suggestion="Update the entity_count property to match actual count",
                    auto_repairable=True,
                )
            )

        log.debug("found_count_mismatches", count=len(mismatches))
        return issues

    async def check_missing_reports(self) -> list[HealthIssue]:
        """Check for communities without reports.

        Returns:
            List of HealthIssue for communities missing reports.
        """
        issues: list[HealthIssue] = []
        missing_reports = await self._repo.find_missing_reports()

        if not missing_reports:
            return issues

        for comm in missing_reports:
            issues.append(
                HealthIssue(
                    issue_type=IssueType.MISSING_REPORT,
                    severity="medium",
                    community_id=comm.get("community_id"),
                    description=f"Community '{comm.get('title', 'Unknown')}' is missing a report",
                    suggestion="Generate a report for this community using the report generator",
                    auto_repairable=True,
                )
            )

        log.debug("found_missing_reports", count=len(missing_reports))
        return issues

    async def check_stale_reports(self, days_threshold: int = 7) -> list[HealthIssue]:
        """Check for communities with stale or outdated reports.

        Args:
            days_threshold: Number of days after which a report is considered stale.

        Returns:
            List of HealthIssue for stale reports.
        """
        issues: list[HealthIssue] = []
        stale_reports = await self._repo.find_stale_reports(days_threshold)

        if not stale_reports:
            return issues

        for report in stale_reports:
            issues.append(
                HealthIssue(
                    issue_type=IssueType.STALE_REPORT,
                    severity="low",
                    community_id=report.get("community_id"),
                    description=f"Report is stale (updated: {report.get('updated_at', 'unknown')})",
                    suggestion="Regenerate the report to reflect current community state",
                    auto_repairable=True,
                )
            )

        log.debug("found_stale_reports", count=len(stale_reports))
        return issues

    async def check_hierarchy_integrity(self) -> list[HealthIssue]:
        """Check for broken hierarchy references.

        Returns:
            List of HealthIssue for hierarchy breaks.
        """
        issues: list[HealthIssue] = []
        breaks = await self._repo.find_hierarchy_breaks()

        if not breaks:
            return issues

        for brk in breaks:
            issues.append(
                HealthIssue(
                    issue_type=IssueType.HIERARCHY_BREAK,
                    severity="medium",
                    community_id=brk.get("community_id"),
                    description=f"Community references non-existent parent: {brk.get('parent_id')}",
                    suggestion="Clear the parent_id or run community detection to rebuild hierarchy",
                    auto_repairable=True,
                )
            )

        log.debug("found_hierarchy_breaks", count=len(breaks))
        return issues

    async def check_modularity_score(self) -> list[HealthIssue]:
        """Check the modularity score of the community structure.

        Returns:
            List of HealthIssue if modularity is low.
        """
        issues: list[HealthIssue] = []

        # Skip if no modularity calculator provided
        if self._modularity_calculator is None:
            return issues

        try:
            modularity = await self._modularity_calculator._calculate_modularity()
            if modularity is None:
                return issues

            if modularity < self.CRITICAL_MODULARITY_THRESHOLD:
                issues.append(
                    HealthIssue(
                        issue_type=IssueType.LOW_MODULARITY,
                        severity="high",
                        community_id=None,
                        description=f"Critical modularity score: {modularity:.4f}",
                        suggestion="Run full community rebuild to improve graph partitioning quality",
                        auto_repairable=False,
                    )
                )
            elif modularity < self.LOW_MODULARITY_THRESHOLD:
                issues.append(
                    HealthIssue(
                        issue_type=IssueType.LOW_MODULARITY,
                        severity="medium",
                        community_id=None,
                        description=f"Low modularity score: {modularity:.4f}",
                        suggestion="Consider running community detection to improve partitioning",
                        auto_repairable=False,
                    )
                )

            log.debug("modularity_check", modularity=modularity)
        except Exception as exc:
            log.warning("modularity_check_failed", error=str(exc))

        return issues

    def _calculate_health_score(
        self,
        issues: list[HealthIssue],
        metrics: dict,
    ) -> float:
        """Calculate health score based on issues and metrics.

        Starting from 100, applies penalties for each issue type.

        Args:
            issues: List of detected issues.
            metrics: Overall metrics.

        Returns:
            Health score (0-100).
        """
        score = 100.0

        # Get counts
        total_communities = metrics.get("total_communities", 0)
        empty_count = metrics.get("empty_community_count", 0)
        stale_count = metrics.get("stale_report_count", 0)

        # Calculate ratios
        if total_communities > 0:
            empty_ratio = empty_count / total_communities
        else:
            # No communities = critical
            return 0.0

        # Apply penalties based on ratios and issue counts
        if empty_ratio >= self.EMPTY_COMMUNITY_CRITICAL_RATIO:
            score -= self.PENALTY_EMPTY_CRITICAL
        elif empty_ratio >= self.EMPTY_COMMUNITY_WARNING_RATIO:
            score -= self.PENALTY_EMPTY_WARNING

        # Count issues by type
        issue_counts: dict[IssueType, int] = {}
        for issue in issues:
            issue_counts[issue.issue_type] = issue_counts.get(issue.issue_type, 0) + 1

        # Entity count mismatch penalty
        mismatch_count = issue_counts.get(IssueType.ENTITY_COUNT_MISMATCH, 0)
        if (
            total_communities > 0
            and mismatch_count / total_communities > self.ENTITY_MISMATCH_WARNING_RATIO
        ):
            score -= self.PENALTY_ENTITY_MISMATCH

        # Missing report penalty
        missing_count = issue_counts.get(IssueType.MISSING_REPORT, 0)
        if (
            total_communities > 0
            and missing_count / total_communities > self.REPORT_MISSING_WARNING_RATIO
        ):
            score -= self.PENALTY_REPORT_MISSING

        # Stale report penalty
        if stale_count > 0:
            score -= self.PENALTY_REPORT_STALE

        # Hierarchy break penalty
        hierarchy_count = issue_counts.get(IssueType.HIERARCHY_BREAK, 0)
        if hierarchy_count > 0:
            score -= self.PENALTY_HIERARCHY_BREAK

        # Modularity penalties
        modularity_issues = issue_counts.get(IssueType.LOW_MODULARITY, 0)
        if modularity_issues > 0:
            for issue in issues:
                if issue.issue_type == IssueType.LOW_MODULARITY:
                    if issue.severity == "high":
                        score -= self.PENALTY_CRITICAL_MODULARITY
                    else:
                        score -= self.PENALTY_LOW_MODULARITY
                break

        return max(0.0, min(100.0, score))

    def _determine_status(self, score: float) -> CommunityHealthStatus:
        """Determine health status from score.

        Args:
            score: Health score (0-100).

        Returns:
            CommunityHealthStatus enum value.
        """
        if score >= 80:
            return CommunityHealthStatus.HEALTHY
        if score >= 60:
            return CommunityHealthStatus.MODERATE
        if score >= 40:
            return CommunityHealthStatus.DEGRADED
        return CommunityHealthStatus.CRITICAL
