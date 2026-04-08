# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Community API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from modules.knowledge.graph.community_models import (
    Community,
    CommunityDetectionResult,
    CommunityReport,
)


class TestCommunityModels:
    """Tests for Community API models."""

    def test_rebuild_request_defaults(self):
        """Test RebuildRequest default values."""
        from api.endpoints.communities import RebuildRequest

        request = RebuildRequest()
        assert request.max_cluster_size == 10
        assert request.seed == 42

    def test_rebuild_request_validation(self):
        """Test RebuildRequest validation."""
        from api.endpoints.communities import RebuildRequest

        # Valid values
        request = RebuildRequest(max_cluster_size=50, seed=123)
        assert request.max_cluster_size == 50

        # Invalid max_cluster_size (too large)
        with pytest.raises(ValueError):
            RebuildRequest(max_cluster_size=200)

    def test_community_response_model(self):
        """Test CommunityResponse model."""
        from api.endpoints.communities import CommunityResponse

        response = CommunityResponse(
            id=str(uuid.uuid4()),
            title="Test Community",
            level=0,
            entity_count=10,
            parent_id=None,
            rank=8.5,
            period="2024-Q1",
            has_report=True,
        )
        assert response.title == "Test Community"
        assert response.has_report is True

    def test_community_detail_response_model(self):
        """Test CommunityDetailResponse model."""
        from api.endpoints.communities import CommunityDetailResponse

        response = CommunityDetailResponse(
            id=str(uuid.uuid4()),
            title="Detailed Community",
            level=1,
            entity_count=25,
            parent_id=str(uuid.uuid4()),
            children_ids=[str(uuid.uuid4())],
            rank=9.0,
            period="2024-Q1",
            modularity=0.45,
            entities=[{"name": "Entity1", "type": "Person"}],
            report={"summary": "Test summary"},
        )
        assert response.level == 1
        assert len(response.children_ids) == 1
        assert response.report is not None


class TestRebuildCommunitiesEndpoint:
    """Tests for POST /admin/communities/rebuild endpoint."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        return AsyncMock()

    @pytest.fixture
    def mock_detector(self):
        """Mock CommunityDetector."""
        detector = MagicMock()
        detector.rebuild_communities = AsyncMock(
            return_value=CommunityDetectionResult(
                communities=[],
                total_communities=10,
                total_entities=100,
                levels=2,
                modularity=0.45,
                orphan_count=5,
                execution_time_ms=1500.0,
            )
        )
        return detector

    @pytest.mark.asyncio
    async def test_rebuild_communities_success(self, mock_pool, mock_detector):
        """Test successful community rebuild."""
        from api.endpoints.communities import RebuildRequest, rebuild_communities

        with patch(
            "api.endpoints.communities.CommunityDetector",
            return_value=mock_detector,
        ):
            with patch(
                "api.endpoints.communities.get_graph_pool",
                return_value=mock_pool,
            ):
                request = RebuildRequest(max_cluster_size=10, seed=42)
                result = await rebuild_communities(
                    request=request,
                    _="test-api-key",
                    pool=mock_pool,
                )

                assert result.data.status == "completed"
                assert result.data.communities_created == 10
                assert result.data.entities_processed == 100
                assert result.data.modularity == 0.45

    @pytest.mark.asyncio
    async def test_rebuild_communities_failure(self, mock_pool):
        """Test community rebuild failure."""
        from api.endpoints.communities import RebuildRequest, rebuild_communities

        mock_detector = MagicMock()
        mock_detector.rebuild_communities = AsyncMock(side_effect=Exception("Detection failed"))

        with patch(
            "api.endpoints.communities.CommunityDetector",
            return_value=mock_detector,
        ):
            with patch(
                "api.endpoints.communities.get_graph_pool",
                return_value=mock_pool,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    request = RebuildRequest()
                    await rebuild_communities(
                        request=request,
                        _="test-api-key",
                        pool=mock_pool,
                    )
                assert exc_info.value.status_code == 500


class TestGenerateReportsEndpoint:
    """Tests for POST /admin/communities/reports/generate endpoint."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        return AsyncMock()

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_generate_all_reports_success(self, mock_pool, mock_llm):
        """Test successful report generation."""
        from api.endpoints.communities import generate_all_reports

        mock_generator = MagicMock()
        mock_generator.generate_all_reports = AsyncMock(
            return_value={
                "total": 10,
                "success": 8,
                "failed": 2,
                "failed_ids": ["id-1", "id-2"],
            }
        )

        with patch(
            "api.endpoints.communities.CommunityReportGenerator",
            return_value=mock_generator,
        ):
            result = await generate_all_reports(
                level=None,
                regenerate_stale=True,
                _="test-api-key",
                pool=mock_pool,
                llm=mock_llm,
            )

            assert result.data.total == 10
            assert result.data.success == 8
            assert result.data.failed == 2
            assert len(result.data.failed_ids) == 2

    @pytest.mark.asyncio
    async def test_generate_reports_with_level_filter(self, mock_pool, mock_llm):
        """Test report generation with level filter."""
        from api.endpoints.communities import generate_all_reports

        mock_generator = MagicMock()
        mock_generator.generate_all_reports = AsyncMock(
            return_value={"total": 5, "success": 5, "failed": 0, "failed_ids": []}
        )

        with patch(
            "api.endpoints.communities.CommunityReportGenerator",
            return_value=mock_generator,
        ):
            result = await generate_all_reports(
                level=0,
                regenerate_stale=False,
                _="test-api-key",
                pool=mock_pool,
                llm=mock_llm,
            )

            assert result.data.total == 5
            assert result.data.failed == 0


