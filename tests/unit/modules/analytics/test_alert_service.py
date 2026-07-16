# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AlertService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.analytics.alert_service import AlertService


@pytest.fixture
def mock_pool():
    """Create a mock RelationalPool."""
    pool = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    pool.session_context.return_value = mock_session
    return pool


@pytest.fixture
def service(mock_pool):
    """Create an AlertService instance."""
    return AlertService(mock_pool)


# ── 1. Create Alert Rule ──────────────────────────────────────────


class TestCreateAlertRule:
    """test_create_alert_rule"""

    @pytest.mark.asyncio
    async def test_create_alert_rule(self, service, mock_pool):
        """Creating an alert rule should persist it to the database."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        rule = await service.create_rule(
            entity_name="中国",
            metric="reference_count",
            operator="z_score>",
            threshold=2.0,
            channel="webhook",
            cooldown_minutes=60,
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        assert rule is not None


# ── 2. Evaluate Rule: z_score ─────────────────────────────────────


class TestEvaluateRuleZScore:
    """test_evaluate_rule_z_score"""

    @pytest.mark.asyncio
    async def test_z_score_exceeds_threshold(self, service):
        """z_score operator should trigger when value exceeds threshold."""
        result = service.evaluate_condition(
            operator="z_score>",
            threshold=2.0,
            current_value=3.5,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_z_score_below_threshold(self, service):
        """z_score operator should not trigger when value is below threshold."""
        result = service.evaluate_condition(
            operator="z_score>",
            threshold=2.0,
            current_value=1.5,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_z_score_at_threshold(self, service):
        """z_score operator should not trigger when value equals threshold."""
        result = service.evaluate_condition(
            operator="z_score>",
            threshold=2.0,
            current_value=2.0,
        )
        assert result is False


# ── 3. Evaluate Rule: pct_change ──────────────────────────────────


class TestEvaluateRulePctChange:
    """test_evaluate_rule_pct_change"""

    @pytest.mark.asyncio
    async def test_pct_change_exceeds_threshold(self, service):
        """pct_change operator should trigger when change exceeds threshold."""
        result = service.evaluate_condition(
            operator="pct_change>",
            threshold=0.5,
            current_value=0.8,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_pct_change_below_threshold(self, service):
        """pct_change operator should not trigger when change is below threshold."""
        result = service.evaluate_condition(
            operator="pct_change>",
            threshold=0.5,
            current_value=0.3,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_pct_change_at_threshold(self, service):
        """pct_change operator should not trigger when change equals threshold."""
        result = service.evaluate_condition(
            operator="pct_change>",
            threshold=0.5,
            current_value=0.5,
        )
        assert result is False


# ── 4. Trigger Alert Creates Event ────────────────────────────────


class TestTriggerAlertCreatesEvent:
    """test_trigger_alert_creates_event"""

    @pytest.mark.asyncio
    async def test_trigger_alert_creates_event(self, service, mock_pool):
        """Triggering an alert should create an AlertEvent record."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.commit = AsyncMock()

        # Mock the rule query result
        mock_rule = MagicMock()
        mock_rule.id = 1
        mock_rule.entity_name = "中国"
        mock_rule.metric = "reference_count"
        mock_rule.operator = "z_score>"
        mock_rule.threshold = 2.0
        mock_rule.channel = "webhook"
        mock_rule.cooldown_minutes = 60
        mock_rule.enabled = True

        mock_rule_result = MagicMock()
        mock_rule_result.scalars.return_value.first.return_value = mock_rule

        # Mock no recent events (cooldown check)
        mock_event_result = MagicMock()
        mock_event_result.scalar.return_value = None

        # execute is awaited, so side_effect returns the result directly
        mock_session.execute.side_effect = [mock_rule_result, mock_event_result]

        event = await service.trigger_alert(
            rule_id=1,
            metric_value=3.5,
            detail={"z_score": 3.5},
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        assert event is not None


# ── 5. Cooldown Prevents Duplicate ────────────────────────────────


class TestCooldownPreventsDuplicate:
    """test_cooldown_prevents_duplicate"""

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate(self, service, mock_pool):
        """Triggering an alert within cooldown should not create a new event."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        # Mock the rule query result
        mock_rule = MagicMock()
        mock_rule.id = 1
        mock_rule.entity_name = "中国"
        mock_rule.cooldown_minutes = 60
        mock_rule.enabled = True

        mock_rule_result = MagicMock()
        mock_rule_result.scalars.return_value.first.return_value = mock_rule

        # Mock a recent event within cooldown
        mock_recent_event = MagicMock()
        mock_recent_event.triggered_at = datetime.now(UTC)

        mock_event_result = MagicMock()
        mock_event_result.scalar.return_value = mock_recent_event

        mock_session.execute.side_effect = [mock_rule_result, mock_event_result]

        event = await service.trigger_alert(
            rule_id=1,
            metric_value=3.5,
        )

        # Should NOT create a new event
        mock_session.add.assert_not_called()
        assert event is None


# ── 6. Acknowledge Alert ──────────────────────────────────────────


class TestAcknowledgeAlert:
    """test_acknowledge_alert"""

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self, service, mock_pool):
        """Acknowledging an alert should set acknowledged_at timestamp."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.commit = AsyncMock()

        # Mock the event query result
        mock_event = MagicMock()
        mock_event.acknowledged_at = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_event
        mock_session.execute.return_value = mock_result

        result = await service.acknowledge_event(event_id=1)

        assert mock_event.acknowledged_at is not None
        mock_session.commit.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_acknowledge_nonexistent_event(self, service, mock_pool):
        """Acknowledging a non-existent event should return False."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.acknowledge_event(event_id=999)
        assert result is False
