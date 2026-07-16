# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.knowledge.graph.community.health.checker module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.graph.community.health.checker import CommunityHealthChecker
from modules.knowledge.graph.community.health.models import (
    CommunityHealthReport,
    CommunityHealthStatus,
    HealthIssue,
    IssueType,
)


class TestCommunityHealthCheckerInit:
    """Test CommunityHealthChecker initialization."""

    def test_init_with_pool(self):
        """Test initialization with graph pool."""
        mock_pool = MagicMock()
        checker = CommunityHealthChecker(mock_pool)

        assert checker._pool is mock_pool

    def test_init_with_modularity_calculator(self):
        """Test initialization with modularity calculator."""
        mock_pool = MagicMock()
        mock_calculator = MagicMock()
        checker = CommunityHealthChecker(mock_pool, modularity_calculator=mock_calculator)

        assert checker._modularity_calculator is mock_calculator


class TestCheckEmptyCommunities:
    """Test check_empty_communities method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_no_empty_communities(self, checker):
        """Test when no empty communities exist."""
        checker._repo.find_empty_communities = AsyncMock(return_value=[])

        issues = await checker.check_empty_communities()

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_empty_communities(self, checker):
        """Test finds empty communities."""
        checker._repo.find_empty_communities = AsyncMock(
            return_value=[
                {"community_id": "1", "title": "Community 1"},
                {"community_id": "2", "title": "Community 2"},
            ]
        )

        issues = await checker.check_empty_communities()

        assert len(issues) == 2
        assert all(isinstance(issue, HealthIssue) for issue in issues)
        assert all(issue.issue_type == IssueType.EMPTY_COMMUNITY for issue in issues)
        assert all(issue.auto_repairable is True for issue in issues)

    @pytest.mark.asyncio
    async def test_empty_community_high_severity(self, checker):
        """Test empty community has high severity."""
        checker._repo.find_empty_communities = AsyncMock(
            return_value=[{"community_id": "1", "title": "Empty Community"}]
        )

        issues = await checker.check_empty_communities()

        assert len(issues) == 1
        assert issues[0].severity == "high"


class TestCheckEntityCountInconsistency:
    """Test check_entity_count_inconsistency method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_no_mismatches(self, checker):
        """Test when no entity count mismatches."""
        checker._repo.find_entity_count_mismatches = AsyncMock(return_value=[])

        issues = await checker.check_entity_count_inconsistency()

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_mismatches(self, checker):
        """Test finds entity count mismatches."""
        checker._repo.find_entity_count_mismatches = AsyncMock(
            return_value=[
                {
                    "community_id": "1",
                    "stored_count": 10,
                    "actual_count": 15,
                },
            ]
        )

        issues = await checker.check_entity_count_inconsistency()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.ENTITY_COUNT_MISMATCH
        assert issues[0].severity == "low"
        assert issues[0].auto_repairable is True


class TestCheckMissingReports:
    """Test check_missing_reports method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_no_missing_reports(self, checker):
        """Test when no missing reports."""
        checker._repo.find_missing_reports = AsyncMock(return_value=[])

        issues = await checker.check_missing_reports()

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_missing_reports(self, checker):
        """Test finds missing reports."""
        checker._repo.find_missing_reports = AsyncMock(
            return_value=[
                {"community_id": "1", "title": "Community 1"},
            ]
        )

        issues = await checker.check_missing_reports()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.MISSING_REPORT
        assert issues[0].severity == "medium"
        assert issues[0].auto_repairable is True


class TestCheckStaleReports:
    """Test check_stale_reports method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_no_stale_reports(self, checker):
        """Test when no stale reports."""
        checker._repo.find_stale_reports = AsyncMock(return_value=[])

        issues = await checker.check_stale_reports(days_threshold=7)

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_stale_reports(self, checker):
        """Test finds stale reports."""
        checker._repo.find_stale_reports = AsyncMock(
            return_value=[
                {
                    "community_id": "1",
                    "updated_at": "2026-01-01",
                },
            ]
        )

        issues = await checker.check_stale_reports(days_threshold=7)

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.STALE_REPORT
        assert issues[0].severity == "low"


