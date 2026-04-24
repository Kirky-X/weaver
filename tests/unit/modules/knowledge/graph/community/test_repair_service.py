# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for modules.knowledge.graph.community.repair_service module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.graph.community.health.models import (
    HealthIssue,
    IssueType,
    RepairResult,
    RepairSummary,
)
from modules.knowledge.graph.community.repair_service import CommunityRepairService


class TestCommunityRepairServiceInit:
    """Test CommunityRepairService initialization."""

    def test_init_with_pool_only(self):
        """Test initialization with pool only."""
        mock_pool = MagicMock()
        service = CommunityRepairService(mock_pool)

        assert service._pool is mock_pool
        assert service._report_generator is None

    def test_init_with_report_generator(self):
        """Test initialization with report generator."""
        mock_pool = MagicMock()
        mock_gen = MagicMock()
        service = CommunityRepairService(mock_pool, mock_gen)

        assert service._pool is mock_pool
        assert service._report_generator is mock_gen


class TestRepairEmptyCommunities:
    """Test repair_empty_communities method."""

    @pytest.fixture
    def service(self):
        """Create CommunityRepairService with mock pool."""
        mock_pool = AsyncMock()
        return CommunityRepairService(mock_pool)

    @pytest.mark.asyncio
    async def test_no_empty_communities(self, service):
        """Test when no empty communities exist."""
        service._pool.execute_query = AsyncMock(return_value=[{"count": 0}])

        result = await service.repair_empty_communities()

        assert result.success is True
        assert result.affected_count == 0
        assert result.repair_type == "delete_empty_communities"

    @pytest.mark.asyncio
    async def test_dry_run_counts_only(self, service):
        """Test dry run only counts without deleting."""
        service._pool.execute_query = AsyncMock(return_value=[{"count": 5}])

        result = await service.repair_empty_communities(dry_run=True)

        assert result.affected_count == 5
        # Should not execute delete query
        assert service._pool.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_deletes_empty_communities(self, service):
        """Test deletes empty communities."""
        service._pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 3}],  # Count query
                [{"deleted": 3}],  # Delete query
            ]
        )

        result = await service.repair_empty_communities(dry_run=False)

        assert result.success is True
        assert result.affected_count == 3
        assert service._pool.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_query_error(self, service):
        """Test handles database query error."""
        service._pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        result = await service.repair_empty_communities()

        assert result.success is False


class TestRepairEntityCountMismatch:
    """Test repair_entity_count_mismatch method."""

    @pytest.fixture
    def service(self):
        """Create CommunityRepairService with mock pool."""
        mock_pool = AsyncMock()
        return CommunityRepairService(mock_pool)

    @pytest.mark.asyncio
    async def test_no_mismatches(self, service):
        """Test when no entity count mismatches exist."""
        service._pool.execute_query = AsyncMock(return_value=[])

        result = await service.repair_entity_count_mismatches()

        assert result.success is True
        assert result.affected_count == 0

    @pytest.mark.asyncio
    async def test_updates_mismatched_counts(self, service):
        """Test updates mismatched entity counts."""
        service._pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 1}],  # Count query
                [{"updated": 1}],  # Update query
            ]
        )

        result = await service.repair_entity_count_mismatches(dry_run=False)

        assert result.success is True
        assert result.affected_count >= 0

    @pytest.mark.asyncio
    async def test_dry_run_for_mismatches(self, service):
        """Test dry run for entity count mismatches."""
        service._pool.execute_query = AsyncMock(return_value=[{"count": 2}])

        result = await service.repair_entity_count_mismatches(dry_run=True)

        assert result.affected_count == 2


class TestRepairStaleReports:
    """Test repair_stale_reports method."""

    @pytest.fixture
    def service_with_generator(self):
        """Create service with report generator."""
        mock_pool = AsyncMock()
        mock_gen = AsyncMock()
        return CommunityRepairService(mock_pool, mock_gen)

    @pytest.mark.asyncio
    async def test_no_stale_reports(self, service_with_generator):
        """Test when no stale reports exist."""
        service_with_generator._pool.execute_query = AsyncMock(return_value=[])

        result = await service_with_generator.repair_stale_reports()

        assert result.success is True
        assert result.affected_count == 0

    @pytest.mark.asyncio
    async def test_regenerates_stale_reports(self, service_with_generator):
        """Test regenerates stale reports."""
        service_with_generator._pool.execute_query = AsyncMock(
            return_value=[
                {"community_id": 1, "level": 0},
            ]
        )
        service_with_generator._report_generator.regenerate_report = AsyncMock()

        result = await service_with_generator.repair_stale_reports(
            community_ids=None, dry_run=False
        )

        assert result.success is True
        service_with_generator._report_generator.regenerate_report.assert_called()

    @pytest.mark.asyncio
    async def test_stale_reports_without_generator(self):
        """Test stale reports repair without generator."""
        mock_pool = AsyncMock()
        service = CommunityRepairService(mock_pool)  # No generator
        service._pool.execute_query = AsyncMock(return_value=[{"community_id": 1}])

        result = await service.repair_stale_reports()

        # Should skip regeneration
        assert result.affected_count == 0


class TestRepairBrokenHierarchy:
    """Test repair_broken_hierarchy method."""

    @pytest.fixture
    def service(self):
        """Create CommunityRepairService with mock pool."""
        mock_pool = AsyncMock()
        return CommunityRepairService(mock_pool)

    @pytest.mark.asyncio
    async def test_no_broken_references(self, service):
        """Test when no broken hierarchy references."""
        service._pool.execute_query = AsyncMock(return_value=[])

        result = await service.repair_hierarchy_breaks()

        assert result.success is True
        assert result.affected_count == 0

    @pytest.mark.asyncio
    async def test_cleans_broken_references(self, service):
        """Test cleans up broken hierarchy references."""
        service._pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 1}],  # Count query
                [{"cleared": 1}],  # Clear query
            ]
        )

        result = await service.repair_hierarchy_breaks(dry_run=False)

        assert result.success is True


class TestRepairResult:
    """Test RepairResult model."""

    def test_create_success_result(self):
        """Test creating successful repair result."""
        result = RepairResult(
            repair_type="test_repair",
            affected_count=5,
            success=True,
        )

        assert result.repair_type == "test_repair"
        assert result.affected_count == 5
        assert result.success is True

    def test_create_failure_result(self):
        """Test creating failed repair result."""
        result = RepairResult(
            repair_type="test_repair",
            affected_count=0,
            success=False,
            error="Test error",
        )

        assert result.success is False
        assert result.error == "Test error"


class TestHealthIssue:
    """Test HealthIssue model."""

    def test_create_health_issue(self):
        """Test creating health issue."""
        issue = HealthIssue(
            issue_type=IssueType.EMPTY_COMMUNITY,
            community_id=1,
            severity="high",
            description="Community has no entities",
            suggestion="Remove the empty community",
        )

        assert issue.issue_type == IssueType.EMPTY_COMMUNITY
        assert issue.community_id == 1
        assert issue.severity == "high"


class TestCommunityRepairServiceIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_full_repair_workflow(self):
        """Test complete repair workflow."""
        mock_pool = AsyncMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        service = CommunityRepairService(mock_pool)

        # Should complete without errors
        result = await service.repair_empty_communities()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_repair_with_all_issues(self):
        """Test repair when all issue types present."""
        mock_pool = AsyncMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"count": 2}])

        service = CommunityRepairService(mock_pool)

        result = await service.repair_empty_communities(dry_run=True)
        assert result.affected_count == 2