class TestRegenerateReportEndpoint:
    """Tests for POST /admin/communities/{id}/report/regenerate endpoint."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        return AsyncMock()

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_regenerate_report_success(self, mock_pool, mock_llm):
        """Test successful report regeneration."""
        from api.endpoints.communities import regenerate_report
        from modules.knowledge.graph.community_report_generator import (
            ReportGenerationResult,
        )

        community_id = str(uuid.uuid4())
        mock_generator = MagicMock()
        mock_generator.regenerate_report = AsyncMock(
            return_value=ReportGenerationResult(
                success=True,
                community_id=community_id,
                report_id=str(uuid.uuid4()),
                error=None,
            )
        )

        with patch(
            "api.endpoints.communities.CommunityReportGenerator",
            return_value=mock_generator,
        ):
            result = await regenerate_report(
                community_id=community_id,
                _="test-api-key",
                pool=mock_pool,
                llm=mock_llm,
            )

            assert result.data["status"] == "completed"
            assert result.data["community_id"] == community_id

    @pytest.mark.asyncio
    async def test_regenerate_report_failure(self, mock_pool, mock_llm):
        """Test report regeneration failure."""
        from api.endpoints.communities import regenerate_report
        from modules.knowledge.graph.community_report_generator import (
            ReportGenerationResult,
        )

        community_id = str(uuid.uuid4())
        mock_generator = MagicMock()
        mock_generator.regenerate_report = AsyncMock(
            return_value=ReportGenerationResult(
                success=False,
                community_id=community_id,
                report_id=None,
                error="LLM failed",
            )
        )

        with patch(
            "api.endpoints.communities.CommunityReportGenerator",
            return_value=mock_generator,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await regenerate_report(
                    community_id=community_id,
                    _="test-api-key",
                    pool=mock_pool,
                    llm=mock_llm,
                )
            assert exc_info.value.status_code == 500


class TestListCommunitiesEndpoint:
    """Tests for GET /graph/communities endpoint."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = AsyncMock()
        pool.execute_query = AsyncMock(return_value=[])
        return pool

    @pytest.mark.asyncio
    async def test_list_communities_success(self, mock_pool):
        """Test successful community listing."""
        from api.endpoints.communities import list_communities

        mock_repo = MagicMock()
        mock_repo.list_communities = AsyncMock(
            return_value=[
                Community(
                    id=str(uuid.uuid4()),
                    title="Community 1",
                    level=0,
                    entity_count=10,
                    parent_id=None,
                    rank=8.0,
                    period=None,
                    modularity=None,
                ),
            ]
        )
        mock_repo.count_communities = AsyncMock(return_value=1)
        mock_repo.get_report = AsyncMock(return_value=None)

        with patch(
            "api.endpoints.communities.Neo4jCommunityRepo",
            return_value=mock_repo,
        ):
            with patch(
                "api.endpoints.communities.get_graph_pool",
                return_value=mock_pool,
            ):
                result = await list_communities(
                    level=None,
                    limit=20,
                    offset=0,
                    _="test-api-key",
                    pool=mock_pool,
                )

                assert result.data.total == 1
                assert len(result.data.communities) == 1

    @pytest.mark.asyncio
    async def test_list_communities_with_level_filter(self, mock_pool):
        """Test community listing with level filter."""
        from api.endpoints.communities import list_communities

        mock_repo = MagicMock()
        mock_repo.list_communities = AsyncMock(return_value=[])
        mock_repo.count_communities = AsyncMock(return_value=0)

        with patch(
            "api.endpoints.communities.Neo4jCommunityRepo",
            return_value=mock_repo,
        ):
            with patch(
                "api.endpoints.communities.get_graph_pool",
                return_value=mock_pool,
            ):
                result = await list_communities(
                    level=0,
                    limit=10,
                    offset=0,
                    _="test-api-key",
                    pool=mock_pool,
                )

                assert result.data.level == 0


