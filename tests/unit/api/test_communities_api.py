# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for communities API endpoints."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestCommunitiesModels:
    """Tests for communities request/response models."""

    def test_rebuild_request_model(self) -> None:
        """Test RebuildRequest model."""
        from api.endpoints.communities import RebuildRequest

        request = RebuildRequest(max_cluster_size=20, seed=123)
        assert request.max_cluster_size == 20
        assert request.seed == 123

    def test_rebuild_response_model(self) -> None:
        """Test RebuildResponse model."""
        from api.endpoints.communities import RebuildResponse

        response = RebuildResponse(
            status="completed",
            communities_created=150,
            entities_processed=500,
            levels=3,
            modularity=0.85,
            orphan_count=5,
            execution_time_ms=2500.0,
        )
        assert response.status == "completed"
        assert response.communities_created == 150
        assert response.entities_processed == 500
        assert response.levels == 3
        assert response.modularity == 0.85
        assert response.orphan_count == 5

    def test_report_generate_response_model(self) -> None:
        """Test ReportGenerateResponse model."""
        from api.endpoints.communities import ReportGenerateResponse

        response = ReportGenerateResponse(
            total=10,
            success=8,
            failed=2,
            failed_ids=["comm-1", "comm-2"],
        )
        assert response.total == 10
        assert response.success == 8
        assert response.failed == 2
        assert len(response.failed_ids) == 2

    def test_community_response_model(self) -> None:
        """Test CommunityResponse model."""
        from api.endpoints.communities import CommunityResponse

        response = CommunityResponse(
            id="comm-123",
            title="Tech Companies",
            level=1,
            entity_count=25,
            parent_id="comm-parent",
            period="2024-Q1",
        )
        assert response.id == "comm-123"
        assert response.title == "Tech Companies"
        assert response.level == 1
        assert response.entity_count == 25

    def test_community_detail_response_model(self) -> None:
        """Test CommunityDetailResponse model."""
        from api.endpoints.communities import CommunityDetailResponse

        response = CommunityDetailResponse(
            id="comm-123",
            title="Tech Companies",
            level=1,
            entity_count=25,
            parent_id="comm-parent",
            children_ids=["comm-child-1", "comm-child-2"],
            rank=0.9,
            period="2024-Q1",
            modularity=0.75,
            entities=[{"name": "Apple", "type": "Organization"}],
            report={"summary": "Tech industry leaders"},
        )
        assert response.id == "comm-123"
        assert len(response.children_ids) == 2
        assert len(response.entities) == 1
        assert response.report is not None

    def test_community_list_response_model(self) -> None:
        """Test CommunityListResponse model."""
        from api.endpoints.communities import CommunityListResponse, CommunityResponse

        communities = [
            CommunityResponse(
                id="c1",
                title="C1",
                level=1,
                entity_count=10,
                parent_id=None,
                period="2024-Q1",
            ),
        ]
        response = CommunityListResponse(communities=communities, total=1, level=1)
        assert response.total == 1
        assert response.level == 1
        assert len(response.communities) == 1


class TestCommunitiesRouter:
    """Tests for communities router configuration."""

    def test_router_prefix(self) -> None:
        """Test router has correct prefix."""
        from api.endpoints.communities import router

        assert router.prefix == "/admin/communities"

    def test_router_tags(self) -> None:
        """Test router has correct tags."""
        from api.endpoints.communities import router

        assert "admin" in router.tags
        assert "communities" in router.tags

    def test_graph_router_prefix(self) -> None:
        """Test graph router has correct prefix."""
        from api.endpoints.communities import graph_router

        assert graph_router.prefix == "/graph/communities"


