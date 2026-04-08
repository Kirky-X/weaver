# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CommunityHealthChecker and CommunityRepairService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.graph.community_health_checker import CommunityHealthChecker
from modules.knowledge.graph.community_health_models import (
    CommunityHealthReport,
    CommunityHealthStatus,
    HealthIssue,
    IssueType,
    RepairResult,
    RepairSummary,
)
from modules.knowledge.graph.community_health_repo import CommunityHealthRepo
from modules.knowledge.graph.community_repair_service import CommunityRepairService


class TestCommunityHealthRepo:
    """Test CommunityHealthRepo diagnostic queries."""

    @pytest.fixture
    def repo(self):
        """Create CommunityHealthRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityHealthRepo(pool)

    @pytest.mark.asyncio
    async def test_find_empty_communities_returns_empty_list(self, repo):
        """Test that empty list is returned when no empty communities exist."""
        repo._pool.execute_query = AsyncMock(return_value=[])
        result = await repo.find_empty_communities()
        assert result == []

    @pytest.mark.asyncio
    async def test_find_empty_communities_returns_communities(self, repo):
        """Test that empty communities are returned correctly."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {"community_id": "id1", "title": "Empty Community", "level": 0},
                {"community_id": "id2", "title": "Another Empty", "level": 1},
            ]
        )
        result = await repo.find_empty_communities()
        assert len(result) == 2
        assert result[0]["community_id"] == "id1"

    @pytest.mark.asyncio
    async def test_find_entity_count_mismatches(self, repo):
        """Test finding entity count mismatches."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {"community_id": "id1", "stored_count": 5, "actual_count": 10},
            ]
        )
        result = await repo.find_entity_count_mismatches()
        assert len(result) == 1
        assert result[0]["stored_count"] == 5
        assert result[0]["actual_count"] == 10

    @pytest.mark.asyncio
    async def test_find_missing_reports(self, repo):
        """Test finding communities without reports."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {"community_id": "id1", "title": "No Report Community", "level": 0},
            ]
        )
        result = await repo.find_missing_reports()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_find_stale_reports(self, repo):
        """Test finding stale reports."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "community_id": "id1",
                    "report_id": "r1",
                    "stale": True,
                    "updated_at": datetime.now(UTC),
                },
            ]
        )
        result = await repo.find_stale_reports()
        assert len(result) == 1
        assert result[0]["stale"] is True

    @pytest.mark.asyncio
    async def test_find_hierarchy_breaks(self, repo):
        """Test finding hierarchy breaks."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {"community_id": "id1", "parent_id": "non_existent", "level": 1},
            ]
        )
        result = await repo.find_hierarchy_breaks()
        assert len(result) == 1
        assert result[0]["parent_id"] == "non_existent"

    @pytest.mark.asyncio
    async def test_get_overall_metrics(self, repo):
        """Test getting overall metrics."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "total_communities": 10,
                    "avg_entity_count": 5.5,
                    "max_level": 2,
                    "communities_with_reports": 8,
                    "stale_report_count": 2,
                    "empty_community_count": 1,
                }
            ]
        )
        result = await repo.get_overall_metrics()
        assert result["total_communities"] == 10
        assert result["empty_community_count"] == 1


class TestCommunityHealthChecker:
    """Test CommunityHealthChecker diagnostics."""

    @pytest.fixture
    def checker(self):
        """Create CommunityHealthChecker with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityHealthChecker(pool)

    @pytest.mark.asyncio
    async def test_diagnose_all_returns_healthy_when_no_issues(self, checker):
        """Test that diagnosis returns HEALTHY when no issues found."""
        # Mock all repo methods to return empty results
        checker._repo.find_empty_communities = AsyncMock(return_value=[])
        checker._repo.find_entity_count_mismatches = AsyncMock(return_value=[])
        checker._repo.find_missing_reports = AsyncMock(return_value=[])
        checker._repo.find_stale_reports = AsyncMock(return_value=[])
        checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 10,
                "avg_entity_count": 5.5,
                "max_level": 2,
                "communities_with_reports": 10,
                "stale_report_count": 0,
                "empty_community_count": 0,
            }
        )

        report = await checker.diagnose_all()

        assert report.status == CommunityHealthStatus.HEALTHY
        assert report.score >= 80
        assert len(report.issues) == 0

    @pytest.mark.asyncio
    async def test_diagnose_detects_empty_communities(self, checker):
        """Test that diagnosis detects empty communities."""
        checker._repo.find_empty_communities = AsyncMock(
            return_value=[
                {"community_id": "id1", "title": "Empty", "level": 0},
            ]
        )
        checker._repo.find_entity_count_mismatches = AsyncMock(return_value=[])
        checker._repo.find_missing_reports = AsyncMock(return_value=[])
        checker._repo.find_stale_reports = AsyncMock(return_value=[])
        checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 10,
                "avg_entity_count": 5.0,
                "max_level": 1,
                "communities_with_reports": 10,
                "stale_report_count": 0,
                "empty_community_count": 1,
            }
        )

        report = await checker.diagnose_all()

        assert any(i.issue_type == IssueType.EMPTY_COMMUNITY for i in report.issues)

    @pytest.mark.asyncio
    async def test_diagnose_detects_entity_count_mismatch(self, checker):
        """Test that diagnosis detects entity count mismatches."""
        checker._repo.find_empty_communities = AsyncMock(return_value=[])
        checker._repo.find_entity_count_mismatches = AsyncMock(
            return_value=[
                {"community_id": "id1", "stored_count": 5, "actual_count": 10},
            ]
        )
        checker._repo.find_missing_reports = AsyncMock(return_value=[])
        checker._repo.find_stale_reports = AsyncMock(return_value=[])
        checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 10,
                "avg_entity_count": 5.0,
                "max_level": 1,
                "communities_with_reports": 10,
                "stale_report_count": 0,
                "empty_community_count": 0,
            }
        )

        report = await checker.diagnose_all()

        assert any(i.issue_type == IssueType.ENTITY_COUNT_MISMATCH for i in report.issues)

    @pytest.mark.asyncio
    async def test_diagnose_detects_missing_reports(self, checker):
        """Test that diagnosis detects missing reports."""
        checker._repo.find_empty_communities = AsyncMock(return_value=[])
        checker._repo.find_entity_count_mismatches = AsyncMock(return_value=[])
        checker._repo.find_missing_reports = AsyncMock(
            return_value=[
                {"community_id": "id1", "title": "No Report", "level": 0},
            ]
        )
        checker._repo.find_stale_reports = AsyncMock(return_value=[])
        checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 10,
                "avg_entity_count": 5.0,
                "max_level": 1,
                "communities_with_reports": 9,
                "stale_report_count": 0,
                "empty_community_count": 0,
            }
        )

        report = await checker.diagnose_all()

        assert any(i.issue_type == IssueType.MISSING_REPORT for i in report.issues)

    @pytest.mark.asyncio
    async def test_diagnose_detects_hierarchy_breaks(self, checker):
        """Test that diagnosis detects hierarchy breaks."""
        checker._repo.find_empty_communities = AsyncMock(return_value=[])
        checker._repo.find_entity_count_mismatches = AsyncMock(return_value=[])
        checker._repo.find_missing_reports = AsyncMock(return_value=[])
        checker._repo.find_stale_reports = AsyncMock(return_value=[])
        checker._repo.find_hierarchy_breaks = AsyncMock(
            return_value=[
                {"community_id": "id1", "parent_id": "missing", "level": 1},
            ]
        )
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 10,
                "avg_entity_count": 5.0,
                "max_level": 1,
                "communities_with_reports": 10,
                "stale_report_count": 0,
                "empty_community_count": 0,
            }
        )

        report = await checker.diagnose_all()

        assert any(i.issue_type == IssueType.HIERARCHY_BREAK for i in report.issues)

    @pytest.mark.asyncio
    async def test_diagnose_returns_critical_for_no_communities(self, checker):
        """Test that diagnosis returns CRITICAL when no communities exist."""
        checker._repo.find_empty_communities = AsyncMock(return_value=[])
        checker._repo.find_entity_count_mismatches = AsyncMock(return_value=[])
        checker._repo.find_missing_reports = AsyncMock(return_value=[])
        checker._repo.find_stale_reports = AsyncMock(return_value=[])
        checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
        checker._repo.get_overall_metrics = AsyncMock(
            return_value={
                "total_communities": 0,
                "avg_entity_count": 0.0,
                "max_level": 0,
                "communities_with_reports": 0,
                "stale_report_count": 0,
                "empty_community_count": 0,
            }
        )

        report = await checker.diagnose_all()

        assert report.status == CommunityHealthStatus.CRITICAL
        assert report.score == 0.0


