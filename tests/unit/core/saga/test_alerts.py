# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for SagaAlertService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.saga.alerts import SagaAlertService


class TestSagaAlertServiceSagaFailure:
    """Tests for alert_saga_failure."""

    @pytest.mark.asyncio
    async def test_saga_failure_increments_metric(self):
        with patch("core.saga.alerts.metrics") as mock_metrics:
            service = SagaAlertService()
            await service.alert_saga_failure(
                saga_id="saga-1",
                article_id="art-1",
                failed_step="pg_insert",
                error="Connection refused",
            )
            mock_metrics.saga_failure_alerts.labels.assert_called_once_with(
                failure_type="saga_failed"
            )
            mock_metrics.saga_failure_alerts.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_saga_failure_with_alert_service(self):
        mock_alert_service = AsyncMock()
        mock_alert_service.list_rules.return_value = []
        mock_alert_service.create_rule.return_value = {"id": 1}
        mock_alert_service.trigger_alert.return_value = {"id": 10}

        service = SagaAlertService(alert_service=mock_alert_service)
        await service.alert_saga_failure(
            saga_id="saga-1",
            article_id="art-1",
            failed_step="pg_insert",
            error="Connection refused",
        )

        mock_alert_service.create_rule.assert_called_once()
        mock_alert_service.trigger_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_saga_failure_reuses_existing_rule(self):
        mock_alert_service = AsyncMock()
        mock_alert_service.list_rules.return_value = [{"id": 5, "metric": "saga_failure"}]
        mock_alert_service.trigger_alert.return_value = {"id": 10}

        service = SagaAlertService(alert_service=mock_alert_service)
        await service.alert_saga_failure(
            saga_id="saga-1",
            article_id="art-1",
            failed_step="pg_insert",
            error="Connection refused",
        )

        mock_alert_service.create_rule.assert_not_called()
        mock_alert_service.trigger_alert.assert_called_once_with(
            rule_id=5,
            metric_value=1.0,
            detail={
                "saga_id": "saga-1",
                "article_id": "art-1",
                "failed_step": "pg_insert",
                "error": "Connection refused",
            },
        )


class TestSagaAlertServiceCompensationFailure:
    """Tests for alert_compensation_failure."""

    @pytest.mark.asyncio
    async def test_compensation_failure_increments_metric(self):
        with patch("core.saga.alerts.metrics") as mock_metrics:
            service = SagaAlertService()
            await service.alert_compensation_failure(
                saga_id="saga-1",
                failed_step="pg_insert",
                error="Rollback failed",
            )
            mock_metrics.saga_failure_alerts.labels.assert_called_once_with(
                failure_type="compensation_failed"
            )
            mock_metrics.saga_failure_alerts.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_compensation_failure_with_alert_service(self):
        mock_alert_service = AsyncMock()
        mock_alert_service.list_rules.return_value = []
        mock_alert_service.create_rule.return_value = {"id": 2}
        mock_alert_service.trigger_alert.return_value = {"id": 11}

        service = SagaAlertService(alert_service=mock_alert_service)
        await service.alert_compensation_failure(
            saga_id="saga-1",
            failed_step="pg_insert",
            error="Rollback failed",
        )

        mock_alert_service.create_rule.assert_called_once()
        mock_alert_service.trigger_alert.assert_called_once()


class TestSagaAlertServiceTimeout:
    """Tests for alert_saga_timeout."""

    @pytest.mark.asyncio
    async def test_timeout_increments_metric(self):
        with patch("core.saga.alerts.metrics") as mock_metrics:
            service = SagaAlertService()
            await service.alert_saga_timeout(
                saga_id="saga-1",
                article_id="art-1",
                timeout_seconds=300,
            )
            mock_metrics.saga_failure_alerts.labels.assert_called_once_with(
                failure_type="saga_timeout"
            )
            mock_metrics.saga_failure_alerts.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_with_alert_service(self):
        mock_alert_service = AsyncMock()
        mock_alert_service.list_rules.return_value = []
        mock_alert_service.create_rule.return_value = {"id": 3}
        mock_alert_service.trigger_alert.return_value = {"id": 12}

        service = SagaAlertService(alert_service=mock_alert_service)
        await service.alert_saga_timeout(
            saga_id="saga-1",
            article_id="art-1",
            timeout_seconds=300,
        )

        mock_alert_service.trigger_alert.assert_called_once()
        call_kwargs = mock_alert_service.trigger_alert.call_args
        assert call_kwargs.kwargs["metric_value"] == 300.0


class TestSagaAlertServiceErrorHandling:
    """Tests for alert service error handling."""

    @pytest.mark.asyncio
    async def test_persistent_alert_failure_does_not_raise(self):
        mock_alert_service = AsyncMock()
        mock_alert_service.list_rules.side_effect = Exception("DB connection failed")

        service = SagaAlertService(alert_service=mock_alert_service)
        # Should not raise
        await service.alert_saga_failure(
            saga_id="saga-1",
            article_id="art-1",
            failed_step="pg_insert",
            error="Connection refused",
        )

    @pytest.mark.asyncio
    async def test_no_alert_service_still_increments_metrics(self):
        with patch("core.saga.alerts.metrics") as mock_metrics:
            service = SagaAlertService(alert_service=None)
            await service.alert_saga_failure(
                saga_id="saga-1",
                article_id="art-1",
                failed_step="pg_insert",
                error="Connection refused",
            )
            mock_metrics.saga_failure_alerts.labels.return_value.inc.assert_called_once()