class TestCheckHierarchyIntegrity:
    """Test check_hierarchy_integrity method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_no_broken_references(self, checker):
        """Test when no broken hierarchy references."""
        checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])

        issues = await checker.check_hierarchy_integrity()

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_broken_references(self, checker):
        """Test finds broken parent references."""
        checker._repo.find_hierarchy_breaks = AsyncMock(
            return_value=[
                {
                    "community_id": "5",
                    "parent_id": "999",
                },
            ]
        )

        issues = await checker.check_hierarchy_integrity()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.HIERARCHY_BREAK
        assert issues[0].severity == "medium"


class TestCheckModularityScore:
    """Test check_modularity_score method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool and calculator."""
        mock_pool = AsyncMock()
        mock_calculator = AsyncMock()
        return CommunityHealthChecker(mock_pool, modularity_calculator=mock_calculator)

    @pytest.mark.asyncio
    async def test_no_calculator_skips_check(self):
        """Test skips modularity check when no calculator provided."""
        mock_pool = AsyncMock()
        checker = CommunityHealthChecker(mock_pool, modularity_calculator=None)

        issues = await checker.check_modularity_score()

        assert issues == []

    @pytest.mark.asyncio
    async def test_low_modularity_warning(self, checker):
        """Test low modularity creates medium severity issue."""
        checker._modularity_calculator._calculate_modularity = AsyncMock(return_value=0.05)

        issues = await checker.check_modularity_score()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.LOW_MODULARITY
        assert issues[0].severity == "medium"

    @pytest.mark.asyncio
    async def test_critical_modularity_error(self, checker):
        """Test critical modularity creates high severity issue."""
        checker._modularity_calculator._calculate_modularity = AsyncMock(return_value=-0.1)

        issues = await checker.check_modularity_score()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.LOW_MODULARITY
        assert issues[0].severity == "high"


class TestDiagnoseAll:
    """Test diagnose_all method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        checker = CommunityHealthChecker(mock_pool)
        # Mock all repo methods
        checker._repo.find_empty_communities = AsyncMock(return_value=[])
        checker._repo.find_entity_count_mismatches = AsyncMock(return_value=[])
        checker._repo.find_missing_reports = AsyncMock(return_value=[])
        checker._repo.find_stale_reports = AsyncMock(return_value=[])
        checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 10,
                "empty_community_count": 0,
                "stale_report_count": 0,
            }
        )
        return checker

    @pytest.mark.asyncio
    async def test_diagnose_all_no_issues(self, checker):
        """Test full health check with no issues."""
        report = await checker.diagnose_all()

        assert isinstance(report, CommunityHealthReport)
        assert len(report.issues) == 0
        assert report.status == CommunityHealthStatus.HEALTHY
        assert report.score == 100.0

    @pytest.mark.asyncio
    async def test_diagnose_all_with_issues(self, checker):
        """Test full health check detects issues."""
        checker._repo.find_empty_communities = AsyncMock(
            return_value=[{"community_id": "1", "title": "Empty"}]
        )
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 10,
                "empty_community_count": 1,
                "stale_report_count": 0,
            }
        )

        report = await checker.diagnose_all()

        assert isinstance(report, CommunityHealthReport)
        assert len(report.issues) > 0
        assert report.status != CommunityHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_diagnose_all_returns_metrics(self, checker):
        """Test diagnose_all returns metrics."""
        report = await checker.diagnose_all()

        assert report.metrics is not None
        assert "total_communities" in report.metrics


class TestCalculateHealthScore:
    """Test _calculate_health_score method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    def test_perfect_score_no_issues(self, checker):
        """Test perfect score with no issues."""
        score = checker._calculate_health_score(
            [],
            {"total_communities": 10, "empty_community_count": 0, "stale_report_count": 0},
        )

        assert score == 100.0

    def test_score_penalty_for_empty_communities(self, checker):
        """Test score penalty for empty communities."""
        issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                description="Empty",
                suggestion="Delete",
            )
        ]
        score = checker._calculate_health_score(
            issues,
            {"total_communities": 10, "empty_community_count": 2, "stale_report_count": 0},
        )

        assert score < 100.0

    def test_zero_communities_critical(self, checker):
        """Test zero communities returns zero score."""
        score = checker._calculate_health_score(
            [],
            {"total_communities": 0, "empty_community_count": 0, "stale_report_count": 0},
        )

        assert score == 0.0


class TestDetermineStatus:
    """Test _determine_status method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    def test_healthy_status(self, checker):
        """Test healthy status for high score."""
        status = checker._determine_status(85.0)
        assert status == CommunityHealthStatus.HEALTHY

    def test_moderate_status(self, checker):
        """Test moderate status for medium score."""
        status = checker._determine_status(70.0)
        assert status == CommunityHealthStatus.MODERATE

    def test_degraded_status(self, checker):
        """Test degraded status for low score."""
        status = checker._determine_status(50.0)
        assert status == CommunityHealthStatus.DEGRADED

    def test_critical_status(self, checker):
        """Test critical status for very low score."""
        status = checker._determine_status(30.0)
        assert status == CommunityHealthStatus.CRITICAL


class TestCommunityHealthReport:
    """Test CommunityHealthReport model."""

    def test_create_healthy_report(self):
        """Test creating healthy report."""
        report = CommunityHealthReport(
            status=CommunityHealthStatus.HEALTHY,
            score=100.0,
            issues=[],
        )

        assert report.status == CommunityHealthStatus.HEALTHY
        assert len(report.issues) == 0
        assert report.score == 100.0

    def test_create_unhealthy_report(self):
        """Test creating report with issues."""
        issue = HealthIssue(
            issue_type=IssueType.EMPTY_COMMUNITY,
            severity="high",
            description="Empty community",
            suggestion="Delete it",
            community_id="1",
        )

        report = CommunityHealthReport(
            status=CommunityHealthStatus.DEGRADED,
            score=60.0,
            issues=[issue],
        )

        assert report.status == CommunityHealthStatus.DEGRADED
        assert len(report.issues) == 1

    def test_to_dict(self):
        """Test to_dict serialization."""
        report = CommunityHealthReport(
            status=CommunityHealthStatus.HEALTHY,
            score=95.0,
            issues=[],
            metrics={"total_communities": 10},
        )

        result = report.to_dict()

        assert result["status"] == "healthy"
        assert result["score"] == 95.0
        assert result["metrics"]["total_communities"] == 10
        assert "checked_at" in result


class TestHealthIssue:
    """Test HealthIssue model."""

    def test_create_issue(self):
        """Test creating health issue."""
        issue = HealthIssue(
            issue_type=IssueType.EMPTY_COMMUNITY,
            severity="high",
            description="Empty community found",
            suggestion="Delete the empty community",
            community_id="123",
            auto_repairable=True,
        )

        assert issue.issue_type == IssueType.EMPTY_COMMUNITY
        assert issue.severity == "high"
        assert issue.community_id == "123"
        assert issue.auto_repairable is True
