# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""E2E tests for system endpoints: /health, /metrics, /api/v1/status,
/api/v1/config, /api/v1/system/health/dependencies, /api/v1/admin/cache/clear,
/api/v1/admin/config/reload."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call


@pytest.mark.e2e
class TestHealthEndpoint:
    """GET /health — public liveness probe (checks omitted by design)."""

    def test_health_public_ok(self, client: TestClient, recorder):
        body = api_call(client, recorder, "GET", "/health", "system", "health_public_no_auth")
        assert body["data"]["status"] in ("healthy", "unhealthy")
        # Error details are deliberately omitted from the public probe
        assert "checks" not in body["data"]


@pytest.mark.e2e
class TestMetricsEndpoint:
    """GET /metrics — Prometheus plaintext, auth required by default."""

    def test_metrics_requires_auth(self, client: TestClient, recorder):
        response = client.get("/metrics")
        assert response.status_code == 401

    def test_metrics_plaintext(self, client: TestClient, auth_headers):
        response = client.get("/metrics", headers=auth_headers)
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
        assert response.text  # non-empty exposition format body

    def test_metrics_rejects_invalid_key(self, client: TestClient):
        response = client.get("/metrics", headers={"X-API-Key": "definitely-wrong-key"})
        assert response.status_code == 403


@pytest.mark.e2e
class TestSystemStatus:
    """GET /api/v1/status — running status + database types."""

    def test_status_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/status",
            "system",
            "status_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_status_payload(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/status",
            "system",
            "status_with_auth",
            headers=auth_headers,
        )
        data = body["data"]
        assert data["status"] == "running"
        assert isinstance(data["version"], str) and data["version"]
        for key in ("relational", "graph", "cache"):
            assert key in data["database"], f"database.{key} missing"


@pytest.mark.e2e
class TestSystemConfig:
    """GET /api/v1/config — admin-only feature switches (no secrets)."""

    def test_config_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/config",
            "system",
            "config_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_config_forbids_regular_key(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/config",
            "system",
            "config_regular_key_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )
        assert "Admin" in body["message"] or "admin" in body["message"]

    def test_config_payload(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/config",
            "system",
            "config_admin_ok",
            headers=admin_headers,
        )
        data = body["data"]
        for key in (
            "relational_pool_type",
            "graph_pool_type",
            "llm_enabled",
            "search_enabled",
            "graph_available",
        ):
            assert key in data, f"config.{key} missing"
        assert isinstance(data["llm_enabled"], bool)
        # No secrets leak: values are type names / booleans only
        assert data["relational_pool_type"] in ("postgres", "duckdb", "PostgresPool", "DuckDBPool")


@pytest.mark.e2e
class TestHealthDependencies:
    """Two distinct dependency-health endpoints:

    - GET /api/v1/health/dependencies — regular key, aggregated checks
    - GET /api/v1/system/health/dependencies — admin key, detailed
      per-dependency status incl. LLM providers
    """

    def test_aggregated_dependencies(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/health/dependencies",
            "system",
            "dependencies_aggregated_regular_key",
            headers=auth_headers,
        )
        assert body["data"]["status"] in ("healthy", "unhealthy")
        assert isinstance(body["data"]["checks"], dict)

    def test_detailed_dependencies_admin_only(
        self, client: TestClient, recorder, auth_headers, admin_headers
    ):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/system/health/dependencies",
            "system",
            "dependencies_detailed_regular_key_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/system/health/dependencies",
            "system",
            "dependencies_detailed_admin_ok",
            headers=admin_headers,
        )
        assert body["data"]["status"] in ("healthy", "degraded")
        assert isinstance(body["data"]["dependencies"], dict)


@pytest.mark.e2e
class TestCacheClear:
    """POST /api/v1/admin/cache/clear — glob pattern delete."""

    def test_cache_clear_admin_only(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/cache/clear",
            "system",
            "cache_clear_regular_key_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )

    def test_cache_clear_default_pattern(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/cache/clear",
            "system",
            "cache_clear_default_pattern",
            headers=admin_headers,
        )
        data = body["data"]
        assert data["status"] == "completed"
        assert isinstance(data["deleted"], int) and data["deleted"] >= 0
        assert data["pattern"] == "*"

    def test_cache_clear_scoped_pattern(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/cache/clear",
            "system",
            "cache_clear_scoped_pattern",
            headers=admin_headers,
            params={"pattern": "cache:nonexistent:*"},
        )
        assert body["data"]["pattern"] == "cache:nonexistent:*"
        assert body["data"]["deleted"] == 0


@pytest.mark.e2e
class TestConfigReload:
    """POST /api/v1/admin/config/reload — live LLM config reload."""

    def test_reload_admin_only(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/config/reload",
            "system",
            "config_reload_regular_key_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )

    def test_reload_ok(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/admin/config/reload",
            "system",
            "config_reload_admin_ok",
            headers=admin_headers,
        )
        data = body["data"]
        assert data["status"] == "reloaded"
        assert isinstance(data["providers"], int) and data["providers"] >= 0
        assert isinstance(data["config_path"], str) and data["config_path"]
