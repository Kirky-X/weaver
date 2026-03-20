# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for sources CRUD endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
class TestSourcesCRUD:
    """Tests for source CRUD operations."""

    def test_create_source_returns_201(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test that POST /api/v1/sources creates a source and returns 201."""
        response = client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Test Source",
                "url": "https://example.com/feed.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == unique_source_id
        assert data["name"] == "Test Source"
        assert data["enabled"] is True

    def test_list_sources_returns_created(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test that GET /api/v1/sources includes the created source."""
        # Create a source first
        client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "List Test Source",
                "url": "https://example.com/list-test.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 60,
            },
            headers=auth_headers,
        )

        # List sources
        response = client.get(
            "/api/v1/sources",
            params={"enabled_only": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        source_ids = [s["id"] for s in data]
        assert unique_source_id in source_ids

    def test_get_source_returns_details(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test that GET /api/v1/sources/{id} returns correct data."""
        # Create a source
        client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Get Test Source",
                "url": "https://example.com/get-test.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )

        # Get the source
        response = client.get(
            f"/api/v1/sources/{unique_source_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == unique_source_id
        assert data["name"] == "Get Test Source"
        assert data["url"] == "https://example.com/get-test.xml"

    def test_update_source_returns_modified(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test that PUT /api/v1/sources/{id} updates fields."""
        # Create a source
        client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Original Name",
                "url": "https://example.com/original.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )

        # Update the source
        response = client.put(
            f"/api/v1/sources/{unique_source_id}",
            json={
                "name": "Updated Name",
                "enabled": False,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["enabled"] is False
        # Original fields should be preserved
        assert data["url"] == "https://example.com/original.xml"

    def test_delete_source_returns_204(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test that DELETE /api/v1/sources/{id} removes source and returns 204."""
        # Create a source
        client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "Delete Test Source",
                "url": "https://example.com/delete-test.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )

        # Delete the source
        response = client.delete(
            f"/api/v1/sources/{unique_source_id}",
            headers=auth_headers,
        )
        assert response.status_code == 204

    def test_get_source_after_delete_returns_404(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        unique_source_id: str,
    ) -> None:
        """Test that GET /api/v1/sources/{id} returns 404 after deletion."""
        # Create a source
        client.post(
            "/api/v1/sources",
            json={
                "id": unique_source_id,
                "name": "404 Test Source",
                "url": "https://example.com/404-test.xml",
                "source_type": "rss",
                "enabled": True,
                "interval_minutes": 30,
            },
            headers=auth_headers,
        )

        # Delete the source
        client.delete(
            f"/api/v1/sources/{unique_source_id}",
            headers=auth_headers,
        )

        # Try to get the deleted source
        response = client.get(
            f"/api/v1/sources/{unique_source_id}",
            headers=auth_headers,
        )
        assert response.status_code == 404
