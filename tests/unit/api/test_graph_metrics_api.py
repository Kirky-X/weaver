# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for graph metrics API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGraphMetricsModels:
    """Tests for graph metrics response models."""

    def test_health_summary_response_model(self) -> None:
        """Test HealthSummaryResponse model."""
        from api.endpoints.graph_metrics import HealthSummaryResponse

        response = HealthSummaryResponse(
            health_score=85.0,
            status="healthy",
            entity_count=1000,
            relationship_count=5000,
            orphan_ratio=0.05,
            connectedness=0.95,
            average_degree=5.0,
            recommendations=["Good graph health"],
        )
        assert response.health_score == 85.0
        assert response.status == "healthy"
        assert response.entity_count == 1000

    def test_graph_metrics_response_model(self) -> None:
        """Test GraphMetricsResponse model."""
        from api.endpoints.graph_metrics import GraphMetricsResponse

        response = GraphMetricsResponse(
            total_entities=1000,
            total_articles=500,
            total_relationships=5000,
            total_mentions=3000,
            connected_components=10,
            largest_component_size=950,
            average_degree=5.0,
            modularity_score=0.75,
            orphan_entities=50,
            high_degree_entities=[{"name": "Apple", "degree": 100}],
            entity_type_distribution={"Organization": 500, "Person": 500},
            relationship_type_distribution={"RELATED_TO": 5000},
            computed_at="2024-01-01T00:00:00",
        )
        assert response.total_entities == 1000
        assert response.total_articles == 500
        assert response.modularity_score == 0.75

    def test_community_metrics_response_model(self) -> None:
        """Test CommunityMetricsResponse model."""
        from api.endpoints.graph_metrics import CommunityMetricsResponse

        response = CommunityMetricsResponse(
            total_communities=100,
            total_reports=80,
            levels=3,
            average_entity_count=10.0,
            average_rank=0.85,
            modularity_score=0.75,
            level_distribution=[{"level": 1, "count": 50}],
            top_communities=[{"id": "c1", "title": "Tech", "level": 1, "entity_count": 25}],
            health_score=80.0,
            health_status="healthy",
        )
        assert response.total_communities == 100
        assert response.health_score == 80.0

    def test_community_health_response_model(self) -> None:
        """Test CommunityHealthResponse model."""
        from api.endpoints.graph_metrics import CommunityHealthResponse

        response = CommunityHealthResponse(
            score=85.0,
            status="healthy",
            issues=[],
            recommendations=["Continue monitoring"],
            modularity=0.75,
            coverage=0.95,
            report_coverage=0.80,
        )
        assert response.score == 85.0
        assert response.status == "healthy"


class TestGraphMetricsRouter:
    """Tests for graph metrics router configuration."""

    def test_router_prefix(self) -> None:
        """Test router has correct prefix."""
        from api.endpoints.graph_metrics import router

        assert router.prefix == "/graph/metrics"

    def test_router_tags(self) -> None:
        """Test router has correct tags."""
        from api.endpoints.graph_metrics import router

        assert "graph-metrics" in router.tags


class TestGraphMetricsEndpoint:
    """Tests for graph metrics endpoint."""

    @pytest.mark.asyncio
    async def test_get_graph_metrics_health_view(self) -> None:
        """Test health view returns health summary."""
        from api.endpoints.graph_metrics import get_graph_metrics

        mock_neo4j = AsyncMock()

        with patch("api.endpoints.graph_metrics.GraphQualityMetrics") as mock_metrics_class:
            mock_metrics = AsyncMock()
            mock_metrics.get_health_summary = AsyncMock(
                return_value={
                    "health_score": 85.0,
                    "status": "healthy",
                    "entity_count": 1000,
                    "relationship_count": 5000,
                    "orphan_ratio": 0.05,
                    "connectedness": 0.95,
                    "average_degree": 5.0,
                    "recommendations": ["Good health"],
                }
            )
            mock_metrics_class.return_value = mock_metrics

            result = await get_graph_metrics(
                view="health", include=None, _="test-key", neo4j=mock_neo4j
            )

        assert result.data.health_score == 85.0
        assert result.data.status == "healthy"

    @pytest.mark.asyncio
    async def test_get_graph_metrics_full_view(self) -> None:
        """Test full view returns complete metrics."""
        from api.endpoints.graph_metrics import get_graph_metrics

        mock_neo4j = AsyncMock()

        with patch("api.endpoints.graph_metrics.get_redis_client", return_value=None):
            with patch("api.endpoints.graph_metrics.GraphQualityMetrics") as mock_metrics_class:
                from datetime import UTC, datetime

                mock_metrics = AsyncMock()
                mock_result = MagicMock()
                mock_result.total_entities = 1000
                mock_result.total_articles = 500
                mock_result.total_relationships = 5000
                mock_result.total_mentions = 3000
                mock_result.connected_components = 10
                mock_result.largest_component_size = 950
                mock_result.average_degree = 5.0
                mock_result.modularity_score = 0.75
                mock_result.orphan_entities = 50
                mock_result.high_degree_entities = []
                mock_result.entity_type_distribution = {}
                mock_result.relationship_type_distribution = {}
                mock_result.computed_at = datetime.now(UTC)
                mock_metrics.calculate_all_metrics = AsyncMock(return_value=mock_result)
                mock_metrics_class.return_value = mock_metrics

                result = await get_graph_metrics(
                    view="full", include=None, _="test-key", neo4j=mock_neo4j
                )

        assert result.data.total_entities == 1000
        assert result.data.total_articles == 500

    @pytest.mark.asyncio
    async def test_get_graph_metrics_community_view(self) -> None:
        """Test community view returns community metrics."""
        from api.endpoints.graph_metrics import get_graph_metrics

        mock_neo4j = AsyncMock()

        with patch("modules.knowledge.graph.community_repo.Neo4jCommunityRepo") as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.count_communities = AsyncMock(return_value=100)
            mock_repo.get_community_metrics = AsyncMock(
                return_value={
                    "average_entity_count": 10.0,
                    "average_rank": 0.85,
                    "average_modularity": 0.75,
                    "report_count": 80,
                }
            )
            mock_repo.get_level_distribution = AsyncMock(return_value=[{"level": 1, "count": 50}])
            mock_repo.list_communities = AsyncMock(return_value=[])
            mock_repo_class.return_value = mock_repo

            result = await get_graph_metrics(
                view="community", include=None, _="test-key", neo4j=mock_neo4j
            )

        assert result.data.total_communities == 100
        assert result.data.total_reports == 80

    @pytest.mark.asyncio
    async def test_get_graph_metrics_invalid_view(self) -> None:
        """Test invalid view raises error."""
        from fastapi import HTTPException

        from api.endpoints.graph_metrics import get_graph_metrics

        mock_neo4j = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_graph_metrics(view="invalid", include=None, _="test-key", neo4j=mock_neo4j)

        assert exc_info.value.status_code == 400
