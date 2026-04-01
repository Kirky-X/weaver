# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for knowledge community CommunityReportGenerator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.community.report_generator import (
    CommunityReportGenerator,
    CommunityReportOutput,
    ReportGenerationResult,
)


@pytest.fixture
def mock_pool():
    """Mock Neo4jPool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient."""
    client = MagicMock()
    client.call = AsyncMock()
    return client


@pytest.fixture
def generator(mock_pool, mock_llm_client):
    """Create CommunityReportGenerator instance."""
    return CommunityReportGenerator(mock_pool, mock_llm_client)


class TestCommunityReportGeneratorInit:
    """Tests for CommunityReportGenerator initialization."""

    def test_init(self, mock_pool, mock_llm_client):
        """Test basic initialization."""
        generator = CommunityReportGenerator(mock_pool, mock_llm_client)
        assert generator._pool is mock_pool
        assert generator._llm is mock_llm_client
        assert generator._max_concurrent == 5

    def test_custom_concurrency(self, mock_pool, mock_llm_client):
        """Test initialization with custom concurrency."""
        generator = CommunityReportGenerator(mock_pool, mock_llm_client, max_concurrent=10)
        assert generator._max_concurrent == 10


class TestGenerateReport:
    """Tests for generate_report method."""

    @pytest.mark.asyncio
    async def test_generate_report_community_not_found(self, generator, mock_pool):
        """Test report generation when community not found."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await generator.generate_report("nonexistent")

        assert result.success is False
        assert result.community_id == "nonexistent"


class TestCommunityReportOutput:
    """Tests for CommunityReportOutput model."""

    def test_model_creation(self):
        """Test model can be created with valid data."""
        report = CommunityReportOutput(
            title="Test Title",
            summary="Test Summary",
            full_content="Test Content",
            key_entities=["Entity1", "Entity2"],
            key_relationships=["Rel1"],
            rank=7.5,
        )

        assert report.title == "Test Title"
        assert report.summary == "Test Summary"
        assert report.rank == 7.5

    def test_model_defaults(self):
        """Test model default values."""
        report = CommunityReportOutput(
            title="Test",
            summary="Summary",
            full_content="Content",
            rank=5.0,
        )

        assert report.key_entities == []
        assert report.key_relationships == []


class TestReportGenerationResult:
    """Tests for ReportGenerationResult dataclass."""

    def test_success_result(self):
        """Test successful result."""
        result = ReportGenerationResult(
            community_id="comm-1",
            success=True,
            report_id="report-1",
        )

        assert result.community_id == "comm-1"
        assert result.success is True
        assert result.report_id == "report-1"
        assert result.error is None

    def test_failure_result(self):
        """Test failure result."""
        result = ReportGenerationResult(
            community_id="comm-1",
            success=False,
            error="Generation failed",
        )

        assert result.success is False
        assert result.error == "Generation failed"
        assert result.report_id is None


class TestGenerateReportWithEntities:
    """Tests for generate_report with community data."""

    @pytest.mark.asyncio
    async def test_community_no_entities(self, generator, mock_pool):
        """Community found but has no entities."""
        call_count = 0

        async def mock_query(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"id": "c-1", "level": 0, "entity_count": 0}]
            if call_count == 2:
                return []  # No entities
            return []

        mock_pool.execute_query = mock_query
        result = await generator.generate_report("c-1")
        assert result.success is False
        assert "no entities" in result.error.lower()

    @pytest.mark.asyncio
    async def test_community_with_entities_llm_fails(self, generator, mock_pool):
        """Community has entities but LLM call fails."""
        call_count = 0

        async def mock_query(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"id": "c-1", "level": 0, "entity_count": 2}]
            if call_count == 2:
                return [{"name": "华为", "type": "组织", "description": "Tech"}]
            if call_count == 3:
                return [
                    {"source": "华为", "relation_type": "合作", "target": "比亚迪", "weight": 1.0}
                ]
            return []

        mock_pool.execute_query = mock_query

        # Mock LLM prompts and call
        mock_llm = generator._llm
        mock_llm._prompts = MagicMock()
        mock_llm._prompts.get.return_value = "{community_id}"
        mock_llm.call_at = AsyncMock(return_value=None)

        result = await generator.generate_report("c-1")
        assert result.success is False
        assert "LLM" in result.error

    @pytest.mark.asyncio
    async def test_full_report_generation(self, generator, mock_pool):
        """Full successful report generation flow."""
        call_count = 0

        async def mock_query(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"id": "c-1", "level": 0, "entity_count": 2}]
            if call_count == 2:
                return [{"name": "华为", "type": "组织", "description": "Tech"}]
            if call_count == 3:
                return [
                    {"source": "华为", "relation_type": "合作", "target": "比亚迪", "weight": 1.0}
                ]
            return []

        mock_pool.execute_query = mock_query

        # Mock LLM
        mock_llm = generator._llm
        mock_llm._prompts = MagicMock()
        mock_llm._prompts.get.return_value = "{community_id}"
        report_output = CommunityReportOutput(
            title="Tech Community",
            summary="A tech community",
            full_content="Full report content",
            key_entities=["华为"],
            key_relationships=["合作"],
            rank=7.0,
        )
        mock_llm.call_at = AsyncMock(return_value=report_output)
        mock_llm.embed = AsyncMock(return_value=[[0.1, 0.2]])

        # Mock repo methods
        generator._repo.create_report = AsyncMock(return_value="r-1")
        generator._repo.update_report_embedding = AsyncMock(return_value=True)

        result = await generator.generate_report("c-1")
        assert result.success is True
        assert result.report_id == "r-1"


class TestRegenerateReport:
    """Tests for regenerate_report method."""

    @pytest.mark.asyncio
    async def test_regenerate_deletes_first(self, generator, mock_pool):
        """Regenerate deletes existing report first."""
        mock_pool.execute_query = AsyncMock(return_value=[])
        generator._repo.delete_report = AsyncMock(return_value=True)

        result = await generator.regenerate_report("c-1")
        # Will fail since community not found, but delete was called
        generator._repo.delete_report.assert_called_once_with("c-1")


class TestMarkStaleReports:
    """Tests for mark_stale_reports method."""

    @pytest.mark.asyncio
    async def test_mark_stale(self, generator, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[{"stale_count": 3}])
        count = await generator.mark_stale_reports()
        assert count == 3

    @pytest.mark.asyncio
    async def test_mark_stale_none(self, generator, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[])
        count = await generator.mark_stale_reports()
        assert count == 0


class TestStoreReportEmbedding:
    """Tests for _store_report_embedding method."""

    @pytest.mark.asyncio
    async def test_store_embedding_success(self, generator, mock_llm_client):
        mock_llm_client.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        generator._repo.update_report_embedding = AsyncMock(return_value=True)

        result = await generator._store_report_embedding("r-1", "content")
        assert result is True

    @pytest.mark.asyncio
    async def test_store_embedding_no_embeddings(self, generator, mock_llm_client):
        mock_llm_client.embed = AsyncMock(return_value=None)
        result = await generator._store_report_embedding("r-1", "content")
        assert result is False

    @pytest.mark.asyncio
    async def test_store_embedding_error(self, generator, mock_llm_client):
        mock_llm_client.embed = AsyncMock(side_effect=Exception("embed error"))
        result = await generator._store_report_embedding("r-1", "content")
        assert result is False


class TestGenerateReportException:
    """Tests for generate_report exception handling."""

    @pytest.mark.asyncio
    async def test_generate_report_general_exception(self, generator, mock_pool):
        """Test generate_report catches general exceptions."""
        mock_pool.execute_query = AsyncMock(side_effect=RuntimeError("Unexpected"))

        result = await generator.generate_report("c-1")

        assert result.success is False
        assert "Unexpected" in result.error


class TestGenerateAllReports:
    """Tests for generate_all_reports method."""

    @pytest.mark.asyncio
    async def test_generate_all_no_communities(self, generator, mock_pool):
        """Test with no communities."""
        generator._repo.list_communities = AsyncMock(return_value=[])
        result = await generator.generate_all_reports()
        assert result["total"] == 0
        assert result["success"] == 0

    @pytest.mark.asyncio
    async def test_generate_all_with_communities(self, generator, mock_pool):
        """Test batch generation with mock communities."""
        mock_comm = MagicMock()
        mock_comm.id = "c-1"
        mock_comm.level = 0

        generator._repo.list_communities = AsyncMock(return_value=[mock_comm])
        generator._repo.get_report = AsyncMock(return_value=None)  # no existing report

        # Mock generate_report to succeed
        with patch.object(
            generator,
            "generate_report",
            new_callable=AsyncMock,
            return_value=ReportGenerationResult(
                community_id="c-1",
                success=True,
                report_id="r-1",
            ),
        ):
            result = await generator.generate_all_reports()

        assert result["success"] == 1
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_generate_all_skips_orphans(self, generator, mock_pool):
        """Test that orphan communities (level=-1) are skipped."""
        mock_comm = MagicMock()
        mock_comm.id = "c-orphan"
        mock_comm.level = -1

        generator._repo.list_communities = AsyncMock(return_value=[mock_comm])

        result = await generator.generate_all_reports()

        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_generate_all_stale_regenerate(self, generator, mock_pool):
        """Test that stale reports are regenerated."""
        mock_comm = MagicMock()
        mock_comm.id = "c-1"
        mock_comm.level = 0

        mock_report = MagicMock()
        mock_report.stale = True

        generator._repo.list_communities = AsyncMock(return_value=[mock_comm])
        generator._repo.get_report = AsyncMock(return_value=mock_report)
        generator._repo.delete_report = AsyncMock()

        with patch.object(
            generator,
            "generate_report",
            new_callable=AsyncMock,
            return_value=ReportGenerationResult(
                community_id="c-1",
                success=True,
                report_id="r-new",
            ),
        ):
            result = await generator.generate_all_reports(regenerate_stale=True)

        assert result["success"] == 1
        generator._repo.delete_report.assert_called_once_with("c-1")

    @pytest.mark.asyncio
    async def test_generate_all_non_stale_skipped(self, generator, mock_pool):
        """Test that non-stale reports are skipped."""
        mock_comm = MagicMock()
        mock_comm.id = "c-1"
        mock_comm.level = 0

        mock_report = MagicMock()
        mock_report.stale = False

        generator._repo.list_communities = AsyncMock(return_value=[mock_comm])
        generator._repo.get_report = AsyncMock(return_value=mock_report)

        result = await generator.generate_all_reports(regenerate_stale=True)

        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_generate_all_with_failure(self, generator, mock_pool):
        """Test batch generation when some reports fail."""
        mock_comm = MagicMock()
        mock_comm.id = "c-1"
        mock_comm.level = 0

        generator._repo.list_communities = AsyncMock(return_value=[mock_comm])
        generator._repo.get_report = AsyncMock(return_value=None)

        with patch.object(
            generator,
            "generate_report",
            new_callable=AsyncMock,
            return_value=ReportGenerationResult(
                community_id="c-1",
                success=False,
                error="LLM failed",
            ),
        ):
            result = await generator.generate_all_reports()

        assert result["failed"] == 1
        assert "c-1" in result["failed_ids"]

    @pytest.mark.asyncio
    async def test_generate_all_with_exception(self, generator, mock_pool):
        """Test batch generation handles unexpected exceptions."""
        mock_comm = MagicMock()
        mock_comm.id = "c-1"
        mock_comm.level = 0

        generator._repo.list_communities = AsyncMock(return_value=[mock_comm])
        generator._repo.get_report = AsyncMock(return_value=None)

        with patch.object(
            generator,
            "generate_report",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Unexpected"),
        ):
            result = await generator.generate_all_reports()

        assert result["failed"] == 1


class TestCallLLM:
    """Tests for _call_llm method."""

    @pytest.mark.asyncio
    async def test_call_llm_no_relationships(self, generator, mock_llm_client):
        """Test _call_llm with no relationships uses fallback text."""
        mock_llm_client._prompts = MagicMock()
        mock_llm_client._prompts.get.return_value = "{community_id}"

        report_output = CommunityReportOutput(title="T", summary="S", full_content="C", rank=5.0)
        mock_llm_client.call_at = AsyncMock(return_value=report_output)

        result = await generator._call_llm(
            community_id="c-1",
            level=0,
            entity_count=1,
            entities=[{"name": "E1", "type": "ORG", "description": "desc"}],
            relationships=[],
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_call_llm_exception(self, generator, mock_llm_client):
        """Test _call_llm handles exception."""
        mock_llm_client._prompts = MagicMock()
        mock_llm_client._prompts.get.return_value = "{community_id}"
        mock_llm_client.call_at = AsyncMock(side_effect=Exception("LLM error"))

        result = await generator._call_llm(
            community_id="c-1",
            level=0,
            entity_count=1,
            entities=[{"name": "E1", "type": "ORG", "description": "desc"}],
            relationships=[],
        )

        assert result is None
