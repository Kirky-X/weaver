# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for admin endpoints (api-keys, dedup, authorities, memory,
database monitoring).

Contract highlights:
- All admin endpoints use verify_admin_api_key: no key → 401 (code 10002),
  regular key → 403 (code 10003 "Admin access required...")
- POST /admin/api-keys returns the plaintext key_value exactly once; listing
  never includes key_value; DB-issued keys can call regular endpoints but are
  rejected from admin endpoints; revoked keys fail validation; rotate
  invalidates the old key immediately (no grace period)
- DELETE /admin/api-keys/{id} on an already-revoked key → 409 (not idempotent)
- PATCH /admin/authorities/{host} with an empty body → 400; unknown host → 404
- Database monitoring on DuckDB fallback → 200 with empty/fixed data + message
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call


@pytest.mark.e2e
class TestAdminAuthGate:
    """Admin endpoints reject missing/regular keys with precise codes."""

    @pytest.mark.parametrize(
        "method,path,json_body",
        [
            ("POST", "/api/v1/admin/api-keys", {}),
            ("GET", "/api/v1/admin/api-keys", None),
            ("POST", "/api/v1/admin/articles/deduplicate", None),
            ("GET", "/api/v1/admin/authorities", None),
            ("GET", "/api/v1/admin/memory/diagnostics", None),
            ("GET", "/api/v1/admin/monitoring/database/pool", None),
        ],
    )
    def test_admin_endpoints_require_admin(
        self, client: TestClient, recorder, auth_headers, method, path, json_body
    ):
        kwargs: dict = {
            "headers": auth_headers,
            "expect_status": 403,
            "expect_code": 10003,
            "expect_data": False,
        }
        if json_body is not None:
            kwargs["json_data"] = json_body
        api_call(client, recorder, method, path, "admin", f"auth_gate_{method}_{path}", **kwargs)


