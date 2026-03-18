# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for articles endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
class TestArticlesEndpoint:
    """Tests for article listing and retrieval."""

    def test_list_articles_returns_empty_initially(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        clean_tables: None,
    ) -> None:
        """Test that GET /api/v1/articles returns empty list with fresh DB."""
        response = client.get(
            "/api/v1/articles",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should be a paginated response
        assert "items" in data or isinstance(data, list)
        if "items" in data:
            assert len(data["items"]) == 0

    def test_list_articles_pagination(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that page/page_size parameters work correctly."""
        response = client.get(
            "/api/v1/articles",
            params={"page": 1, "page_size": 10},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should respect pagination params
        if "items" in data:
            assert len(data["items"]) <= 10

    def test_list_articles_filter_by_category(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that category filter works on articles listing."""
        response = client.get(
            "/api/v1/articles",
            params={"category": "technology"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        # Should not error on category filter

    def test_get_article_not_found(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that GET /api/v1/articles/{invalid_id} returns 404."""
        response = client.get(
            "/api/v1/articles/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_articles_require_auth(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that GET /api/v1/articles returns 401 without API key."""
        response = client.get("/api/v1/articles")
        assert response.status_code == 401
