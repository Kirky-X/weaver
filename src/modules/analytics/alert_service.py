# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Alert service for entity monitoring.

Provides CRUD for alert rules, rule evaluation, event triggering
with cooldown, and event acknowledgment.

No matching Protocol yet — standalone service component.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)


class AlertService:
    """Alert rule management and evaluation service.

    No matching Protocol yet — standalone service component.
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def create_rule(
        self,
        entity_name: str,
        metric: str,
        operator: str,
        threshold: float,
        channel: str = "webhook",
        cooldown_minutes: int = 60,
    ) -> dict[str, Any]:
        """Create a new alert rule.

        Args:
            entity_name: Entity to monitor.
            metric: Metric to watch (reference_count, sentiment_change, volume_spike).
            operator: Comparison operator (z_score>, pct_change>, absolute>).
            threshold: Threshold value for triggering.
            channel: Notification channel.
            cooldown_minutes: Minimum minutes between alerts for the same rule.

        Returns:
            Dict representation of the created rule.
        """
        from core.db.models import AlertRule

        async with self._pool.session_context() as session:
            rule = AlertRule(
                entity_name=entity_name,
                metric=metric,
                operator=operator,
                threshold=threshold,
                channel=channel,
                cooldown_minutes=cooldown_minutes,
                enabled=True,
            )
            session.add(rule)
            await session.flush()
            await session.commit()

            return {
                "id": rule.id,
                "entity_name": rule.entity_name,
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": float(rule.threshold),
                "channel": rule.channel,
                "cooldown_minutes": rule.cooldown_minutes,
                "enabled": rule.enabled,
            }

    async def get_rule(self, rule_id: int) -> dict[str, Any] | None:
        """Get an alert rule by ID."""
        from sqlalchemy import select

        from core.db.models import AlertRule

        async with self._pool.session_context() as session:
            result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
            rule = result.scalars().first()
            if rule is None:
                return None
            return {
                "id": rule.id,
                "entity_name": rule.entity_name,
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": float(rule.threshold),
                "channel": rule.channel,
                "cooldown_minutes": rule.cooldown_minutes,
                "enabled": rule.enabled,
            }

    async def list_rules(
        self,
        entity_name: str | None = None,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List alert rules, optionally filtered."""
        from sqlalchemy import select

        from core.db.models import AlertRule

        async with self._pool.session_context() as session:
            query = select(AlertRule)
            if entity_name:
                query = query.where(AlertRule.entity_name == entity_name)
            if enabled_only:
                query = query.where(AlertRule.enabled.is_(True))
            query = query.order_by(AlertRule.id.desc())
            result = await session.execute(query)
            rules = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "entity_name": r.entity_name,
                    "metric": r.metric,
                    "operator": r.operator,
                    "threshold": float(r.threshold),
                    "channel": r.channel,
                    "cooldown_minutes": r.cooldown_minutes,
                    "enabled": r.enabled,
                }
                for r in rules
            ]

    async def update_rule(self, rule_id: int, **fields: Any) -> dict[str, Any] | None:
        """Update an alert rule."""
        from sqlalchemy import select

        from core.db.models import AlertRule

        async with self._pool.session_context() as session:
            result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
            rule = result.scalars().first()
            if rule is None:
                return None
            for key, value in fields.items():
                if hasattr(rule, key):
                    setattr(rule, key, value)
            await session.commit()
            return {
                "id": rule.id,
                "entity_name": rule.entity_name,
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": float(rule.threshold),
                "channel": rule.channel,
                "cooldown_minutes": rule.cooldown_minutes,
                "enabled": rule.enabled,
            }

    async def delete_rule(self, rule_id: int) -> bool:
        """Delete an alert rule."""
        from sqlalchemy import select

        from core.db.models import AlertRule

        async with self._pool.session_context() as session:
            result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
            rule = result.scalars().first()
            if rule is None:
                return False
            await session.delete(rule)
            await session.commit()
            return True

    def evaluate_condition(
        self,
        operator: str,
        threshold: float,
        current_value: float,
    ) -> bool:
        """Evaluate whether a condition is met.

        Args:
            operator: Comparison operator (z_score>, pct_change>, absolute>).
            threshold: Threshold value.
            current_value: Current metric value.

        Returns:
            True if the condition triggers an alert.
        """
        if operator in ("z_score>", "pct_change>", "absolute>"):
            return current_value > threshold
        return False

    async def trigger_alert(
        self,
        rule_id: int,
        metric_value: float,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Trigger an alert for a rule if cooldown allows.

        Args:
            rule_id: The alert rule ID.
            metric_value: The current metric value that triggered the alert.
            detail: Additional detail for the event.

        Returns:
            Dict representation of the created event, or None if cooldown blocked.
        """
        from sqlalchemy import select

        from core.db.models import AlertEvent, AlertRule

        async with self._pool.session_context() as session:
            # 1. Get the rule
            result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
            rule = result.scalars().first()
            if rule is None or not rule.enabled:
                log.warning("trigger_alert_rule_not_found", rule_id=rule_id)
                return None

            # 2. Check cooldown — look for recent event within cooldown window
            cooldown_cutoff = datetime.now(UTC) - timedelta(minutes=rule.cooldown_minutes)
            recent_result = await session.execute(
                select(AlertEvent).where(
                    AlertEvent.rule_id == rule_id,
                    AlertEvent.triggered_at > cooldown_cutoff,
                )
            )
            recent_event = recent_result.scalar()
            if recent_event is not None:
                log.info(
                    "trigger_alert_cooldown_active",
                    rule_id=rule_id,
                    last_triggered=recent_event.triggered_at.isoformat(),
                )
                return None

            # 3. Create the event
            event = AlertEvent(
                rule_id=rule_id,
                entity_name=rule.entity_name,
                metric_value=metric_value,
                detail=detail,
            )
            session.add(event)
            await session.commit()

            log.info(
                "trigger_alert_created",
                rule_id=rule_id,
                entity_name=rule.entity_name,
                metric_value=metric_value,
            )

            return {
                "id": event.id,
                "rule_id": event.rule_id,
                "entity_name": event.entity_name,
                "metric_value": float(event.metric_value),
                "triggered_at": event.triggered_at.isoformat() if event.triggered_at else None,
                "acknowledged_at": (
                    event.acknowledged_at.isoformat() if event.acknowledged_at else None
                ),
                "detail": event.detail,
            }

    async def acknowledge_event(self, event_id: int) -> bool:
        """Acknowledge an alert event.

        Args:
            event_id: The alert event ID.

        Returns:
            True if acknowledged, False if event not found.
        """
        from sqlalchemy import select

        from core.db.models import AlertEvent

        async with self._pool.session_context() as session:
            result = await session.execute(select(AlertEvent).where(AlertEvent.id == event_id))
            event = result.scalars().first()
            if event is None:
                return False
            event.acknowledged_at = datetime.now(UTC)
            await session.commit()
            return True

    async def list_events(
        self,
        rule_id: int | None = None,
        entity_name: str | None = None,
        acknowledged: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List alert events with optional filters."""
        from sqlalchemy import select

        from core.db.models import AlertEvent

        async with self._pool.session_context() as session:
            query = select(AlertEvent)
            if rule_id is not None:
                query = query.where(AlertEvent.rule_id == rule_id)
            if entity_name is not None:
                query = query.where(AlertEvent.entity_name == entity_name)
            if acknowledged is False:
                query = query.where(AlertEvent.acknowledged_at.is_(None))
            elif acknowledged is True:
                query = query.where(AlertEvent.acknowledged_at.isnot(None))
            query = query.order_by(AlertEvent.triggered_at.desc()).limit(limit)
            result = await session.execute(query)
            events = result.scalars().all()
            return [
                {
                    "id": e.id,
                    "rule_id": e.rule_id,
                    "entity_name": e.entity_name,
                    "metric_value": float(e.metric_value),
                    "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
                    "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
                    "detail": e.detail,
                }
                for e in events
            ]