@pytest.mark.e2e
class TestApiKeyLifecycle:
    """Full api-key lifecycle: create → use → list → rotate → revoke."""

    def test_create_key_payload(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/api-keys",
            "admin",
            "api_key_create",
            headers=admin_headers,
            json_data={
                "scopes": ["search:read"],
                "rate_limit_per_min": 100,
                "expires_in_days": 30,
                "created_by": "e2e-suite",
            },
        )
        data = body["data"]
        for key in ("key_id", "key_value", "scopes", "rate_limit_per_min", "expires_at"):
            assert key in data, f"api key payload key {key} missing"
        assert data["key_value"].startswith("weaver_")
        assert data["scopes"] == ["search:read"]
        assert data["rate_limit_per_min"] == 100
        # Cleanup so repeated runs don't accumulate test keys
        self._cleanup_key(client, admin_headers, data["key_id"])

    def test_create_key_validation(self, client: TestClient, recorder, admin_headers):
        # rate_limit below ge=10
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/api-keys",
            "admin",
            "api_key_rate_limit_9_expect_422",
            headers=admin_headers,
            json_data={"rate_limit_per_min": 9},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        # expires_in_days above le=365
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/api-keys",
            "admin",
            "api_key_expiry_366_expect_422",
            headers=admin_headers,
            json_data={"expires_in_days": 366},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        # created_by with forbidden characters
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/api-keys",
            "admin",
            "api_key_created_by_injection_expect_422",
            headers=admin_headers,
            json_data={"created_by": "<script>alert(1)</script>"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    @staticmethod
    def _cleanup_key(client: TestClient, admin_headers: dict[str, str], key_id: str) -> None:
        """Best-effort revocation so repeated runs don't accumulate keys."""
        client.delete(f"/api/v1/admin/api-keys/{key_id}", headers=admin_headers)

    def test_full_lifecycle(self, client: TestClient, recorder, admin_headers, auth_headers):
        # 1. Create
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/api-keys",
            "admin",
            "lifecycle_key_create",
            headers=admin_headers,
            json_data={"created_by": "e2e-lifecycle"},
        )
        key_id = body["data"]["key_id"]
        key_value = body["data"]["key_value"]
        issued = {"X-API-Key": key_value}

        # 2. DB-issued key works on regular endpoints
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "admin",
            "lifecycle_key_works_on_regular",
            headers=issued,
        )

        # 3. DB-issued key is rejected from admin endpoints
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/api-keys",
            "admin",
            "lifecycle_key_blocked_from_admin",
            headers=issued,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )

        # 4. Listing shows the key without its value
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/api-keys",
            "admin",
            "lifecycle_key_list",
            headers=admin_headers,
            params={"include_revoked": "true"},
        )
        listed = next(k for k in body["data"] if k["key_id"] == key_id)
        assert "key_value" not in listed
        assert listed["is_revoked"] is False

        # 5. Rotate → new plaintext value; old key dies immediately
        body = api_call(
            client,
            recorder,
            "POST",
            f"/api/v1/admin/api-keys/{key_id}/rotate",
            "admin",
            "lifecycle_key_rotate",
            headers=admin_headers,
        )
        rotated = body["data"]
        assert rotated["old_key_id"] == key_id
        assert rotated["new_key_id"] != key_id
        assert rotated["new_key_value"].startswith("weaver_")
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "admin",
            "lifecycle_old_key_dead_after_rotate",
            headers=issued,
            # Rotated key misses the DB lookup and fails the env-key
            # fallback comparison -> 403 (only a missing header is 401)
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )

        # 6. Revoke the new key
        body = api_call(
            client,
            recorder,
            "DELETE",
            f"/api/v1/admin/api-keys/{rotated['new_key_id']}",
            "admin",
            "lifecycle_key_revoke",
            headers=admin_headers,
        )
        assert body["data"]["revoked"] is True

        # 7. Revoked key fails regular-endpoint validation
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/sources",
            "admin",
            "lifecycle_revoked_key_rejected",
            headers={"X-API-Key": rotated["new_key_value"]},
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )

        # 8. Re-revoke → 409 (not idempotent), rotate on revoked → 409
        api_call(
            client,
            recorder,
            "DELETE",
            f"/api/v1/admin/api-keys/{rotated['new_key_id']}",
            "admin",
            "lifecycle_key_re_revoke_expect_409",
            headers=admin_headers,
            expect_status=409,
            expect_code=10005,
            expect_data=False,
        )
        api_call(
            client,
            recorder,
            "POST",
            f"/api/v1/admin/api-keys/{rotated['new_key_id']}/rotate",
            "admin",
            "lifecycle_key_rotate_revoked_expect_409",
            headers=admin_headers,
            expect_status=409,
            expect_code=10005,
            expect_data=False,
        )

        # 9. Cleanup: revoke the rotated-away original key (409 tolerated)
        self._cleanup_key(client, admin_headers, key_id)

    def test_revoke_unknown_key(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "DELETE",
            "/api/v1/admin/api-keys/no-such-key",
            "admin",
            "api_key_revoke_unknown_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )


@pytest.mark.e2e
class TestDeduplicate:
    """POST /api/v1/admin/articles/deduplicate — no params, real deletion."""

    def test_deduplicate_payload(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/articles/deduplicate",
            "admin",
            "deduplicate",
            headers=admin_headers,
        )
        data = body["data"]
        assert isinstance(data["removed"], int) and data["removed"] >= 0
        assert isinstance(data["kept"], int) and data["kept"] >= 0


@pytest.mark.e2e
class TestAuthorities:
    """GET/PATCH /admin/authorities, POST refresh-auto-scores."""

    def test_list(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/authorities",
            "admin",
            "authorities_list",
            headers=admin_headers,
        )
        assert isinstance(body["data"], list)
        for item in body["data"]:
            for key in ("id", "host", "authority", "tier"):
                assert key in item, f"authority item key {key} missing"

    def test_patch_empty_body(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "PATCH",
            "/api/v1/admin/authorities/example.com",
            "admin",
            "authorities_patch_empty_expect_400",
            headers=admin_headers,
            json_data={},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        assert "At least one field" in body["message"]

    def test_patch_invalid_host(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "PATCH",
            "/api/v1/admin/authorities/bad_host!name",
            "admin",
            "authorities_patch_invalid_host_expect_422",
            headers=admin_headers,
            json_data={"authority": 0.5},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_patch_unknown_host(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "PATCH",
            "/api/v1/admin/authorities/no-such-host.example",
            "admin",
            "authorities_patch_unknown_expect_404",
            headers=admin_headers,
            json_data={"authority": 0.5},
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_patch_value_bounds(self, client: TestClient, recorder, admin_headers):
        # Valid host syntax but authority out of [0,1] → 422 before existence check
        api_call(
            client,
            recorder,
            "PATCH",
            "/api/v1/admin/authorities/unknown.example.org",
            "admin",
            "authorities_patch_authority_1_5_expect_422",
            headers=admin_headers,
            json_data={"authority": 1.5},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_refresh_auto_scores(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/authorities/refresh-auto-scores",
            "admin",
            "authorities_refresh_auto_scores",
            headers=admin_headers,
        )
        data = body["data"]
        assert isinstance(data["sources_updated"], int) and data["sources_updated"] >= 0
        assert "triggered_at" in data


@pytest.mark.e2e
class TestMemoryAdmin:
    """GET diagnostics (never 503) and POST trigger-consolidation."""

    def test_diagnostics_payload(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/memory/diagnostics",
            "admin",
            "memory_diagnostics",
            headers=admin_headers,
        )
        data = body["data"]
        for key in (
            "memory_service_initialized",
            "temporal_event_count",
            "causal_link_count",
            "pending_consolidation",
            "slow_path_enabled",
            "scheduler_job_registered",
        ):
            assert key in data, f"memory diagnostics key {key} missing"

    def test_consolidation_batch_bounds(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/memory/trigger-consolidation",
            "admin",
            "memory_consolidation_batch_0_expect_422",
            headers=admin_headers,
            params={"batch_size": "0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/memory/trigger-consolidation",
            "admin",
            "memory_consolidation_batch_101_expect_422",
            headers=admin_headers,
            params={"batch_size": "101"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_consolidation_available_or_unavailable(
        self, client: TestClient, recorder, admin_headers
    ):
        from tests.e2e.endpoints._kit import api_call_multi

        body = api_call_multi(
            client,
            recorder,
            "POST",
            "/api/v1/admin/memory/trigger-consolidation",
            "admin",
            "memory_consolidation",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=admin_headers,
            params={"batch_size": "5"},
        )
        if body and body.get("data"):
            assert "processed" in body["data"]
            assert isinstance(body["data"]["event_ids"], list)


@pytest.mark.e2e
class TestDatabaseMonitoring:
    """Database monitoring endpoints degrade gracefully on DuckDB."""

    def test_indexes(self, client: TestClient, recorder, admin_headers):
        from tests.e2e.endpoints._kit import api_call_multi

        body = api_call_multi(
            client,
            recorder,
            "GET",
            "/api/v1/admin/monitoring/database/indexes",
            "admin",
            "monitoring_indexes",
            variants={200: {}},
            headers=admin_headers,
            params={"limit": "10"},
        )
        data = body["data"]
        assert isinstance(data, list)
        for item in data:
            for key in ("table", "index", "scans"):
                assert key in item

    def test_tables(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/monitoring/database/tables",
            "admin",
            "monitoring_tables",
            headers=admin_headers,
        )
        assert isinstance(body["data"], list)

    def test_tables_limit_bounds(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/monitoring/database/tables",
            "admin",
            "monitoring_tables_limit_201_expect_422",
            headers=admin_headers,
            params={"limit": "201"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_pool_stats(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/monitoring/database/pool",
            "admin",
            "monitoring_pool",
            headers=admin_headers,
        )
        data = body["data"]
        for key in ("pool_size", "checked_in", "checked_out", "overflow"):
            assert key in data, f"pool stats key {key} missing"
        assert isinstance(data["pool_size"], int)

    def test_slow_queries(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/monitoring/database/slow-queries",
            "admin",
            "monitoring_slow_queries",
            headers=admin_headers,
        )
        data = body["data"]
        assert "slow_queries" in data
        assert isinstance(data["slow_queries"], list)

    def test_slow_queries_limit_bounds(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/admin/monitoring/database/slow-queries",
            "admin",
            "monitoring_slow_queries_limit_101_expect_422",
            headers=admin_headers,
            params={"limit": "101"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
