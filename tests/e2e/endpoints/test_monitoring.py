# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for monitoring endpoints (alerts, causal stats, community health,
graph metrics, LLM failures/usage, memory diagnostics).

Contract highlights:
- Alert rules: metric is one of 6 literals, operator one of 3 literals
  (Pydantic-enforced → 422); PATCH with empty body → 400; trigger during
  cooldown → 200 + data:null + warning (not an error); acknowledge is
  idempotent; threshold has no range validation by design
- GET /monitoring/llm/usage: from/to are mandatory datetimes → 422 when
  missing; group_by/granularity are regex-validated
- Monitoring memory diagnostics never 503s (container provides defaults)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call, api_call_multi

VALID_METRICS = (
    "reference_count",
    "sentiment_change",
    "volume_spike",
    "saga_failure",
    "compensation_failure",
    "saga_timeout",
)
VALID_OPERATORS = ("z_score>", "pct_change>", "absolute>")


def _rule_payload(entity: str, **overrides) -> dict:
    payload = {
        "entity_name": entity,
        "metric": "reference_count",
        "operator": "z_score>",
        "threshold": 2.0,
    }
    payload.update(overrides)
    return payload


@pytest.mark.e2e
class TestAlertRules:
    """CRUD for /api/v1/monitoring/alerts/rules."""

    def test_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_list_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_regular_key_forbidden(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_list_regular_key_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )

    def test_invalid_metric_rejected(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_invalid_metric_expect_422",
            headers=admin_headers,
            json_data=_rule_payload("e2e-entity", metric="cpu_usage"),
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_invalid_operator_rejected(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_invalid_operator_expect_422",
            headers=admin_headers,
            json_data=_rule_payload("e2e-entity", operator=">="),
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_missing_required_fields(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_missing_fields_expect_422",
            headers=admin_headers,
            json_data={"entity_name": "x"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_rule_crud_roundtrip(self, client: TestClient, recorder, admin_headers):
        entity = f"e2e-rule-entity-{id(self)}"
        # Create
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_rule_create",
            headers=admin_headers,
            json_data=_rule_payload(entity, cooldown_minutes=0),
        )
        rule = body["data"]
        for key in (
            "id",
            "entity_name",
            "metric",
            "operator",
            "threshold",
            "channel",
            "cooldown_minutes",
            "enabled",
        ):
            assert key in rule, f"alert rule key {key} missing"
        assert rule["entity_name"] == entity
        assert rule["enabled"] is True
        rule_id = rule["id"]

        # Read
        body = api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/monitoring/alerts/rules/{rule_id}",
            "monitoring",
            "alerts_rule_get",
            headers=admin_headers,
        )
        assert body["data"]["id"] == rule_id

        # List filter by entity
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_rule_list_filtered",
            headers=admin_headers,
            params={"entity_name": entity},
        )
        assert any(r["id"] == rule_id for r in body["data"])

        # Patch (disable)
        body = api_call(
            client,
            recorder,
            "PATCH",
            f"/api/v1/monitoring/alerts/rules/{rule_id}",
            "monitoring",
            "alerts_rule_patch",
            headers=admin_headers,
            json_data={"enabled": False},
        )
        assert body["data"]["enabled"] is False

        # Patch with empty body → 400
        api_call(
            client,
            recorder,
            "PATCH",
            f"/api/v1/monitoring/alerts/rules/{rule_id}",
            "monitoring",
            "alerts_rule_patch_empty_expect_400",
            headers=admin_headers,
            json_data={},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )

        # Delete
        body = api_call(
            client,
            recorder,
            "DELETE",
            f"/api/v1/monitoring/alerts/rules/{rule_id}",
            "monitoring",
            "alerts_rule_delete",
            headers=admin_headers,
        )
        assert body["data"] is True

        # Get after delete → 404
        api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/monitoring/alerts/rules/{rule_id}",
            "monitoring",
            "alerts_rule_get_after_delete_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_get_unknown_rule(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/alerts/rules/999999",
            "monitoring",
            "alerts_rule_unknown_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )


@pytest.mark.e2e
class TestAlertTriggerAndEvents:
    """POST trigger / acknowledge, GET events."""

    def test_trigger_unknown_rule(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/trigger",
            "monitoring",
            "alerts_trigger_unknown_rule_expect_404",
            headers=admin_headers,
            json_data={"rule_id": 999999, "metric_value": 5.0},
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_trigger_cooldown_returns_warning(self, client: TestClient, recorder, admin_headers):
        """First trigger creates an event; second within cooldown → data:null
        plus a warning field (200, not an error)."""
        entity = f"e2e-trigger-entity-{id(self)}"
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/rules",
            "monitoring",
            "alerts_trigger_setup_rule",
            headers=admin_headers,
            json_data=_rule_payload(entity, cooldown_minutes=60),
        )
        rule_id = body["data"]["id"]

        first = api_call_multi(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/trigger",
            "monitoring",
            "alerts_trigger_first",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=admin_headers,
            json_data={"rule_id": rule_id, "metric_value": 10.0, "detail": {"src": "e2e"}},
        )
        if first and first.get("data"):
            assert first["data"]["rule_id"] == rule_id

        # Second trigger inside the cooldown window: envelope code 0 with
        # data null (expect_data=False) and a populated warning field
        second = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/trigger",
            "monitoring",
            "alerts_trigger_cooldown",
            headers=admin_headers,
            json_data={"rule_id": rule_id, "metric_value": 11.0},
            expect_data=False,
        )
        if second.get("data") is None:
            assert second.get("warning"), "cooldown suppression must surface a warning"

        # Events list shows the triggered event(s)
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/alerts/events",
            "monitoring",
            "alerts_events_list",
            headers=admin_headers,
            params={"entity_name": entity},
        )
        assert isinstance(body["data"], list)
        if body["data"]:
            event = body["data"][0]
            # Acknowledge (idempotent)
            api_call(
                client,
                recorder,
                "POST",
                f"/api/v1/monitoring/alerts/events/{event['id']}/acknowledge",
                "monitoring",
                "alerts_event_acknowledge",
                headers=admin_headers,
            )

        # Cleanup rule
        api_call(
            client,
            recorder,
            "DELETE",
            f"/api/v1/monitoring/alerts/rules/{rule_id}",
            "monitoring",
            "alerts_trigger_cleanup",
            headers=admin_headers,
        )

    def test_acknowledge_unknown_event(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/monitoring/alerts/events/999999/acknowledge",
            "monitoring",
            "alerts_ack_unknown_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_events_limit_bounds(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/alerts/events",
            "monitoring",
            "alerts_events_limit_201_expect_422",
            headers=admin_headers,
            params={"limit": "201"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestCausalStats:
    """GET /api/v1/monitoring/causal/stats."""

    def test_stats(self, client: TestClient, recorder, admin_headers):
        body = api_call_multi(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/causal/stats",
            "monitoring",
            "causal_stats",
            variants={
                200: {},
                503: {"expect_code": 50001, "expect_data": False},
            },
            headers=admin_headers,
        )
        if body and body.get("data"):
            data = body["data"]
            assert isinstance(data["causal_edges"], int)
            assert set(data["edge_types"]) == {"CAUSES", "ENABLES", "PREVENTS"}


@pytest.mark.e2e
class TestMonitoringCommunitiesHealth:
    """GET /api/v1/monitoring/communities/health."""

    def test_health_payload(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/communities/health",
            "monitoring",
            "communities_health",
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
            assert key in data, f"community health key {key} missing"
        assert 0 <= data["score"] <= 100
        assert data["status"] in ("healthy", "moderate", "degraded", "critical")
        # Always null by design
        assert data["last_check_at"] is None

    def test_health_regular_key_forbidden(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/communities/health",
            "monitoring",
            "communities_health_regular_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )


@pytest.mark.e2e
class TestMonitoringGraphMetrics:
    """GET /api/v1/monitoring/graph/metrics (view validation mirrors /graph/metrics)."""

    def test_health_view(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/graph/metrics",
            "monitoring",
            "monitoring_graph_metrics_health",
            headers=admin_headers,
        )
        data = body["data"]
        assert 0 <= data["health_score"] <= 100
        assert data["status"] in ("healthy", "moderate", "degraded", "critical")

    def test_invalid_view(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/graph/metrics",
            "monitoring",
            "monitoring_graph_metrics_invalid_view_expect_400",
            headers=admin_headers,
            params={"view": "nope"},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestLLMMonitoring:
    """GET /monitoring/llm/failures, /failures/stats, /usage."""

    def test_failures_list(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/failures",
            "monitoring",
            "llm_failures_list",
            headers=admin_headers,
        )
        assert isinstance(body["data"], list)

    def test_failures_limit_bounds(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/failures",
            "monitoring",
            "llm_failures_limit_201_expect_422",
            headers=admin_headers,
            params={"limit": "201"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_failures_invalid_since(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/failures",
            "monitoring",
            "llm_failures_bad_since_expect_422",
            headers=admin_headers,
            params={"since": "yesterday"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_failure_stats(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/failures/stats",
            "monitoring",
            "llm_failures_stats",
            headers=admin_headers,
        )
        data = body["data"]
        for key in ("total_failures", "by_call_point", "by_status", "last_failure_at"):
            assert key in data, f"llm failure stats key {key} missing"
        assert isinstance(data["total_failures"], int)

    def test_usage_requires_from_to(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/usage",
            "monitoring",
            "llm_usage_missing_range_expect_422",
            headers=admin_headers,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_usage_invalid_group_by(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/usage",
            "monitoring",
            "llm_usage_bad_group_by_expect_422",
            headers=admin_headers,
            params={
                "from": "2026-01-01T00:00:00",
                "to": "2026-01-02T00:00:00",
                "group_by": "color",
            },
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_usage_invalid_granularity(self, client: TestClient, recorder, admin_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/usage",
            "monitoring",
            "llm_usage_bad_granularity_expect_422",
            headers=admin_headers,
            params={
                "from": "2026-01-01T00:00:00",
                "to": "2026-01-02T00:00:00",
                "granularity": "weekly",
            },
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_usage_summary(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/usage",
            "monitoring",
            "llm_usage_summary",
            headers=admin_headers,
            params={"from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00"},
        )
        data = body["data"]
        for key in (
            "group_by",
            "total_calls",
            "total_tokens",
            "avg_latency_ms",
            "total_cost_usd",
            "success_rate",
        ):
            assert key in data, f"llm usage summary key {key} missing"
        assert data["group_by"] == "summary"
        assert data["total_calls"] >= 0

    def test_usage_group_by_time(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/llm/usage",
            "monitoring",
            "llm_usage_group_time",
            headers=admin_headers,
            params={
                "from": "2026-01-01T00:00:00",
                "to": "2026-01-02T00:00:00",
                "group_by": "time",
                "granularity": "daily",
            },
        )
        data = body["data"]
        assert data["group_by"] == "time"
        assert isinstance(data["records"], list)


@pytest.mark.e2e
class TestMonitoringMemory:
    """GET /api/v1/monitoring/memory/diagnostics."""

    def test_diagnostics(self, client: TestClient, recorder, admin_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/monitoring/memory/diagnostics",
            "monitoring",
            "monitoring_memory_diagnostics",
            headers=admin_headers,
        )
        data = body["data"]
        assert "memory_service_initialized" in data
        assert "temporal_event_count" in data
