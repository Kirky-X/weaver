"""Unit tests for community report generator module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from modules.community.report_generator import (
    CommunityReportGenerator,
    CommunityReport,
)


class TestCommunityReport:
    """Test CommunityReport dataclass."""

    def test_initialization(self):
        """Test CommunityReport initialization."""
        report = CommunityReport(
            id="test-id",
            community_id="comm-1",
            level=0,
            title="Test Community",
            summary="Test summary",
            full_content="Full content here",
            rank=0.8,
            entity_count=10,
            relationship_count=5,
            created_at=datetime.now(timezone.utc),
            metadata={},
        )

        assert report.id == "test-id"
        assert report.community_id == "comm-1"
        assert report.title == "Test Community"


class TestCommunityReportGenerator:
    """Test CommunityReportGenerator class."""

    def test_init(self):
        """Test initialization."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        assert generator._pool == mock_pool
        assert generator._llm == mock_llm

    @pytest.mark.asyncio
    async def test_generate_report_no_entities(self):
        """Test report generation with no entities."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        report = await generator.generate_report("comm-1")

        assert report.community_id == "comm-1"
        assert report.entity_count == 0

    @pytest.mark.asyncio
    async def test_generate_report_with_entities(self):
        """Test report generation with entities."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(side_effect=[
            [{"name": "Entity1", "type": "人物", "description": "Desc1"}],
            [{"source": "Entity1", "target": "Entity2", "type": "工作于", "weight": 1.0}],
        ])
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "标题: 测试社区\n摘要: 这是一个测试社区。\n\n详细报告内容。"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        report = await generator.generate_report("comm-1")

        assert report.community_id == "comm-1"
        assert report.entity_count >= 0

    @pytest.mark.asyncio
    async def test_generate_reports_batch(self):
        """Test batch report generation."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        reports = await generator.generate_reports_batch(["comm-1", "comm-2"])

        assert len(reports) == 2

    @pytest.mark.asyncio
    async def test_get_report_exists(self):
        """Test getting existing report."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{
            "id": "report-1",
            "community_id": "comm-1",
            "level": 0,
            "title": "Test",
            "summary": "Summary",
            "full_content": "Content",
            "rank": 0.5,
            "entity_count": 10,
            "relationship_count": 5,
            "created_at": datetime.now(timezone.utc),
        }])
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        report = await generator.get_report("comm-1")

        assert report is not None

    @pytest.mark.asyncio
    async def test_get_report_not_exists(self):
        """Test getting non-existing report."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        report = await generator.get_report("non-existent")

        assert report is None

    def test_prepare_content(self):
        """Test content preparation."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        entities = [
            {"name": "Entity1", "type": "人物", "description": "Desc1"},
            {"name": "Entity2", "type": "组织机构", "description": "Desc2"},
        ]
        relationships = [
            {"source": "Entity1", "target": "Entity2", "type": "工作于"},
        ]

        content = generator._prepare_content(entities, relationships)

        assert "Entity1" in content
        assert "Entity2" in content

    def test_parse_generated_content(self):
        """Test parsing generated content."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        content = "标题: 测试\n摘要: 这是一个摘要。\n\n详细报告内容。"
        title, summary = generator._parse_generated_content(content)

        assert isinstance(title, str)
        assert isinstance(summary, str)

    def test_calculate_rank(self):
        """Test rank calculation."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        entities = [{"type": "人物"}, {"type": "人物"}]
        relationships = [{"type": "工作于"}]

        rank = generator._calculate_rank(entities, relationships)

        assert rank >= 0.0

    def test_count_entity_types(self):
        """Test entity type counting."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)

        entities = [
            {"type": "人物"},
            {"type": "人物"},
            {"type": "组织机构"},
        ]

        counts = generator._count_entity_types(entities)

        assert counts["人物"] == 2
        assert counts["组织机构"] == 1