class TestGetCommunityEndpoint:
    """Tests for GET /graph/communities/{community_id} endpoint."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = AsyncMock()
        pool.execute_query = AsyncMock(return_value=[])
        return pool

    @pytest.mark.asyncio
    async def test_get_community_success(self, mock_pool):
        """Test successful community retrieval."""
        from api.endpoints.communities import get_community

        community_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get_community = AsyncMock(
            return_value=Community(
                id=community_id,
                title="Test Community",
                level=0,
                entity_count=15,
                parent_id=None,
                rank=9.0,
                period="2024-Q1",
                modularity=0.42,
            )
        )
        mock_repo.get_report = AsyncMock(
            return_value=CommunityReport(
                id=str(uuid.uuid4()),
                community_id=community_id,
                title="Test Community Report",
                summary="Test summary",
                full_content="Full content",
                key_entities=["Entity1"],
                key_relationships=[],
                rank=9.0,
            )
        )

        with patch(
            "api.endpoints.communities.Neo4jCommunityRepo",
            return_value=mock_repo,
        ):
            with patch(
                "api.endpoints.communities.get_graph_pool",
                return_value=mock_pool,
            ):
                result = await get_community(
                    community_id=community_id,
                    _="test-api-key",
                    pool=mock_pool,
                )

                assert result.data.id == community_id
                assert result.data.title == "Test Community"
                assert result.data.report is not None

    @pytest.mark.asyncio
    async def test_get_community_not_found(self, mock_pool):
        """Test community not found."""
        from api.endpoints.communities import get_community

        community_id = str(uuid.uuid4())
        mock_repo = MagicMock()
        mock_repo.get_community = AsyncMock(return_value=None)

        with patch(
            "api.endpoints.communities.Neo4jCommunityRepo",
            return_value=mock_repo,
        ):
            with patch(
                "api.endpoints.communities.get_graph_pool",
                return_value=mock_pool,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await get_community(
                        community_id=community_id,
                        _="test-api-key",
                        pool=mock_pool,
                    )
                assert exc_info.value.status_code == 404


class TestDependencies:
    """Tests for dependency functions."""

    # NOTE: set_neo4j_pool and set_llm_client functions removed from api.endpoints.communities
    # Now uses api.dependencies via FastAPI dependency injection

    # NOTE: _neo4j_pool and _llm_client module-level variables removed
    # The get_graph_pool and get_llm_client functions now use api.dependencies
