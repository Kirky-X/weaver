# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for article endpoints.

Contract (src/api/endpoints/content/articles.py):
- GET /articles: page/page_size bounds (1-100), category is a Chinese enum,
  invalid category → 422, sort_by whitelist silently falls back
- GET /articles/{id}: 400 non-UUID (code 10001), 404 code=30001 (not found)
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call


@pytest.mark.e2e
class TestListArticles:
    """GET /api/v1/articles."""

    def test_list_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_list_payload(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_default",
            headers=auth_headers,
        )
        data = body["data"]
        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in data, f"pagination key {key} missing"
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total"] >= len(data["items"])

    def test_list_page_size_cap(self, client: TestClient, recorder, auth_headers):
        # 100 is the cap → accepted; 101 → 422
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_page_size_100",
            headers=auth_headers,
            params={"page_size": "100"},
        )
        assert body["data"]["page_size"] == 100
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_page_size_101_expect_422",
            headers=auth_headers,
            params={"page_size": "101"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_list_invalid_category(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_invalid_category_expect_422",
            headers=auth_headers,
            params={"category": "not-a-category"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        # Error message must enumerate the legal categories
        assert "科技" in body["message"]

    def test_list_valid_category_filter(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_category_tech",
            headers=auth_headers,
            params={"category": "科技"},
        )
        for item in body["data"]["items"]:
            assert item.get("category") == "科技"

    def test_list_min_score_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_min_score_1_5_expect_422",
            headers=auth_headers,
            params={"min_score": "1.5"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_min_score_valid",
            headers=auth_headers,
            params={"min_score": "0.5"},
        )
        assert "items" in body["data"]

    def test_list_sort_params(self, client: TestClient, recorder, auth_headers):
        # Whitelisted sort column → 200
        for sort_by in ("publish_time", "score", "credibility_score", "created_at"):
            body = api_call(
                client,
                recorder,
                "GET",
                "/api/v1/articles",
                "articles",
                f"list_sort_{sort_by}",
                headers=auth_headers,
                params={"sort_by": sort_by, "sort_order": "asc"},
            )
            assert "items" in body["data"]
        # Non-whitelisted sort_by silently falls back (documented behavior)
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_sort_unknown_falls_back",
            headers=auth_headers,
            params={"sort_by": "malicious_column"},
        )
        assert "items" in body["data"]

    def test_list_pagination_math(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles",
            "articles",
            "list_page2_size3",
            headers=auth_headers,
            params={"page": "2", "page_size": "3"},
        )
        data = body["data"]
        assert data["page"] == 2
        assert data["page_size"] == 3
        assert len(data["items"]) <= 3
        assert data["total_pages"] == (data["total"] + 2) // 3


@pytest.mark.e2e
class TestArticleDetail:
    """GET /api/v1/articles/{article_id}."""

    def test_detail_invalid_uuid(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/articles/not-a-uuid",
            "articles",
            "detail_invalid_uuid_expect_400",
            headers=auth_headers,
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        assert "Invalid article ID" in body["message"]

    def test_detail_not_found(self, client: TestClient, recorder, auth_headers):
        missing = str(uuid.uuid4())
        body = api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/articles/{missing}",
            "articles",
            "detail_not_found_expect_404",
            headers=auth_headers,
            expect_status=404,
            expect_code=30001,
            expect_data=False,
        )
        assert missing in body["message"]