class TestCommunityRepairService:
    """Test CommunityRepairService repair operations."""

    @pytest.fixture
    def repair_service(self):
        """Create CommunityRepairService with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityRepairService(pool)

    @pytest.mark.asyncio
    async def test_repair_empty_communities_returns_zero_when_none(self, repair_service):
        """Test that repair returns 0 when no empty communities."""
        repair_service._pool.execute_query = AsyncMock(return_value=[{"count": 0}])
        result = await repair_service.repair_empty_communities()

        assert result.success is True
        assert result.affected_count == 0

    @pytest.mark.asyncio
    async def test_repair_empty_communities_dry_run(self, repair_service):
        """Test dry run doesn't delete."""
        repair_service._pool.execute_query = AsyncMock(return_value=[{"count": 5}])
        result = await repair_service.repair_empty_communities(dry_run=True)

        assert result.success is True
        assert result.error == "dry_run"

    @pytest.mark.asyncio
    async def test_repair_entity_count_mismatches(self, repair_service):
        """Test entity count repair."""
        repair_service._pool.execute_query = AsyncMock(return_value=[{"count": 3}])
        result = await repair_service.repair_entity_count_mismatches()

        assert result.success is True
        assert result.repair_type == "update_entity_counts"

    @pytest.mark.asyncio
    async def test_repair_hierarchy_breaks(self, repair_service):
        """Test hierarchy break repair."""
        repair_service._pool.execute_query = AsyncMock(return_value=[{"count": 2}])
        result = await repair_service.repair_hierarchy_breaks()

        assert result.success is True
        assert result.repair_type == "clear_broken_parent_ids"

    @pytest.mark.asyncio
    async def test_auto_repair_filters_non_repairable(self, repair_service):
        """Test that auto_repair only repairs auto-repairable issues."""
        repair_service._pool.execute_query = AsyncMock(return_value=[{"count": 0}])

        issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                description="Empty",
                suggestion="Delete",
                community_id="id1",
                auto_repairable=True,
            ),
            HealthIssue(
                issue_type=IssueType.LOW_MODULARITY,
                severity="high",
                description="Low modularity",
                suggestion="Rebuild",
                community_id=None,
                auto_repairable=False,
            ),
        ]

        summary = await repair_service.auto_repair(issues)

        # Only empty communities should be repaired
        assert len(summary.results) == 1
        assert summary.results[0].repair_type == "delete_empty_communities"


