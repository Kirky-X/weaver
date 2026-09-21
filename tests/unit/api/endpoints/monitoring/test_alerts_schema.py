# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Validation tests for alert rule request schemas.

 regression: ``cooldown_minutes`` previously had no lower bound, so
a negative cooldown could be persisted and break scheduler arithmetic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.endpoints.monitoring.alerts import (
    CreateAlertRuleRequest,
    UpdateAlertRuleRequest,
    get_alert_service,
    router,
)
from api.middleware.auth import verify_admin_api_key


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin"

    service = MagicMock()
    service.create_rule = AsyncMock(return_value={"id": 1})
    service.update_rule = AsyncMock(return_value={"id": 1})
    app.dependency_overrides[get_alert_service] = lambda: service

    return TestClient(app, raise_server_exceptions=False)


class TestCooldownMinutesLowerBound:
    """Negative cooldown_minutes must be rejected with 422."""

    def test_create_rejects_negative_cooldown(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateAlertRuleRequest(
                entity_name="OpenAI",
                metric="reference_count",
                operator="z_score>",
                threshold=2.0,
                cooldown_minutes=-5,
            )
        assert "cooldown_minutes" in str(exc_info.value)

    def test_update_rejects_negative_cooldown(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            UpdateAlertRuleRequest(cooldown_minutes=-1)
        assert "cooldown_minutes" in str(exc_info.value)

    def test_zero_cooldown_is_valid(self) -> None:
        req = CreateAlertRuleRequest(
            entity_name="OpenAI",
            metric="reference_count",
            operator="z_score>",
            threshold=2.0,
            cooldown_minutes=0,
        )
        assert req.cooldown_minutes == 0

    def test_create_endpoint_negative_cooldown_returns_422(self) -> None:
        client = _make_client()
        resp = client.post(
            "/monitoring/alerts/rules",
            json={
                "entity_name": "OpenAI",
                "metric": "reference_count",
                "operator": "z_score>",
                "threshold": 2.0,
                "cooldown_minutes": -5,
            },
        )
        assert resp.status_code == 422

    def test_update_endpoint_negative_cooldown_returns_422(self) -> None:
        client = _make_client()
        resp = client.patch(
            "/monitoring/alerts/rules/1",
            json={"cooldown_minutes": -1},
        )
        # Validation failure must never reach the service layer.
        assert resp.status_code == 422
        service = client.app.dependency_overrides[get_alert_service]()
        service.update_rule.assert_not_called()


class TestMetricOperatorEnum:
    """``metric`` and ``operator`` MUST be constrained to known values.

    A typo like ``zscore>`` or an unknown metric would previously create a rule
    that can never fire (``evaluate_condition`` silently returns False). The
    schema now rejects them with 422 at validation time.
    """

    def test_invalid_metric_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateAlertRuleRequest(
                entity_name="OpenAI",
                metric="z_score>",
                operator="z_score>",
                threshold=2.0,
            )
        assert "metric" in str(exc_info.value)

    def test_invalid_operator_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateAlertRuleRequest(
                entity_name="OpenAI",
                metric="reference_count",
                operator="zscore>",
                threshold=2.0,
            )
        assert "operator" in str(exc_info.value)

    def test_valid_metric_operator_accepted(self) -> None:
        req = CreateAlertRuleRequest(
            entity_name="OpenAI",
            metric="saga_timeout",
            operator="absolute>",
            threshold=1.0,
        )
        assert req.metric == "saga_timeout"
        assert req.operator == "absolute>"

    def test_endpoint_invalid_metric_returns_422(self) -> None:
        client = _make_client()
        resp = client.post(
            "/monitoring/alerts/rules",
            json={
                "entity_name": "OpenAI",
                "metric": "not_a_real_metric",
                "operator": "z_score>",
                "threshold": 2.0,
            },
        )
        assert resp.status_code == 422
