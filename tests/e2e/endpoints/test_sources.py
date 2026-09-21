# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for source management: CRUD + validation + SSRF guards.

Contract (src/api/endpoints/content/sources.py):
- POST returns 201 (not 200); DELETE returns 204 with no body
- Errors: 404 code=40001 (source not found), 409 code=40002 (duplicate id),
  422 for validation/feed failures, 403 for SSRF violations
- URL validation rejects localhost/127.0.0.1/metadata hosts and enforces RFC 1035
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call

# Stable public RSS feed for the full create→read→update→delete path.
# Skipped (explicitly) when the network is unavailable.
PUBLIC_FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"


def _create_payload(source_id: str, url: str = PUBLIC_FEED_URL) -> dict:
    return {
        "id": source_id,
        "name": "E2E Source",
        "url": url,
        "source_type": "rss",
        "enabled": True,
    }


@pytest.mark.e2e
class TestListSources:
    """GET /api/v1/sources."""

    def test_list_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "sources",
            "list_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_list_empty(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "sources",
            "list_default",
            headers=auth_headers,
        )
        data = body["data"]
        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in data, f"pagination key {key} missing"
        assert data["page"] == 1
        assert data["page_size"] == 50
        assert data["total"] == len(data["items"])
        assert data["total_pages"] == (data["total"] + data["page_size"] - 1) // data["page_size"]

    def test_list_pagination_bounds(self, client: TestClient, recorder, auth_headers):
        # page_size above the 200 cap → 422
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "sources",
            "list_page_size_201_expect_422",
            headers=auth_headers,
            params={"page_size": "201"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        # page below 1 → 422
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "sources",
            "list_page_0_expect_422",
            headers=auth_headers,
            params={"page": "0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_list_enabled_only_filter(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "sources",
            "list_enabled_only_false",
            headers=auth_headers,
            params={"enabled_only": "false", "page_size": "10"},
        )
        assert body["data"]["page_size"] == 10


@pytest.mark.e2e
class TestSourceDetail:
    """GET /api/v1/sources/{source_id}."""

    def test_get_not_found(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources/no-such-source",
            "sources",
            "get_not_found_expect_404",
            headers=auth_headers,
            expect_status=404,
            expect_code=40001,
            expect_data=False,
        )
        assert "no-such-source" in body["message"]


@pytest.mark.e2e
class TestCreateSourceValidation:
    """POST /api/v1/sources — validation-only paths (no network needed)."""

    def test_create_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/sources",
            "sources",
            "create_no_auth_expect_401",
            json_data=_create_payload("anon"),
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_create_missing_required_fields(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/sources",
            "sources",
            "create_missing_fields_expect_422",
            headers=admin_headers,
            json_data={"id": "incomplete"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_create_empty_id_rejected(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/sources",
            "sources",
            "create_empty_id_expect_422",
            headers=admin_headers,
            json_data=_create_payload(""),
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_create_dangerous_host_rejected(self, client: TestClient, recorder, admin_headers):
        for host in (
            "http://localhost/rss",
            "http://127.0.0.1/rss",
            "http://169.254.169.254/latest/meta-data/",
        ):
            api_call(
                client,
                recorder,
                "POST",
                "/api/v1/sources",
                "sources",
                f"create_dangerous_host_{host.split('//')[1].split('/')[0]}_expect_422",
                headers=admin_headers,
                json_data=_create_payload("ssrf-probe", url=host),
                expect_status=422,
                expect_code=10001,
                expect_data=False,
            )

    def test_create_non_http_scheme_rejected(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/sources",
            "sources",
            "create_ftp_scheme_expect_422",
            headers=admin_headers,
            json_data=_create_payload("ftp-src", url="ftp://example.com/rss"),
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("interval_minutes", 4),  # below ge=5
            ("interval_minutes", 1441),  # above le=1440
            ("per_host_concurrency", 0),  # below ge=1
            ("per_host_concurrency", 11),  # above le=10
            ("credibility", 1.5),  # above le=1.0
            ("tier", 4),  # above le=3
        ],
    )
    def test_create_range_violations(
        self, client: TestClient, recorder, admin_headers, field: str, value
    ):
        payload = _create_payload(f"range-{field}-{value}")
        payload[field] = value
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/sources",
            "sources",
            f"create_range_{field}_{value}_expect_422",
            headers=admin_headers,
            json_data=payload,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestSourceLifecycle:
    """Full create→get→update→delete path against a public feed."""

    @pytest.fixture()
    def created_source(self, client: TestClient, recorder, admin_headers, unique_id):
        """Create a source via the API; skip the lifecycle tests offline."""
        source_id = f"e2e-lifecycle-{unique_id}"
        response = client.post(
            "/api/v1/sources",
            headers=admin_headers,
            json=_create_payload(source_id),
        )
        if response.status_code in (403, 422):
            # 403: SSRF/DNS check failed (offline); 422: feed validation failed
            pytest.skip(
                f"Public feed unreachable (offline environment): "
                f"{response.status_code} {response.text[:150]}"
            )
        assert response.status_code == 201, response.text[:300]
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["id"] == source_id
        assert data["name"] == "E2E Source"
        assert data["enabled"] is True
        return source_id

    def test_full_lifecycle(
        self, client: TestClient, recorder, admin_headers, auth_headers, created_source
    ):
        source_id = created_source
        # Duplicate id → 409 code=40002
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/sources",
            "sources",
            "lifecycle_create_duplicate_expect_409",
            headers=admin_headers,
            json_data=_create_payload(source_id),
            expect_status=409,
            expect_code=40002,
            expect_data=False,
        )
        # GET detail echoes the created record
        body = api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/sources/{source_id}",
            "sources",
            "lifecycle_get_created",
            headers=auth_headers,
        )
        assert body["data"]["id"] == source_id
        # Update (no URL change → no refetch)
        body = api_call(
            client,
            recorder,
            "PUT",
            f"/api/v1/sources/{source_id}",
            "sources",
            "lifecycle_update",
            headers=admin_headers,
            json_data={"name": "E2E Source Updated", "enabled": False},
        )
        assert body["data"]["name"] == "E2E Source Updated"
        assert body["data"]["enabled"] is False
        # Delete → 204 with empty body
        response = client.delete(f"/api/v1/sources/{source_id}", headers=admin_headers)
        assert response.status_code == 204
        assert not response.content
        # GET after delete → 404 code=40001
        api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/sources/{source_id}",
            "sources",
            "lifecycle_get_after_delete_expect_404",
            headers=auth_headers,
            expect_status=404,
            expect_code=40001,
            expect_data=False,
        )

    def test_update_nonexistent(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "PUT",
            "/api/v1/sources/no-such-source",
            "sources",
            "update_not_found_expect_404",
            headers=admin_headers,
            json_data={"name": "ghost"},
            expect_status=404,
            expect_code=40001,
            expect_data=False,
        )

    def test_delete_nonexistent(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "DELETE",
            "/api/v1/sources/no-such-source",
            "sources",
            "delete_not_found_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=40001,
            expect_data=False,
        )
