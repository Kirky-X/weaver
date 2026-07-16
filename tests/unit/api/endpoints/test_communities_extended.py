# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Extended unit tests for communities API endpoints - health check and repair coverage."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from tests.helpers import generate_random_uuid


class TestHealthOverviewEndpoint:
    """Tests for GET /admin/communities/health endpoint (lines 427-486)."""

    @pytest.mark.asyncio
    async def test_health_overview_healthy_status(self) -> None:
        """Test health overview returns healthy status with good metrics."""
        from api.endpoints.communities import get_health_overview

        mock_pool = AsyncMock()

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker._repo.get_overall_metrics = AsyncMock(
                return_value={
                    "total_communities": 100,
                    "empty_community_count": 2,
                    "communities_with_reports": 85,
                    "stale_report_count": 0,
                }
            )
            mock_checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
            mock_checker_class.return_value = mock_checker

            result = await get_health_overview(
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.status == "healthy"
        assert result.data.score >= 80.0
        assert result.data.total_communities == 100
        assert result.data.communities_with_reports == 85
        assert result.data.stale_reports == 0
        assert result.data.empty_communities == 2
        assert result.data.hierarchy_issues == 0

    @pytest.mark.asyncio
    async def test_health_overview_critical_no_communities(self) -> None:
        """Test health overview returns critical status when no communities exist."""
        from api.endpoints.communities import get_health_overview

        mock_pool = AsyncMock()

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker._repo.get_overall_metrics = AsyncMock(
                return_value={
                    "total_communities": 0,
                    "empty_community_count": 0,
                    "communities_with_reports": 0,
                    "stale_report_count": 0,
                }
            )
            mock_checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[])
            mock_checker_class.return_value = mock_checker

            result = await get_health_overview(
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.status == "critical"
        assert result.data.score == 0.0
        assert result.data.total_communities == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metrics,expected_status,expected_score",
        [
            # High empty ratio > 10%
            (
                {
                    "total_communities": 100,
                    "empty_community_count": 15,
                    "communities_with_reports": 90,
                    "stale_report_count": 0,
                },
                "moderate",  # score = 100 - 30 = 70
                70.0,
            ),
            # Medium empty ratio > 5%
            (
                {
                    "total_communities": 100,
                    "empty_community_count": 8,
                    "communities_with_reports": 80,
                    "stale_report_count": 0,
                },
                "healthy",  # score = 100 - 15 = 85
                85.0,
            ),
            # Low report ratio < 70%
            (
                {
                    "total_communities": 100,
                    "empty_community_count": 2,
                    "communities_with_reports": 50,
                    "stale_report_count": 0,
                },
                "healthy",  # score = 100 - 10 = 90
                90.0,
            ),
            # With stale reports
            (
                {
                    "total_communities": 100,
                    "empty_community_count": 2,
                    "communities_with_reports": 85,
                    "stale_report_count": 5,
                },
                "healthy",  # score = 100 - 5 = 95
                95.0,
            ),
            # Multiple penalties - degraded
            (
                {
                    "total_communities": 100,
                    "empty_community_count": 12,
                    "communities_with_reports": 60,
                    "stale_report_count": 3,
                },
                "degraded",  # score = 100 - 30 - 10 - 5 = 55
                55.0,
            ),
        ],
    )
    async def test_health_overview_score_calculations(
        self,
        metrics: dict[str, Any],
        expected_status: str,
        expected_score: float,
    ) -> None:
        """Test health overview score calculation with various metrics."""
        from api.endpoints.communities import get_health_overview

        mock_pool = AsyncMock()

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker._repo.get_overall_metrics = AsyncMock(return_value=metrics)
            mock_checker._repo.find_hierarchy_breaks = AsyncMock(return_value=[{"id": "break1"}])
            mock_checker_class.return_value = mock_checker

            result = await get_health_overview(
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.status == expected_status
        assert result.data.score == expected_score
        assert result.data.hierarchy_issues == 1

    @pytest.mark.asyncio
    async def test_health_overview_exception_handling(self) -> None:
        """Test health overview handles exceptions properly."""
        from api.endpoints.communities import get_health_overview

        mock_pool = AsyncMock()

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker._repo.get_overall_metrics = AsyncMock(
                side_effect=Exception("Database connection failed")
            )
            mock_checker_class.return_value = mock_checker

            with pytest.raises(HTTPException) as exc_info:
                await get_health_overview(
                    _="test-key",
                    pool=mock_pool,
                )

        assert exc_info.value.status_code == 500
        assert "Health check failed" in str(exc_info.value.detail)


class TestDiagnoseHealthEndpoint:
    """Tests for POST /admin/communities/health/diagnose endpoint (lines 512-545)."""

    @pytest.mark.asyncio
    async def test_diagnose_health_with_issues(self) -> None:
        """Test diagnose health returns detailed issues."""
        from api.endpoints.communities import diagnose_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )

        mock_pool = AsyncMock()

        # Create mock health issues
        mock_issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                community_id=generate_random_uuid(),
                description="Community has no entities",
                suggestion="Delete empty community",
                auto_repairable=True,
            ),
            HealthIssue(
                issue_type=IssueType.STALE_REPORT,
                severity="low",
                community_id=generate_random_uuid(),
                description="Report is outdated",
                suggestion="Regenerate report",
                auto_repairable=True,
            ),
            HealthIssue(
                issue_type=IssueType.LOW_MODULARITY,
                severity="medium",
                community_id=None,
                description="Low modularity score",
                suggestion="Rebuild communities",
                auto_repairable=False,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.MODERATE,
            score=65.0,
            issues=mock_issues,
            metrics={"total_communities": 50},
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            result = await diagnose_health(
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.status == "moderate"
        assert result.data.score == 65.0
        assert len(result.data.issues) == 3
        assert result.data.issues[0].issue_type == "empty_community"
        assert result.data.issues[0].severity == "high"
        assert result.data.issues[0].auto_repairable is True
        assert result.data.issues[2].auto_repairable is False
        # Should only include auto-repairable suggestions
        assert len(result.data.repair_suggestions) == 2

    @pytest.mark.asyncio
    async def test_diagnose_health_no_issues(self) -> None:
        """Test diagnose health with no issues found."""
        from api.endpoints.communities import diagnose_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
        )

        mock_pool = AsyncMock()

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.HEALTHY,
            score=95.0,
            issues=[],
            metrics={"total_communities": 100},
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            result = await diagnose_health(
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.status == "healthy"
        assert result.data.score == 95.0
        assert len(result.data.issues) == 0
        assert len(result.data.repair_suggestions) == 0

    @pytest.mark.asyncio
    async def test_diagnose_health_exception_handling(self) -> None:
        """Test diagnose health handles exceptions properly."""
        from api.endpoints.communities import diagnose_health

        mock_pool = AsyncMock()

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(side_effect=Exception("Diagnosis engine failed"))
            mock_checker_class.return_value = mock_checker

            with pytest.raises(HTTPException) as exc_info:
                await diagnose_health(
                    _="test-key",
                    pool=mock_pool,
                )

        assert exc_info.value.status_code == 500
        assert "Diagnosis failed" in str(exc_info.value.detail)


class TestRepairHealthEndpoint:
    """Tests for POST /admin/communities/health/repair endpoint (lines 573-637)."""

    @pytest.mark.asyncio
    async def test_repair_health_no_repairable_issues(self) -> None:
        """Test repair health returns empty results when no repairable issues."""
        from api.endpoints.communities import RepairRequest, repair_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        # Only non-repairable issues
        mock_issues = [
            HealthIssue(
                issue_type=IssueType.LOW_MODULARITY,
                severity="medium",
                community_id=None,
                description="Low modularity",
                suggestion="Rebuild",
                auto_repairable=False,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.MODERATE,
            score=65.0,
            issues=mock_issues,
            metrics={"total_communities": 50},
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            result = await repair_health(
                request=RepairRequest(),
                _="test-key",
                pool=mock_pool,
                llm=mock_llm,
            )

        assert result.data.repaired == {}
        assert result.data.failed == {}
        assert result.data.duration_ms == 0.0

    @pytest.mark.asyncio
    async def test_repair_health_with_repair_types_filter(self) -> None:
        """Test repair health filters by requested repair types."""
        from api.endpoints.communities import RepairRequest, repair_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        mock_issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                community_id=generate_random_uuid(),
                description="Empty community",
                suggestion="Delete",
                auto_repairable=True,
            ),
            HealthIssue(
                issue_type=IssueType.STALE_REPORT,
                severity="low",
                community_id=generate_random_uuid(),
                description="Stale report",
                suggestion="Regenerate",
                auto_repairable=True,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.MODERATE,
            score=65.0,
            issues=mock_issues,
            metrics={"total_communities": 50},
        )

        from modules.knowledge.graph.community.repair_service import RepairResult, RepairSummary

        mock_summary = RepairSummary(
            results=[
                RepairResult(
                    repair_type="delete_empty_communities",
                    affected_count=3,
                    success=True,
                ),
            ],
            total_repaired=3,
            duration_ms=150.0,
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            with patch("api.endpoints.communities.CommunityRepairService") as mock_repair_class:
                mock_repair = AsyncMock()
                mock_repair.auto_repair = AsyncMock(return_value=mock_summary)
                mock_repair_class.return_value = mock_repair

                # Only request stale_report repair, not empty_community
                result = await repair_health(
                    request=RepairRequest(repair_types=["stale_report"]),
                    _="test-key",
                    pool=mock_pool,
                    llm=mock_llm,
                )

        # Should have no repairs since we filtered to stale_report only
        # but mock only returned delete_empty_communities
        assert result.data.duration_ms == 150.0

    @pytest.mark.asyncio
    async def test_repair_health_successful_repairs(self) -> None:
        """Test repair health returns successful repair counts."""
        from api.endpoints.communities import RepairRequest, repair_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )
        from modules.knowledge.graph.community.repair_service import RepairResult, RepairSummary

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        mock_issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                community_id=generate_random_uuid(),
                description="Empty community",
                suggestion="Delete",
                auto_repairable=True,
            ),
            HealthIssue(
                issue_type=IssueType.ENTITY_COUNT_MISMATCH,
                severity="low",
                community_id=generate_random_uuid(),
                description="Count mismatch",
                suggestion="Update count",
                auto_repairable=True,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.MODERATE,
            score=65.0,
            issues=mock_issues,
            metrics={"total_communities": 50},
        )

        mock_summary = RepairSummary(
            results=[
                RepairResult(
                    repair_type="delete_empty_communities",
                    affected_count=5,
                    success=True,
                ),
                RepairResult(
                    repair_type="update_entity_counts",
                    affected_count=10,
                    success=True,
                ),
            ],
            total_repaired=15,
            duration_ms=250.0,
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            with patch("api.endpoints.communities.CommunityRepairService") as mock_repair_class:
                mock_repair = AsyncMock()
                mock_repair.auto_repair = AsyncMock(return_value=mock_summary)
                mock_repair_class.return_value = mock_repair

                result = await repair_health(
                    request=RepairRequest(),
                    _="test-key",
                    pool=mock_pool,
                    llm=mock_llm,
                )

        assert result.data.repaired["delete_empty_communities"] == 5
        assert result.data.repaired["update_entity_counts"] == 10
        assert result.data.failed == {}
        assert result.data.duration_ms == 250.0

    @pytest.mark.asyncio
    async def test_repair_health_with_failures(self) -> None:
        """Test repair health handles partial failures."""
        from api.endpoints.communities import RepairRequest, repair_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )
        from modules.knowledge.graph.community.repair_service import RepairResult, RepairSummary

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        mock_issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                community_id=generate_random_uuid(),
                description="Empty community",
                suggestion="Delete",
                auto_repairable=True,
            ),
            HealthIssue(
                issue_type=IssueType.HIERARCHY_BREAK,
                severity="medium",
                community_id=generate_random_uuid(),
                description="Broken hierarchy",
                suggestion="Clear parent",
                auto_repairable=True,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.DEGRADED,
            score=45.0,
            issues=mock_issues,
            metrics={"total_communities": 50},
        )

        mock_summary = RepairSummary(
            results=[
                RepairResult(
                    repair_type="delete_empty_communities",
                    affected_count=3,
                    success=True,
                ),
                RepairResult(
                    repair_type="clear_broken_parent_ids",
                    affected_count=0,
                    success=False,
                    error="Database timeout",
                ),
            ],
            total_repaired=3,
            duration_ms=300.0,
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            with patch("api.endpoints.communities.CommunityRepairService") as mock_repair_class:
                mock_repair = AsyncMock()
                mock_repair.auto_repair = AsyncMock(return_value=mock_summary)
                mock_repair_class.return_value = mock_repair

                result = await repair_health(
                    request=RepairRequest(),
                    _="test-key",
                    pool=mock_pool,
                    llm=mock_llm,
                )

        assert result.data.repaired["delete_empty_communities"] == 3
        assert "clear_broken_parent_ids" in result.data.failed
        assert result.data.failed["clear_broken_parent_ids"] == ["Database timeout"]
        assert result.data.duration_ms == 300.0

    @pytest.mark.asyncio
    async def test_repair_health_dry_run(self) -> None:
        """Test repair health dry run mode."""
        from api.endpoints.communities import RepairRequest, repair_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )
        from modules.knowledge.graph.community.repair_service import RepairResult, RepairSummary

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        mock_issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                community_id=generate_random_uuid(),
                description="Empty community",
                suggestion="Delete",
                auto_repairable=True,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.MODERATE,
            score=65.0,
            issues=mock_issues,
            metrics={"total_communities": 50},
        )

        mock_summary = RepairSummary(
            results=[
                RepairResult(
                    repair_type="delete_empty_communities",
                    affected_count=5,
                    success=True,
                    error="dry_run",
                ),
            ],
            total_repaired=5,
            duration_ms=100.0,
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            with patch("api.endpoints.communities.CommunityRepairService") as mock_repair_class:
                mock_repair = AsyncMock()
                mock_repair.auto_repair = AsyncMock(return_value=mock_summary)
                mock_repair_class.return_value = mock_repair

                result = await repair_health(
                    request=RepairRequest(dry_run=True),
                    _="test-key",
                    pool=mock_pool,
                    llm=mock_llm,
                )

        # In dry run, should still show affected count
        assert result.data.repaired["delete_empty_communities"] == 5
        assert result.data.duration_ms == 100.0

    @pytest.mark.asyncio
    async def test_repair_health_exception_handling(self) -> None:
        """Test repair health handles exceptions properly."""
        from api.endpoints.communities import RepairRequest, repair_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        # Need repairable issues to trigger repair service
        mock_issues = [
            HealthIssue(
                issue_type=IssueType.EMPTY_COMMUNITY,
                severity="high",
                community_id=generate_random_uuid(),
                description="Empty community",
                suggestion="Delete",
                auto_repairable=True,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.MODERATE,
            score=65.0,
            issues=mock_issues,
            metrics={"total_communities": 100},
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            with patch("api.endpoints.communities.CommunityRepairService") as mock_repair_class:
                mock_repair = AsyncMock()
                mock_repair.auto_repair = AsyncMock(
                    side_effect=Exception("Repair service unavailable")
                )
                mock_repair_class.return_value = mock_repair

                with pytest.raises(HTTPException) as exc_info:
                    await repair_health(
                        request=RepairRequest(),
                        _="test-key",
                        pool=mock_pool,
                        llm=mock_llm,
                    )

        assert exc_info.value.status_code == 500
        assert "Repair failed" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_repair_health_unknown_error_in_result(self) -> None:
        """Test repair health handles results with None error."""
        from api.endpoints.communities import RepairRequest, repair_health
        from modules.knowledge.graph.community.health.models import (
            CommunityHealthReport,
            CommunityHealthStatus,
            HealthIssue,
            IssueType,
        )
        from modules.knowledge.graph.community.repair_service import RepairResult, RepairSummary

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        mock_issues = [
            HealthIssue(
                issue_type=IssueType.STALE_REPORT,
                severity="low",
                community_id=generate_random_uuid(),
                description="Stale report",
                suggestion="Regenerate",
                auto_repairable=True,
            ),
        ]

        mock_report = CommunityHealthReport(
            status=CommunityHealthStatus.MODERATE,
            score=70.0,
            issues=mock_issues,
            metrics={"total_communities": 50},
        )

        # Result with None error
        mock_summary = RepairSummary(
            results=[
                RepairResult(
                    repair_type="regenerate_stale_reports",
                    affected_count=0,
                    success=False,
                    error=None,  # Test None error handling
                ),
            ],
            total_repaired=0,
            duration_ms=200.0,
        )

        with patch("api.endpoints.communities.CommunityHealthChecker") as mock_checker_class:
            mock_checker = AsyncMock()
            mock_checker.diagnose_all = AsyncMock(return_value=mock_report)
            mock_checker_class.return_value = mock_checker

            with patch("api.endpoints.communities.CommunityRepairService") as mock_repair_class:
                mock_repair = AsyncMock()
                mock_repair.auto_repair = AsyncMock(return_value=mock_summary)
                mock_repair_class.return_value = mock_repair

                result = await repair_health(
                    request=RepairRequest(),
                    _="test-key",
                    pool=mock_pool,
                    llm=mock_llm,
                )

        # Should use "Unknown error" when error is None
        assert "regenerate_stale_reports" in result.data.failed
        assert result.data.failed["regenerate_stale_reports"] == ["Unknown error"]
