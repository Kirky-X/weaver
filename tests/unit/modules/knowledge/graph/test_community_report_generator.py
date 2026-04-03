# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CommunityReportGenerator."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.graph.community_models import Community, CommunityReport
from modules.knowledge.graph.community_report_generator import (
    CommunityReportGenerator,
    CommunityReportOutput,
    ReportGenerationResult,
)


class TestCommunityReportGeneratorInit:
    """Test CommunityReportGenerator initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        generator = CommunityReportGenerator(mock_pool, mock_llm)

        assert generator._pool == mock_pool
        assert generator._llm == mock_llm
        assert generator._max_concurrent == 5

    def test_init_with_custom_concurrency(self):
        """Test initialization with custom concurrency."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        generator = CommunityReportGenerator(mock_pool, mock_llm, max_concurrent=10)

        assert generator._max_concurrent == 10


class TestCommunityReportGeneratorGenerateReport:
    """Test generate_report method."""

    @pytest.fixture
    def generator(self):
        """Create CommunityReportGenerator with mocked dependencies."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()

        llm = MagicMock()
        llm._prompts = MagicMock()
        llm._prompts.get = MagicMock(return_value="Test prompt")
        llm.call_at = AsyncMock()
        llm.embed = AsyncMock(return_value=[[0.1] * 1536])

        generator = CommunityReportGenerator(pool, llm)
        generator._repo = MagicMock()
        generator._repo.get_report = AsyncMock(return_value=None)
        generator._repo.create_report = AsyncMock(return_value="report-id")
        generator._repo.update_report_embedding = AsyncMock(return_value=True)
        generator._repo.delete_report = AsyncMock(return_value=True)

        return generator

    @pytest.mark.asyncio
    async def test_generate_report_success(self, generator):
        """Test successful report generation."""
        # Mock community data
        generator._pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "community-1", "level": 0, "entity_count": 3}],  # community data
                [  # entities
                    {"name": "OpenAI", "type": "组织机构", "description": "AI公司"},
                    {"name": "GPT-4", "type": "产品", "description": "大语言模型"},
                ],
                [  # relationships
                    {"source": "OpenAI", "relation_type": "开发", "target": "GPT-4", "weight": 1.0},
                ],
            ]
        )

        # Mock LLM response - call_at returns CommunityReportOutput when output_model is used
        generator._llm.call_at = AsyncMock(
            return_value=CommunityReportOutput(
                title="AI技术社区",
                summary="这是一个关于AI技术的社区",
                full_content="完整报告内容...",
                key_entities=["OpenAI", "GPT-4"],
                key_relationships=["OpenAI --开发--> GPT-4"],
                rank=8.5,
            )
        )

        result = await generator.generate_report("community-1")

        assert result.success is True
        assert result.report_id == "report-id"
        assert result.community_id == "community-1"

    @pytest.mark.asyncio
    async def test_generate_report_community_not_found(self, generator):
        """Test report generation when community not found."""
        generator._pool.execute_query = AsyncMock(return_value=[])

        result = await generator.generate_report("non-existent")

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_generate_report_no_entities(self, generator):
        """Test report generation when community has no entities."""
        generator._pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "community-1", "level": 0, "entity_count": 0}],
                [],  # No entities
                [],  # No relationships
            ]
        )

        result = await generator.generate_report("community-1")

        assert result.success is False
        assert "no entities" in result.error.lower()

    @pytest.mark.asyncio
    async def test_generate_report_llm_failure(self, generator):
        """Test report generation when LLM fails."""
        generator._pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "community-1", "level": 0, "entity_count": 1}],
                [{"name": "Test", "type": "未知", "description": ""}],
                [],
            ]
        )

        # LLM returns None
        generator._llm.call_at = AsyncMock(return_value=None)

        result = await generator.generate_report("community-1")

        assert result.success is False
        assert "failed" in result.error.lower()


class TestCommunityReportGeneratorGenerateAllReports:
    """Test generate_all_reports method."""

    @pytest.fixture
    def generator(self):
        """Create CommunityReportGenerator with mocked dependencies."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()

        llm = MagicMock()
        llm._prompts = MagicMock()
        llm._prompts.get = MagicMock(return_value="Test prompt")
        llm.call_at = AsyncMock()
        llm.embed = AsyncMock(return_value=[[0.1] * 1536])

        generator = CommunityReportGenerator(pool, llm)
        generator._repo = MagicMock()
        generator._repo.get_report = AsyncMock(return_value=None)
        generator._repo.create_report = AsyncMock(return_value="report-id")
        generator._repo.update_report_embedding = AsyncMock(return_value=True)
        generator._repo.delete_report = AsyncMock(return_value=True)

        return generator

    @pytest.mark.asyncio
    async def test_generate_all_reports_success(self, generator):
        """Test batch report generation."""
        # Mock list_communities
        generator._repo.list_communities = AsyncMock(
            return_value=[
                Community(id="c1", title="C1", level=0, entity_count=2),
                Community(id="c2", title="C2", level=0, entity_count=2),
            ]
        )

        # Mock generate_report to succeed
        generator.generate_report = AsyncMock(
            return_value=ReportGenerationResult(
                community_id="c1",
                success=True,
                report_id="report-id",
            )
        )

        result = await generator.generate_all_reports()

        assert result["total"] == 2
        assert result["success"] == 2
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_generate_all_reports_with_failures(self, generator):
        """Test batch report generation with some failures."""
        generator._repo.list_communities = AsyncMock(
            return_value=[
                Community(id="c1", title="C1", level=0, entity_count=2),
                Community(id="c2", title="C2", level=0, entity_count=2),
                Community(id="c3", title="C3", level=0, entity_count=2),
            ]
        )

        # Mock generate_report with mixed results
        generator.generate_report = AsyncMock(
            side_effect=[
                ReportGenerationResult(community_id="c1", success=True, report_id="r1"),
                ReportGenerationResult(community_id="c2", success=False, error="Failed"),
                ReportGenerationResult(community_id="c3", success=True, report_id="r3"),
            ]
        )

        result = await generator.generate_all_reports()

        assert result["total"] == 3
        assert result["success"] == 2
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_generate_all_reports_skips_orphans(self, generator):
        """Test that batch generation skips orphan communities."""
        generator._repo.list_communities = AsyncMock(
            return_value=[
                Community(id="c1", title="C1", level=0, entity_count=2),
                Community(id="orphan", title="Orphan", level=-1, entity_count=1),  # Orphan
            ]
        )

        generator.generate_report = AsyncMock(
            return_value=ReportGenerationResult(
                community_id="c1",
                success=True,
                report_id="report-id",
            )
        )

        result = await generator.generate_all_reports()

        # Should only process non-orphan community
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_generate_all_reports_with_level_filter(self, generator):
        """Test batch generation with level filter."""
        generator._repo.list_communities = AsyncMock(
            return_value=[
                Community(id="c1", title="C1", level=1, entity_count=2),
            ]
        )

        generator.generate_report = AsyncMock(
            return_value=ReportGenerationResult(
                community_id="c1",
                success=True,
                report_id="report-id",
            )
        )

        result = await generator.generate_all_reports(level=1)

        # list_communities should be called with level filter
        generator._repo.list_communities.assert_called_once_with(level=1, limit=10000)


