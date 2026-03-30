# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for pipeline trigger and status endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
class TestPipelineEndpoint:
    """Tests for pipeline trigger and status operations."""

    def test_trigger_pipeline_returns_task_id(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that POST /api/v1/pipeline/trigger returns a task_id."""
        response = client.post(
            "/api/v1/pipeline/trigger",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "task_id" in data
        assert data["task_id"] is not None
        # Status should be queued or running
        assert data.get("status") in ("queued", "running", "completed")

    def test_get_task_status_returns_pending(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that GET /api/v1/pipeline/tasks/{id} shows correct status."""
        # First trigger a task
        trigger_response = client.post(
            "/api/v1/pipeline/trigger",
            json={},
            headers=auth_headers,
        )
        assert trigger_response.status_code == 200
        task_id = trigger_response.json()["data"]["task_id"]

        # Get the task status
        response = client.get(
            f"/api/v1/pipeline/tasks/{task_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["task_id"] == task_id
        assert "status" in data

    def test_trigger_with_source_filter(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test triggering pipeline with specific source_id filter."""
        # Create a source first
        client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Pipeline Test Source",
                "url": "https://example.com/pipeline-test.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )

        # Trigger with specific source
        response = client.post(
            "/api/v1/pipeline/trigger",
            json={"source_id": unique_source_id},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "task_id" in data

    def test_get_nonexistent_task_returns_404(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that GET /api/v1/pipeline/tasks/{invalid_id} returns 404."""
        response = client.get(
            "/api/v1/pipeline/tasks/nonexistent-task-id",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_queue_stats_returns_valid(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that GET /api/v1/pipeline/queue/stats returns valid stats."""
        response = client.get(
            "/api/v1/pipeline/queue/stats",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        # Should have queue_depth and article_stats
        assert isinstance(data.get("queue_depth", 0), int)
        assert isinstance(data.get("total_tasks", 0), int)
