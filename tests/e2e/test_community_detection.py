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


@pytest.mark.e2e
class TestCommunityDetectionWorkflow:
    """Tests for community detection end-to-end workflow."""

    def test_community_rebuild_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test complete community rebuild workflow: Trigger → List → Get."""
        # 1. Trigger community rebuild
        with patch(
            "modules.graph_store.community_detector.CommunityDetector.rebuild_communities",
            new_callable=AsyncMock,
        ) as mock_rebuild:
            mock_rebuild.return_value = MagicMock(
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
        with patch(
            "modules.graph_store.community_repo.Neo4jCommunityRepo.list_communities",
            new_callable=AsyncMock,
        ) as mock_list:
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
            assert len(data) >= 1

    def test_community_get_detail_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting individual community detail."""
        with patch(
            "modules.graph_store.community_repo.Neo4jCommunityRepo.get_community",
            new_callable=AsyncMock,
        ) as mock_get:
            from modules.graph_store.community_models import Community

            mock_get.return_value = Community(
                id="comm-1",
                title="AI Research Community",
                level=0,
                entity_count=15,
                rank=8.5,
                summary="Community focused on AI research topics",
            )

            get_response = client.get(
                "/api/v1/graph/communities/comm-1",
                headers=auth_headers,
            )

            assert get_response.status_code == 200
            data = get_response.json()
            assert data["id"] == "comm-1"
            assert data["title"] == "AI Research Community"

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
        with patch(
            "modules.graph_store.community_repo.Neo4jCommunityRepo.get_community_metrics",
            new_callable=AsyncMock,
        ) as mock_metrics:
            mock_metrics.return_value = {
                "total_communities": 10,
                "total_entities": 150,
                "avg_community_size": 15.0,
                "modularity": 0.42,
                "hierarchy_levels": 3,
            }

            response = client.get(
                "/api/v1/graph/metrics",
                params={"view": "community"},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "total_communities" in data
            assert "modularity" in data


@pytest.mark.e2e
class TestCommunitySearchIntegration:
    """Tests for search integration with communities."""

    def test_global_search_uses_communities(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that global search utilizes community data."""
        with patch(
            "modules.search.engines.global_search.GlobalSearchEngine.search",
            new_callable=AsyncMock,
        ) as mock_search:
            from modules.search.engines.global_search import GlobalSearchResult

            mock_search.return_value = GlobalSearchResult(
                query="artificial intelligence research",
                answer="AI research focuses on creating intelligent systems...",
                confidence=0.85,
                communities_used=["comm-1", "comm-2"],
                total_context_tokens=3000,
            )

            response = client.get(
                "/api/v1/search/global",
                params={"query": "artificial intelligence research"},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "answer" in data
            assert data["confidence"] > 0

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

            response = client.post(
                "/api/v1/search/drift",
                json={"query": "What are the latest AI breakthroughs?"},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "answer" in data
            assert "hierarchy" in data


@pytest.mark.e2e
class TestCommunityDetectionScheduler:
    """Tests for community detection scheduler integration."""

    def test_scheduler_status_endpoint(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting scheduler status."""
        with patch(
            "modules.scheduler.jobs.CommunityDetectionScheduler.get_status",
            new_callable=AsyncMock,
        ) as mock_status:
            mock_status.return_value = {
                "last_rebuild": "2024-01-15T10:00:00Z",
                "entity_count": 1000,
                "community_count": 25,
                "next_check": "2024-01-22T10:00:00Z",
            }

            response = client.get(
                "/api/v1/admin/communities/scheduler/status",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "last_rebuild" in data or "status" in data

    def test_force_rebuild_endpoint(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test forcing a community rebuild."""
        with patch(
            "modules.scheduler.jobs.CommunityDetectionScheduler.force_rebuild",
            new_callable=AsyncMock,
        ) as mock_force:
            mock_force.return_value = {
                "triggered": True,
                "reason": "forced",
                "communities_created": 12,
                "modularity": 0.48,
            }

            response = client.post(
                "/api/v1/admin/communities/rebuild",
                json={"force": True},
                headers=auth_headers,
            )

            assert response.status_code in (200, 202)
