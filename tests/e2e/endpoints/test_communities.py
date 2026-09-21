# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for community management endpoints (/api/v1/admin/communities).

Contract highlights:
- list/health/diagnose/repair work on an empty graph (200 with zeroed data;
  total=0 → status critical, score 0)
- Unknown community_id → 404 ("Community not found")
- repair with invalid repair_types → 400 listing valid types; dry_run only counts
- rebuild requires graph pool AND LLM → 503 in degraded environments
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call, api_call_multi

VALID_REPAIR_TYPES = (
    "empty_community",
    "entity_count_mismatch",
    "missing_report",
    "stale_report",
    "hierarchy_break",
    "low_modularity",
)


@pytest.mark.e2e
class TestCommunitiesAuth:
    """All community endpoints are admin-only."""

    def test_list_regular_key_forbidden(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/communities",
            "communities",
            "communities_list_regular_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )


@pytest.mark.e2e
class TestCommunitiesList:
    """GET /api/v1/admin/communities."""

    def test_list_empty(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/communities",
            "communities",
            "communities_list",
            headers=admin_headers,
        )
        data = body["data"]
        for key in ("communities", "total"):
            assert key in data, f"community list key {key} missing"
        assert isinstance(data["communities"], list)
        assert data["total"] == len(data["communities"])

    def test_list_pagination_bounds(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/communities",
            "communities",
            "communities_list_limit_101_expect_422",
            headers=admin_headers,
            params={"limit": "101"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/communities",
            "communities",
            "communities_list_page_0_expect_422",
            headers=admin_headers,
            params={"page": "0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_list_offset_takes_priority(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/communities",
            "communities",
            "communities_list_offset",
            headers=admin_headers,
            params={"offset": "0", "limit": "5", "page": "3"},
        )
        assert body["data"]["total"] == len(body["data"]["communities"])


@pytest.mark.e2e
class TestCommunityDetail:
    """GET /api/v1/admin/communities/{community_id}."""

    def test_unknown_community(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/communities/no-such-community",
            "communities",
            "community_detail_unknown_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )
        assert "not found" in body["message"].lower()

    def test_regenerate_unknown_community(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/communities/no-such-community/report/regenerate",
            "communities",
            "community_report_regenerate_unknown_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )
        assert "not found" in body["message"].lower()


@pytest.mark.e2e
class TestCommunitiesHealth:
    """GET health, POST diagnose, POST repair."""

    def test_health_overview(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/communities/health",
            "communities",
            "communities_health_overview",
            headers=admin_headers,
        )
        data = body["data"]
        for key in (
            "status",
            "score",
            "total_communities",
            "communities_with_reports",
            "stale_reports",
            "empty_communities",
            "hierarchy_issues",
        ):
            assert key in data
        assert 0 <= data["score"] <= 100
        assert data["status"] in ("healthy", "moderate", "degraded", "critical")

    def test_diagnose(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/communities/health/diagnose",
            "communities",
            "communities_health_diagnose",
            headers=admin_headers,
        )
        data = body["data"]
        for key in ("status", "issues", "metrics", "repair_suggestions"):
            assert key in data, f"diagnose key {key} missing"
        assert isinstance(data["issues"], list)
        for issue in data["issues"]:
            for key in ("issue_type", "severity", "description"):
                assert key in issue, f"issue key {key} missing"

    def test_repair_invalid_type(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/communities/health/repair",
            "communities",
            "communities_repair_invalid_type_expect_400",
            headers=admin_headers,
            json_data={"repair_types": ["bogus_type"]},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        assert "Invalid repair types" in body["message"]
        for valid_type in VALID_REPAIR_TYPES:
            assert valid_type in body["message"]

    def test_repair_dry_run(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/communities/health/repair",
            "communities",
            "communities_repair_dry_run",
            headers=admin_headers,
            json_data={"repair_types": list(VALID_REPAIR_TYPES), "dry_run": True},
        )
        data = body["data"]
        for key in ("repaired", "failed", "duration_ms"):
            assert key in data, f"repair key {key} missing"
        assert isinstance(data["repaired"], dict)
        assert isinstance(data["failed"], dict)


@pytest.mark.e2e
class TestCommunitiesMutations:
    """POST rebuild / reports/generate — LLM-dependent (503 without stack)."""

    def test_rebuild(self, client: TestClient, recorder, admin_headers):
        body = api_call_multi(
            client,
            recorder,
            "POST",
            "/api/v1/admin/communities/rebuild",
            "communities",
            "communities_rebuild",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=admin_headers,
            json_data={"max_cluster_size": 10, "seed": 42},
        )
        if body and body.get("data"):
            data = body["data"]
            assert data["status"] == "completed"
            for key in (
                "communities_created",
                "entities_processed",
                "levels",
                "modularity",
                "execution_time_ms",
            ):
                assert key in data, f"rebuild key {key} missing"

    def test_rebuild_cluster_size_bounds(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/communities/rebuild",
            "communities",
            "communities_rebuild_cluster_0_expect_422",
            headers=admin_headers,
            json_data={"max_cluster_size": 0},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_generate_reports(self, client: TestClient, recorder, admin_headers):
        body = api_call_multi(
            client,
            recorder,
            "POST",
            "/api/v1/admin/communities/reports/generate",
            "communities",
            "communities_generate_reports",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=admin_headers,
        )
        if body and body.get("data"):
            data = body["data"]
            for key in ("total", "success", "failed", "failed_ids"):
                assert key in data, f"report generate key {key} missing"
            assert data["total"] == data["success"] + data["failed"]
