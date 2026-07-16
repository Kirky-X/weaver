# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Saga alert service for failure notification.

Integrates saga and compensation failures with the alerting system.
Logs alerts, increments Prometheus counters, and can trigger external
notifications via the existing AlertService.

Implements:
    - SagaAlertService: Alert handling for saga/compensation failures
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from core.observability.metrics import metrics

if TYPE_CHECKING:
    from modules.analytics.alert_service import AlertService

log = get_logger(__name__)


class SagaAlertService:
    """Alert service for saga and compensation failures.

    Provides alert triggering for saga failures, compensation failures,
    and saga timeouts. Integrates with the existing AlertService for
    persistent alert events and uses Prometheus counters for monitoring.

    Args:
        alert_service: Optional AlertService for persistent alert storage.
            If None, alerts are only logged and counted via Prometheus.
    """

    def __init__(self, alert_service: AlertService | None = None) -> None:
        self._alert_service = alert_service

    async def alert_saga_failure(
        self,
        saga_id: str,
        article_id: str,
        failed_step: str,
        error: str,
    ) -> None:
        """Alert on saga execution failure.

        Args:
            saga_id: ID of the failed saga.
            article_id: ID of the affected article.
            failed_step: Name of the step that failed.
            error: Error message from the failure.
        """
        metrics.saga_failure_alerts.labels(failure_type="saga_failed").inc()

        detail = {
            "saga_id": saga_id,
            "article_id": article_id,
            "failed_step": failed_step,
            "error": error,
        }

        log.error(
            "saga_failure_alert",
            saga_id=saga_id,
            article_id=article_id,
            failed_step=failed_step,
            error=error,
        )

        if self._alert_service is not None:
            await self._trigger_persistent_alert(
                entity_name=f"saga:{saga_id}",
                metric="saga_failure",
                value=1.0,
                detail=detail,
            )

    async def alert_compensation_failure(
        self,
        saga_id: str,
        failed_step: str,
        error: str,
    ) -> None:
        """Alert on compensation transaction failure.

        Args:
            saga_id: ID of the saga with failed compensation.
            failed_step: Name of the step whose compensation failed.
            error: Error message from the compensation failure.
        """
        metrics.saga_failure_alerts.labels(failure_type="compensation_failed").inc()

        detail = {
            "saga_id": saga_id,
            "failed_step": failed_step,
            "error": error,
        }

        log.error(
            "compensation_failure_alert",
            saga_id=saga_id,
            failed_step=failed_step,
            error=error,
        )

        if self._alert_service is not None:
            await self._trigger_persistent_alert(
                entity_name=f"saga:{saga_id}",
                metric="compensation_failure",
                value=1.0,
                detail=detail,
            )

    async def alert_saga_timeout(
        self,
        saga_id: str,
        article_id: str,
        timeout_seconds: int,
    ) -> None:
        """Alert on saga execution timeout.

        Args:
            saga_id: ID of the timed-out saga.
            article_id: ID of the affected article.
            timeout_seconds: Configured timeout duration.
        """
        metrics.saga_failure_alerts.labels(failure_type="saga_timeout").inc()

        detail = {
            "saga_id": saga_id,
            "article_id": article_id,
            "timeout_seconds": timeout_seconds,
        }

        log.error(
            "saga_timeout_alert",
            saga_id=saga_id,
            article_id=article_id,
            timeout_seconds=timeout_seconds,
        )

        if self._alert_service is not None:
            await self._trigger_persistent_alert(
                entity_name=f"saga:{saga_id}",
                metric="saga_timeout",
                value=float(timeout_seconds),
                detail=detail,
            )

    async def _trigger_persistent_alert(
        self,
        entity_name: str,
        metric: str,
        value: float,
        detail: dict[str, Any],
    ) -> None:
        """Trigger a persistent alert via AlertService.

        Creates or reuses an alert rule for the entity/metric combination,
        then triggers an alert event.

        Args:
            entity_name: Entity identifier for the alert.
            metric: Metric name that triggered the alert.
            value: Current metric value.
            detail: Additional detail for the alert event.
        """
        try:
            # Look for existing rule for this entity/metric
            rules = await self._alert_service.list_rules(entity_name=entity_name, enabled_only=True)
            rule_id = None
            for rule in rules:
                if rule["metric"] == metric:
                    rule_id = rule["id"]
                    break

            # Create rule if none exists
            if rule_id is None:
                created = await self._alert_service.create_rule(
                    entity_name=entity_name,
                    metric=metric,
                    operator="absolute>",
                    threshold=0,
                    channel="webhook",
                    cooldown_minutes=5,
                )
                rule_id = created["id"]

            # Trigger the alert event
            await self._alert_service.trigger_alert(
                rule_id=rule_id,
                metric_value=value,
                detail=detail,
            )
        except Exception as exc:
            log.error(
                "saga_alert_trigger_failed",
                entity_name=entity_name,
                metric=metric,
                error=str(exc),
            )