class TestHealthModels:
    """Test health data models."""

    def test_community_health_status_values(self):
        """Test CommunityHealthStatus enum values."""
        assert CommunityHealthStatus.HEALTHY.value == "healthy"
        assert CommunityHealthStatus.MODERATE.value == "moderate"
        assert CommunityHealthStatus.DEGRADED.value == "degraded"
        assert CommunityHealthStatus.CRITICAL.value == "critical"

    def test_issue_type_values(self):
        """Test IssueType enum values."""
        assert IssueType.EMPTY_COMMUNITY.value == "empty_community"
        assert IssueType.ENTITY_COUNT_MISMATCH.value == "entity_count_mismatch"
        assert IssueType.MISSING_REPORT.value == "missing_report"
        assert IssueType.STALE_REPORT.value == "stale_report"
        assert IssueType.HIERARCHY_BREAK.value == "hierarchy_break"
        assert IssueType.LOW_MODULARITY.value == "low_modularity"

    def test_health_issue_creation(self):
        """Test HealthIssue dataclass."""
        issue = HealthIssue(
            issue_type=IssueType.EMPTY_COMMUNITY,
            severity="high",
            description="Test issue",
            suggestion="Fix it",
            community_id="test-id",
            auto_repairable=True,
        )
        assert issue.issue_type == IssueType.EMPTY_COMMUNITY
        assert issue.severity == "high"
        assert issue.auto_repairable is True

    def test_community_health_report_to_dict(self):
        """Test CommunityHealthReport serialization."""
        report = CommunityHealthReport(
            status=CommunityHealthStatus.HEALTHY,
            score=95.0,
            issues=[],
            metrics={"total": 10},
        )
        data = report.to_dict()

        assert data["status"] == "healthy"
        assert data["score"] == 95.0
        assert data["issues"] == []
        assert data["metrics"]["total"] == 10

    def test_repair_summary_to_dict(self):
        """Test RepairSummary serialization."""
        summary = RepairSummary(
            results=[
                RepairResult(
                    repair_type="delete_empty",
                    affected_count=5,
                    success=True,
                )
            ],
            total_repaired=5,
            duration_ms=100.0,
        )
        data = summary.to_dict()

        assert data["total_repaired"] == 5
        assert data["duration_ms"] == 100.0
        assert len(data["results"]) == 1