class TestCommunityReportGeneratorRegenerateReport:
    """Test regenerate_report method."""

    @pytest.fixture
    def generator(self):
        """Create CommunityReportGenerator with mocked dependencies."""
        pool = MagicMock()
        llm = MagicMock()
        generator = CommunityReportGenerator(pool, llm)
        generator._repo = MagicMock()
        generator._repo.delete_report = AsyncMock(return_value=True)
        generator.generate_report = AsyncMock(
            return_value=ReportGenerationResult(
                community_id="community-1",
                success=True,
                report_id="new-report-id",
            )
        )
        return generator

    @pytest.mark.asyncio
    async def test_regenerate_report_deletes_existing(self, generator):
        """Test that regenerate deletes existing report first."""
        await generator.regenerate_report("community-1")

        generator._repo.delete_report.assert_called_once_with("community-1")

    @pytest.mark.asyncio
    async def test_regenerate_report_generates_new(self, generator):
        """Test that regenerate generates new report."""
        result = await generator.regenerate_report("community-1")

        assert result.success is True
        assert result.report_id == "new-report-id"


class TestCommunityReportOutput:
    """Test CommunityReportOutput model."""

    def test_valid_output(self):
        """Test creating valid output."""
        output = CommunityReportOutput(
            title="AI技术社区",
            summary="这是一个关于AI技术的社区",
            full_content="完整报告内容" * 100,
            key_entities=["OpenAI", "GPT-4"],
            key_relationships=["OpenAI --开发--> GPT-4"],
            rank=8.5,
        )

        assert output.title == "AI技术社区"
        assert output.rank == 8.5

    def test_rank_validation(self):
        """Test rank validation (1-10 range)."""
        # Valid rank
        output = CommunityReportOutput(
            title="Test",
            summary="Summary",
            full_content="Content",
            rank=5.0,
        )
        assert output.rank == 5.0

        # Invalid rank (too high)
        with pytest.raises(ValueError):
            CommunityReportOutput(
                title="Test",
                summary="Summary",
                full_content="Content",
                rank=15.0,
            )

        # Invalid rank (too low)
        with pytest.raises(ValueError):
            CommunityReportOutput(
                title="Test",
                summary="Summary",
                full_content="Content",
                rank=0.5,
            )


class TestReportGenerationResult:
    """Test ReportGenerationResult dataclass."""

    def test_success_result(self):
        """Test successful result."""
        result = ReportGenerationResult(
            community_id="community-1",
            success=True,
            report_id="report-id",
        )

        assert result.community_id == "community-1"
        assert result.success is True
        assert result.report_id == "report-id"
        assert result.error is None

    def test_failure_result(self):
        """Test failure result."""
        result = ReportGenerationResult(
            community_id="community-1",
            success=False,
            error="Generation failed",
        )

        assert result.success is False
        assert result.error == "Generation failed"
        assert result.report_id is None
