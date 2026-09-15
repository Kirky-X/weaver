# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""E2E tests for cross-cutting workflows."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Stable public RSS feed; full CRUD workflows are skipped when offline.
PUBLIC_FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"


@pytest.mark.e2e
class TestWorkflows:
    """Tests for complete end-to-end workflows."""

    def test_full_source_crud_workflow(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test complete Source CRUD workflow: Create -> List -> Update -> Delete."""
        # 1. Create (feed validation fetches the URL; skip when offline)
        create_response = client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Workflow Test Source",
                "url": PUBLIC_FEED_URL,
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=admin_headers,
        )
        if create_response.status_code == 422:
            pytest.skip("Public feed unreachable (offline environment)")
        assert create_response.status_code == 201, create_response.text[:300]
        create_data = create_response.json()["data"]
        assert create_data["id"] == unique_source_id

        # 2. List - verify it appears (list returns a paginated envelope)
        list_response = client.get(
            "/api/v1/sources",
            params={"enabled_only": "false"},
            headers=admin_headers,
        )
        assert list_response.status_code == 200
        list_data = list_response.json()["data"]
        source_ids = [s["id"] for s in list_data["items"]]
        assert unique_source_id in source_ids

        # 3. Update
        update_response = client.put(
            f"/api/v1/sources/{unique_source_id}",
            json={"name": "Updated Workflow Source"},
            headers=admin_headers,
        )
        assert update_response.status_code == 200
        update_data = update_response.json()["data"]
        assert update_data["name"] == "Updated Workflow Source"

        # 4. Delete → 204, no body
        delete_response = client.delete(
            f"/api/v1/sources/{unique_source_id}",
            headers=admin_headers,
        )
        assert delete_response.status_code == 204

        # 5. Verify deleted → 404 code 40001
        get_response = client.get(
            f"/api/v1/sources/{unique_source_id}",
            headers=admin_headers,
        )
        assert get_response.status_code == 404
        assert get_response.json()["code"] == 40001

    def test_source_then_pipeline_workflow(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test workflow: Create source -> Trigger pipeline -> Verify task status."""
        # 1. Create a source
        create_response = client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Pipeline Workflow Source",
                "url": PUBLIC_FEED_URL,
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=admin_headers,
        )
        if create_response.status_code == 422:
            pytest.skip("Public feed unreachable (offline environment)")
        assert create_response.status_code == 201, create_response.text[:300]

        # 2. Trigger pipeline with this source
        trigger_response = client.post(
            "/api/v1/pipeline/trigger",
            json={"source_id": unique_source_id},
            headers=admin_headers,
        )
        assert trigger_response.status_code == 200, trigger_response.text[:300]
        trigger_data = trigger_response.json()["data"]
        assert trigger_data["status"] == "queued"
        task_id = trigger_data["task_id"]

        # 3. Get task status
        status_response = client.get(
            f"/api/v1/pipeline/tasks/{task_id}",
            headers=admin_headers,
        )
        assert status_response.status_code == 200
        status_data = status_response.json()["data"]
        assert status_data["task_id"] == task_id

    def test_unauthorized_access_blocked(
        self,
        client: TestClient,
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
            assert response.json()["code"] == 10002

    def test_health_check_integration(
        self,
        client: TestClient,
    ) -> None:
        """Public health probe deliberately omits per-service checks (CWE-200)."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        health_data = data["data"]
        assert "status" in health_data
        assert health_data["status"] in ("healthy", "unhealthy")
        # Error details are intentionally excluded from the public probe
        assert "checks" not in health_data

    def test_graph_entity_not_found(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Unknown entity → 404 with envelope code 10004."""
        response = client.get(
            "/api/v1/graph/entities/NonexistentEntity12345",
            headers=admin_headers,
        )
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == 10004
        assert "NonexistentEntity12345" in body["message"]
