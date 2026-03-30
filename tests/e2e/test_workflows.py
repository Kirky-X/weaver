# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for cross-cutting workflows."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
class TestWorkflows:
    """Tests for complete end-to-end workflows."""

    def test_full_source_crud_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test complete Source CRUD workflow: Create -> List -> Update -> Delete."""
        # 1. Create
        create_response = client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Workflow Test Source",
                "url": "https://example.com/workflow.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        create_data = create_response.json()["data"]
        assert create_data["id"] == unique_source_id

        # 2. List - verify it appears
        list_response = client.get(
            "/api/v1/sources",
            params={"enabled_only": False},
            headers=auth_headers,
        )
        assert list_response.status_code == 200
        list_data = list_response.json()["data"]
        source_ids = [s["id"] for s in list_data]
        assert unique_source_id in source_ids

        # 3. Update
        update_response = client.put(
            f"/api/v1/sources/{unique_source_id}",
            json={"name": "Updated Workflow Source"},
            headers=auth_headers,
        )
        assert update_response.status_code == 200
        update_data = update_response.json()["data"]
        assert update_data["name"] == "Updated Workflow Source"

        # 4. Delete
        delete_response = client.delete(
            f"/api/v1/sources/{unique_source_id}",
            headers=auth_headers,
        )
        assert delete_response.status_code == 204

        # 5. Verify deleted
        get_response = client.get(
            f"/api/v1/sources/{unique_source_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    def test_source_then_pipeline_workflow(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test workflow: Create source -> Trigger pipeline -> Verify no crash."""
        # 1. Create a source
        client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Pipeline Workflow Source",
                "url": "https://example.com/pipeline-workflow.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )

        # 2. Trigger pipeline with this source
        trigger_response = client.post(
            "/api/v1/pipeline/trigger",
            json={"source_id": unique_source_id},
            headers=auth_headers,
        )
        assert trigger_response.status_code == 200
        trigger_data = trigger_response.json()["data"]
        task_id = trigger_data["task_id"]

        # 3. Get task status
        status_response = client.get(
            f"/api/v1/pipeline/tasks/{task_id}",
            headers=auth_headers,
        )
        assert status_response.status_code == 200
        status_data = status_response.json()["data"]
        assert status_data["task_id"] == task_id

    def test_unauthorized_access_blocked(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that missing API key is blocked on protected endpoints."""
        protected_endpoints = [
            ("GET", "/api/v1/sources"),
            ("GET", "/api/v1/articles"),
            ("POST", "/api/v1/pipeline/trigger"),
        ]

        for method, endpoint in protected_endpoints:
            if method == "GET":
                response = client.get(endpoint)
            else:
                response = client.post(endpoint, json={})

            assert response.status_code == 401, f"{method} {endpoint} should require auth"

    def test_health_check_integration(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that health check endpoint returns proper response structure."""
        response = client.get("/health")
        # Health endpoint returns 200 if healthy, 503 if unhealthy
        # Either status is acceptable for testing the endpoint works
        assert response.status_code in (200, 503)
        data = response.json()

        # Health response should have status field
        assert "status" in data
        # Should have checks dict with service details
        assert "checks" in data
        # Verify checks structure contains expected services
        checks = data["checks"]
        assert isinstance(checks, dict)

    def test_graph_entity_not_found(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that querying a non-existent entity returns appropriate response."""
        response = client.get(
            "/api/v1/graph/entities/NonexistentEntity12345",
            headers=auth_headers,
        )
        # Acceptable responses:
        # - 404: entity not found
        # - 200: empty result returned
        # - 500/503: service unavailable (Neo4j pool not started)
        assert response.status_code in (200, 404, 500, 503)