class TestCommunitiesEndpoints:
    """Tests for communities endpoint functions."""

    @pytest.mark.asyncio
    async def test_rebuild_communities_success(self) -> None:
        """Test POST /admin/communities/rebuild starts rebuild."""
        from api.endpoints.communities import RebuildRequest, rebuild_communities

        mock_pool = AsyncMock()

        with patch("api.endpoints.communities.CommunityDetector") as mock_detector_class:
            mock_detector = AsyncMock()
            mock_detector.rebuild_communities = AsyncMock(
                return_value=MagicMock(
                    total_communities=100,
                    total_entities=500,
                    levels=3,
                    modularity=0.85,
                    orphan_count=5,
                    execution_time_ms=1500.0,
                )
            )
            mock_detector_class.return_value = mock_detector

            request = RebuildRequest()
            result = await rebuild_communities(
                request=request,
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.status == "completed"
        assert result.data.communities_created == 100

    @pytest.mark.asyncio
    async def test_generate_all_reports_success(self) -> None:
        """Test POST /admin/communities/reports/generate generates reports."""
        from api.endpoints.communities import generate_all_reports

        mock_pool = AsyncMock()
        mock_llm = AsyncMock()

        with patch("api.endpoints.communities.CommunityReportGenerator") as mock_gen_class:
            mock_gen = AsyncMock()
            mock_gen.generate_all_reports = AsyncMock(
                return_value={"total": 10, "success": 8, "failed": 2, "failed_ids": []}
            )
            mock_gen_class.return_value = mock_gen

            result = await generate_all_reports(
                level=None,
                regenerate_stale=True,
                _="test-key",
                pool=mock_pool,
                llm=mock_llm,
            )

        assert result.data.total == 10
        assert result.data.success == 8

    @pytest.mark.asyncio
    async def test_list_communities_success(self) -> None:
        """Test GET /graph/communities returns communities list."""
        from api.endpoints.communities import list_communities

        mock_pool = AsyncMock()

        with patch("api.endpoints.communities.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_communities = AsyncMock(
                return_value=[
                    MagicMock(
                        id="c1",
                        title="Community 1",
                        level=1,
                        entity_count=10,
                        parent_id=None,
                        rank=0.9,
                        period="2024-Q1",
                    )
                ]
            )
            mock_repo.count_communities = AsyncMock(return_value=1)
            mock_repo.get_report = AsyncMock(return_value=None)
            mock_repo_class.return_value = mock_repo

            result = await list_communities(
                level=None,
                limit=20,
                offset=0,
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.total == 1
        assert len(result.data.communities) == 1

    @pytest.mark.asyncio
    async def test_get_community_success(self) -> None:
        """Test GET /graph/communities/{id} returns community details."""
        from api.endpoints.communities import get_community

        mock_pool = AsyncMock()

        # Mock Neo4j session for queries
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        # Mock pool.execute_query
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"name": "Apple", "type": "Organization"}],  # entities
                [{"id": "child-1"}],  # children
            ]
        )

        with patch("api.endpoints.communities.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.get_community = AsyncMock(
                return_value=MagicMock(
                    id="comm-123",
                    title="Tech Companies",
                    level=1,
                    entity_count=10,
                    parent_id=None,
                    rank=0.9,
                    period="2024-Q1",
                    modularity=0.75,
                )
            )
            mock_repo.get_report = AsyncMock(return_value=None)
            mock_repo_class.return_value = mock_repo

            result = await get_community(
                community_id="comm-123",
                _="test-key",
                pool=mock_pool,
            )

        assert result.data.id == "comm-123"
        assert result.data.title == "Tech Companies"


class TestCommunityEndpointsRoutes:
    """Tests for community endpoint routes."""

    def test_router_has_rebuild_route(self) -> None:
        """Test router has rebuild endpoint."""
        from api.endpoints.communities import router

        routes = [route.path for route in router.routes]
        assert "/admin/communities/rebuild" in routes

    def test_router_has_reports_generate_route(self) -> None:
        """Test router has reports generate endpoint."""
        from api.endpoints.communities import router

        routes = [route.path for route in router.routes]
        assert "/admin/communities/reports/generate" in routes

    def test_graph_router_has_list_route(self) -> None:
        """Test graph router has list endpoint."""
        from api.endpoints.communities import graph_router

        routes = [route.path for route in graph_router.routes]
        assert "/graph/communities" in routes

    def test_graph_router_has_detail_route(self) -> None:
        """Test graph router has detail endpoint."""
        from api.endpoints.communities import graph_router

        routes = [route.path for route in graph_router.routes]
        assert "/graph/communities/{community_id}" in routes
