# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for modules.knowledge.graph.community.health.checker module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.graph.community.health.checker import CommunityHealthChecker
from modules.knowledge.graph.community.health.models import (
    HealthIssue,
    HealthReport,
    IssueType,
)


class TestCommunityHealthCheckerInit:
    """Test CommunityHealthChecker initialization."""

    def test_init_with_pool(self):
        """Test initialization with graph pool."""
        mock_pool = MagicMock()
        checker = CommunityHealthChecker(mock_pool)

        assert checker._pool is mock_pool


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
        checker._pool.execute_query = AsyncMock(return_value=[])

        issues = await checker.check_empty_communities()

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_empty_communities(self, checker):
        """Test finds empty communities."""
        checker._pool.execute_query = AsyncMock(
            return_value=[
                {"community_id": 1, "level": 0},
                {"community_id": 2, "level": 1},
            ]
        )

        issues = await checker.check_empty_communities()

        assert len(issues) == 2
        assert all(isinstance(issue, HealthIssue) for issue in issues)
        assert all(issue.issue_type == IssueType.EMPTY_COMMUNITY for issue in issues)


class TestCheckEntityCountMismatch:
    """Test check_entity_count_mismatch method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_no_mismatches(self, checker):
        """Test when no entity count mismatches."""
        checker._pool.execute_query = AsyncMock(return_value=[])

        issues = await checker.check_entity_count_mismatch()

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_mismatches(self, checker):
        """Test finds entity count mismatches."""
        checker._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "community_id": 1,
                    "stored_count": 10,
                    "actual_count": 15,
                    "difference": 5,
                },
            ]
        )

        issues = await checker.check_entity_count_mismatch()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.ENTITY_COUNT_MISMATCH
        assert issues[0].severity in ["medium", "high"]


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
        checker._pool.execute_query = AsyncMock(return_value=[])

        issues = await checker.check_stale_reports(max_age_days=7)

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_stale_reports(self, checker):
        """Test finds stale reports."""
        checker._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "community_id": 1,
                    "last_updated": "2026-01-01",
                    "age_days": 100,
                },
            ]
        )

        issues = await checker.check_stale_reports(max_age_days=7)

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.STALE_REPORT


class TestCheckBrokenHierarchy:
    """Test check_broken_hierarchy method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_no_broken_references(self, checker):
        """Test when no broken hierarchy references."""
        checker._pool.execute_query = AsyncMock(return_value=[])

        issues = await checker.check_broken_hierarchy()

        assert issues == []

    @pytest.mark.asyncio
    async def test_finds_broken_references(self, checker):
        """Test finds broken parent references."""
        checker._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "community_id": 5,
                    "parent_id": 999,
                },
            ]
        )

        issues = await checker.check_broken_hierarchy()

        assert len(issues) == 1
        assert issues[0].issue_type == IssueType.BROKEN_HIERARCHY


class TestRunFullHealthCheck:
    """Test run_full_health_check method."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mock pool."""
        mock_pool = AsyncMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        return CommunityHealthChecker(mock_pool)

    @pytest.mark.asyncio
    async def test_full_check_no_issues(self, checker):
        """Test full health check with no issues."""
        report = await checker.run_full_health_check()

        assert isinstance(report, HealthReport)
        assert len(report.issues) == 0
        assert report.healthy is True

    @pytest.mark.asyncio
    async def test_full_check_with_issues(self, checker):
        """Test full health check detects issues."""
        # Return empty communities
        call_count = 0

        async def mock_execute_query(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"community_id": 1, "level": 0}]  # Empty communities
            return []  # No other issues

        checker._pool.execute_query = mock_execute_query

        report = await checker.run_full_health_check()

        assert isinstance(report, HealthReport)
        assert len(report.issues) > 0
        assert report.healthy is False

    @pytest.mark.asyncio
    async def test_full_check_counts_by_type(self, checker):
        """Test full check provides issue counts by type."""
        checker._pool.execute_query = AsyncMock(return_value=[])

        report = await checker.run_full_health_check()

        assert hasattr(report, "issue_counts")
        assert isinstance(report.issue_counts, dict)


class TestHealthReport:
    """Test HealthReport model."""

    def test_create_healthy_report(self):
        """Test creating healthy report."""
        report = HealthReport(
            healthy=True,
            issues=[],
            checked_at="2026-04-16T12:00:00Z",
        )

        assert report.healthy is True
        assert len(report.issues) == 0

    def test_create_unhealthy_report(self):
        """Test creating report with issues."""
        issue = HealthIssue(
            issue_type=IssueType.EMPTY_COMMUNITY,
            community_id=1,
            severity="high",
        )

        report = HealthReport(
            healthy=False,
            issues=[issue],
            issue_counts={IssueType.EMPTY_COMMUNITY: 1},
        )

        assert report.healthy is False
        assert len(report.issues) == 1
        assert report.issue_counts[IssueType.EMPTY_COMMUNITY] == 1


class TestCommunityHealthCheckerIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_complete_health_workflow(self):
        """Test complete health checking workflow."""
        mock_pool = AsyncMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        checker = CommunityHealthChecker(mock_pool)

        # Run full health check
        report = await checker.run_full_health_check()

        assert isinstance(report, HealthReport)
        assert report is not None

    @pytest.mark.asyncio
    async def test_health_check_with_multiple_issues(self):
        """Test health check detects multiple issue types."""
        mock_pool = AsyncMock()
        # Simulate various issues
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"community_id": 1, "level": 0}],  # Empty communities
                [
                    {"community_id": 2, "stored_count": 10, "actual_count": 15, "difference": 5}
                ],  # Mismatch
                [],  # No stale reports
                [],  # No broken hierarchy
            ]
        )

        checker = CommunityHealthChecker(mock_pool)

        report = await checker.run_full_health_check()

        assert report.healthy is False
        assert len(report.issues) >= 2
