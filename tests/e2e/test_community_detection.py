# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for community detection workflow.

Tests the complete workflow of:
1. Community detection trigger via API
2. Community report generation
3. Community retrieval via API
4. Global search using communities
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _patch_search_deps():
    """Create patch context for all search dependencies used in community search tests."""
    mock_llm = MagicMock()
    mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024])

    mock_local_engine = MagicMock()
    mock_global_engine = MagicMock()
    mock_global_engine._pool = MagicMock()
    mock_global_engine._llm = MagicMock()
    mock_hybrid_engine = MagicMock()
    mock_vector_repo = MagicMock()

    patches = [
        patch("api.endpoints._deps.Endpoints.get_llm", return_value=mock_llm),
        patch("api.endpoints._deps.Endpoints.get_local_engine", return_value=mock_local_engine),
        patch("api.endpoints._deps.Endpoints.get_global_engine", return_value=mock_global_engine),
        patch("api.endpoints._deps.Endpoints.get_hybrid_engine", return_value=mock_hybrid_engine),
        patch("api.endpoints._deps.Endpoints.get_vector_repo", return_value=mock_vector_repo),
    ]
    return patches


@pytest.mark.e2e
class TestCommunityDetectionWorkflow:
    """Tests for community detection end-to-end workflow."""

    def test_community_rebuild_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test complete community rebuild workflow: Trigger -> status check."""
        # The rebuild endpoint creates a CommunityDetector internally,
        # so we mock the class itself.
        with patch(
            "modules.graph_store.community_detector.CommunityDetector.rebuild_communities",
            new_callable=AsyncMock,
        ) as mock_rebuild:
            from modules.graph_store.community_models import CommunityDetectionResult

            mock_rebuild.return_value = CommunityDetectionResult(
                communities=[],
                total_entities=100,
                total_communities=5,
                modularity=0.45,
                levels=2,
                orphan_count=0,
                execution_time_ms=1500.0,
            )

            rebuild_response = client.post(
                "/api/v1/admin/communities/rebuild",
                headers=auth_headers,
            )

            # Should succeed or return 202 for async processing
            assert rebuild_response.status_code in (200, 202)

    def test_community_list_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test listing communities after detection."""
        # The endpoint creates Neo4jCommunityRepo(pool) internally,
        # so we mock the class methods directly.
        with (
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.list_communities",
                new_callable=AsyncMock,
            ) as mock_list,
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.count_communities",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_count,
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.get_report",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            from modules.graph_store.community_models import Community

            mock_list.return_value = [
                Community(
                    id="comm-1",
                    title="AI Research",
                    level=0,
                    entity_count=10,
                    rank=8.5,
                ),
                Community(
                    id="comm-2",
                    title="Machine Learning",
                    level=0,
                    entity_count=8,
                    rank=7.2,
                ),
            ]

            list_response = client.get(
                "/api/v1/graph/communities",
                headers=auth_headers,
            )

            assert list_response.status_code == 200
            data = list_response.json()
            # Response is wrapped in APIResponse: {"code": 0, "data": {...}}
            assert "data" in data
            community_data = data["data"]
            assert "communities" in community_data
            assert len(community_data["communities"]) >= 1

    def test_community_get_detail_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting individual community detail."""
        from modules.graph_store.community_models import Community

        mock_community = Community(
            id="comm-1",
            title="AI Research Community",
            level=0,
            entity_count=15,
            rank=8.5,
        )

        with (
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.get_community",
                new_callable=AsyncMock,
                return_value=mock_community,
            ),
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.get_report",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "core.db.neo4j.Neo4jPool.execute_query",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            get_response = client.get(
                "/api/v1/graph/communities/comm-1",
                headers=auth_headers,
            )

            assert get_response.status_code == 200
            data = get_response.json()
            # Response is wrapped in APIResponse
            assert "data" in data
            assert data["data"]["id"] == "comm-1"
            assert data["data"]["title"] == "AI Research Community"

    def test_community_not_found(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting non-existent community returns 404."""
        with patch(
            "modules.graph_store.community_repo.Neo4jCommunityRepo.get_community",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = client.get(
                "/api/v1/graph/communities/non-existent",
                headers=auth_headers,
            )

            assert response.status_code == 404

    def test_report_regenerate_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test regenerating community report."""
        with patch(
            "modules.graph_store.community_report_generator.CommunityReportGenerator.regenerate_report",
            new_callable=AsyncMock,
        ) as mock_regenerate:
            from modules.graph_store.community_report_generator import ReportGenerationResult

            mock_regenerate.return_value = ReportGenerationResult(
                community_id="comm-1",
                success=True,
                report_id="report-new",
            )

            response = client.post(
                "/api/v1/admin/communities/comm-1/report/regenerate",
                headers=auth_headers,
            )

            assert response.status_code in (200, 202)


@pytest.mark.e2e
class TestCommunityMetricsWorkflow:
    """Tests for community metrics API workflow."""

    def test_community_metrics_endpoint(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting community-level metrics."""
        with (
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.count_communities",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.get_community_metrics",
                new_callable=AsyncMock,
            ) as mock_metrics,
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.get_level_distribution",
                new_callable=AsyncMock,
                return_value=[{"level": 0, "count": 5}, {"level": 1, "count": 5}],
            ),
            patch(
                "modules.graph_store.community_repo.Neo4jCommunityRepo.list_communities",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_metrics.return_value = {
                "average_modularity": 0.42,
                "report_count": 5,
                "average_entity_count": 15.0,
                "average_rank": 7.5,
            }

            response = client.get(
                "/api/v1/graph/metrics",
                params={"view": "community"},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            # Response wrapped in APIResponse
            assert "data" in data
            assert "total_communities" in data["data"]
            assert "health_score" in data["data"]


@pytest.mark.e2e
class TestCommunitySearchIntegration:
    """Tests for search integration with communities."""

    def test_drift_search_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test DRIFT search end-to-end."""
        with patch(
            "modules.search.engines.drift_search.DRIFTSearchEngine.search",
            new_callable=AsyncMock,
        ) as mock_search:
            from modules.search.engines.drift_search import DriftHierarchy, DriftResult

            mock_search.return_value = DriftResult(
                query="What are the latest AI breakthroughs?",
                answer="Recent AI breakthroughs include...",
                confidence=0.82,
                hierarchy=DriftHierarchy(
                    primer={"answer": "Initial answer from community reports"},
                    follow_ups=[{"question": "What about GPT-4?", "answer": "GPT-4 is..."}],
                ),
                primer_communities=3,
                follow_up_iterations=2,
                total_llm_calls=5,
            )

            patches = _patch_search_deps()
            for p in patches:
                p.start()
            try:
                response = client.post(
                    "/api/v1/search/drift",
                    json={"query": "What are the latest AI breakthroughs?"},
                    headers=auth_headers,
                )
            finally:
                for p in patches:
                    p.stop()

            assert response.status_code == 200
            data = response.json()
            # Response is wrapped in APIResponse: {"code": 0, "data": {...}}
            assert "data" in data
            assert "answer" in data["data"]
            assert "hierarchy" in data["data"]


@pytest.mark.e2e
class TestCommunityDetectionScheduler:
    """Tests for community detection scheduler integration.

    Note: The scheduler module uses SchedulerJobs class (not CommunityDetectionScheduler).
    These tests verify the admin community endpoints work correctly.
    """

    def test_force_rebuild_endpoint(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test forcing a community rebuild."""
        with patch(
            "modules.graph_store.community_detector.CommunityDetector.rebuild_communities",
            new_callable=AsyncMock,
        ) as mock_rebuild:
            from modules.graph_store.community_models import CommunityDetectionResult

            mock_rebuild.return_value = CommunityDetectionResult(
                communities=[],
                total_entities=500,
                total_communities=12,
                modularity=0.48,
                levels=3,
                orphan_count=5,
                execution_time_ms=2000.0,
            )

            response = client.post(
                "/api/v1/admin/communities/rebuild",
                json={"force": True},
                headers=auth_headers,
            )

            assert response.status_code in (200, 202)
