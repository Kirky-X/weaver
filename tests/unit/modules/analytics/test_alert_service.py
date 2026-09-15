# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AlertService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
        mock_pool.session_context.assert_called_once()
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
        mock_pool.session_context.assert_called_once()
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
        mock_pool.session_context.assert_called_once()
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


# ── 7. Delete Alert Rule (TDD for DELETE endpoint 500 fix) ───────
#
# Root cause: alert_events.rule_id FK is NO ACTION (RESTRICT) in PG
# (migration 08 + confirmed by migration 28 downgrade comments).
# Deleting a rule that has events triggers FK violation → HTTP 500.
# Fix: in delete_rule, DELETE alert_events first, then alert_rule,
# both in the same transaction. Must work for PostgreSQL and DuckDB.


class TestDeleteAlertRule:
    """test_delete_alert_rule — covers all boundary scenarios.

    Scenarios required by task (do not simplify):
    - rule_id not found        → return False (404 at API layer)
    - rule exists, no events   → delete rule, return True
    - rule exists, has events  → delete events then rule (transaction), return True
    - DB exception             → propagate, no commit
    """

    @pytest.mark.asyncio
    async def test_delete_rule_not_found_returns_false(self, service, mock_pool):
        """Rule not found: no DELETE executed, no commit, return False."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.delete_rule(rule_id=999)

        assert result is False
        # Only the existence-check SELECT should have run — no DELETEs.
        assert mock_session.execute.call_count == 1
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_rule_no_events_deletes_rule_only(self, service, mock_pool):
        """Rule with no associated events: SELECT + DELETE events + DELETE rule."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.commit = AsyncMock()

        # Rule lookup returns an existing rule
        mock_rule = MagicMock()
        mock_rule.id = 11
        mock_rule_result = MagicMock()
        mock_rule_result.scalars.return_value.first.return_value = mock_rule

        # Core delete results (rowcount not required by service, but mocked)
        mock_delete_events_result = MagicMock()
        mock_delete_events_result.rowcount = 0
        mock_delete_rule_result = MagicMock()
        mock_delete_rule_result.rowcount = 1

        mock_session.execute.side_effect = [
            mock_rule_result,
            mock_delete_events_result,
            mock_delete_rule_result,
        ]

        result = await service.delete_rule(rule_id=11)

        assert result is True
        # SELECT + DELETE events + DELETE rule = 3 execute calls
        assert mock_session.execute.call_count == 3
        mock_pool.session_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_rule_with_events_deletes_events_before_rule(self, service, mock_pool):
        """Rule with events: MUST delete events BEFORE rule (FK NO ACTION).

        This is the regression test for the 500 error. The fix must issue
        DELETE FROM alert_events WHERE rule_id=? BEFORE
        DELETE FROM alert_rules WHERE id=?, in the same transaction.
        """
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.commit = AsyncMock()

        mock_rule = MagicMock()
        mock_rule.id = 11
        mock_rule_result = MagicMock()
        mock_rule_result.scalars.return_value.first.return_value = mock_rule

        # 3 events to be deleted first
        mock_delete_events_result = MagicMock()
        mock_delete_events_result.rowcount = 3
        mock_delete_rule_result = MagicMock()
        mock_delete_rule_result.rowcount = 1

        mock_session.execute.side_effect = [
            mock_rule_result,
            mock_delete_events_result,
            mock_delete_rule_result,
        ]

        result = await service.delete_rule(rule_id=11)

        assert result is True
        assert mock_session.execute.call_count == 3

        # Verify statement ordering by inspecting compiled SQL.
        calls = mock_session.execute.call_args_list
        events_sql = str(calls[1].args[0].compile(compile_kwargs={"literal_binds": True})).lower()
        rule_sql = str(calls[2].args[0].compile(compile_kwargs={"literal_binds": True})).lower()

        # 2nd execute must be DELETE FROM alert_events
        assert "delete from alert_events" in events_sql
        assert "rule_id" in events_sql
        # 3rd execute must be DELETE FROM alert_rules
        assert "delete from alert_rules" in rule_sql

        mock_pool.session_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_rule_db_exception_propagates_without_commit(self, service, mock_pool):
        """DB exception during delete must propagate; commit must NOT run."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_rule = MagicMock()
        mock_rule.id = 11
        mock_rule_result = MagicMock()
        mock_rule_result.scalars.return_value.first.return_value = mock_rule

        mock_session.execute.side_effect = [
            mock_rule_result,
            RuntimeError("db connection lost"),
        ]

        with pytest.raises(RuntimeError, match="db connection lost"):
            await service.delete_rule(rule_id=11)

        mock_session.commit.assert_not_called()


# ── 8. Get Rule ──────────────────────────────────────────────────


class TestGetRule:
    """Tests for AlertService.get_rule()."""

    @pytest.mark.asyncio
    async def test_get_rule_found(self, service, mock_pool):
        """get_rule returns dict when rule exists."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_rule = MagicMock()
        mock_rule.id = 42
        mock_rule.entity_name = "TestEntity"
        mock_rule.metric = "reference_count"
        mock_rule.operator = "z_score>"
        mock_rule.threshold = 2.5
        mock_rule.channel = "webhook"
        mock_rule.cooldown_minutes = 30
        mock_rule.enabled = True
        mock_rule.trigger_type = None
        mock_rule.trend_window_days = None
        mock_rule.trend_threshold = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_rule
        mock_session.execute.return_value = mock_result

        result = await service.get_rule(42)

        assert result is not None
        assert result["id"] == 42
        assert result["entity_name"] == "TestEntity"
        assert result["threshold"] == 2.5

    @pytest.mark.asyncio
    async def test_get_rule_not_found(self, service, mock_pool):
        """get_rule returns None when rule doesn't exist."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.get_rule(999)

        assert result is None


# ── 9. List Rules ────────────────────────────────────────────────


class TestListRules:
    """Tests for AlertService.list_rules()."""

    @pytest.mark.asyncio
    async def test_list_rules_no_filter(self, service, mock_pool):
        """list_rules returns all rules when no filter."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_rule = MagicMock()
        mock_rule.id = 1
        mock_rule.entity_name = "Entity1"
        mock_rule.metric = "reference_count"
        mock_rule.operator = "z_score>"
        mock_rule.threshold = 2.0
        mock_rule.channel = "webhook"
        mock_rule.cooldown_minutes = 60
        mock_rule.enabled = True
        mock_rule.trigger_type = None
        mock_rule.trend_window_days = None
        mock_rule.trend_threshold = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_rule]
        mock_session.execute.return_value = mock_result

        result = await service.list_rules()

        assert len(result) == 1
        assert result[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_list_rules_with_entity_filter(self, service, mock_pool):
        """list_rules filters by entity_name."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await service.list_rules(entity_name="NonExistent")

        assert result == []

    @pytest.mark.asyncio
    async def test_list_rules_enabled_only(self, service, mock_pool):
        """list_rules filters enabled only."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await service.list_rules(enabled_only=True)

        assert result == []


# ── 10. Update Rule ──────────────────────────────────────────────


class TestUpdateRule:
    """Tests for AlertService.update_rule()."""

    @pytest.mark.asyncio
    async def test_update_rule_found(self, service, mock_pool):
        """update_rule updates fields and returns dict."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.commit = AsyncMock()

        mock_rule = MagicMock()
        mock_rule.id = 1
        mock_rule.entity_name = "Updated"
        mock_rule.metric = "reference_count"
        mock_rule.operator = "z_score>"
        mock_rule.threshold = 3.0
        mock_rule.channel = "webhook"
        mock_rule.cooldown_minutes = 60
        mock_rule.enabled = True
        mock_rule.trigger_type = None
        mock_rule.trend_window_days = None
        mock_rule.trend_threshold = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_rule
        mock_session.execute.return_value = mock_result

        result = await service.update_rule(1, threshold=3.0, enabled=False)

        assert result is not None
        assert result["id"] == 1
        mock_pool.session_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_rule_not_found(self, service, mock_pool):
        """update_rule returns None when rule doesn't exist."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.update_rule(999, threshold=3.0)

        assert result is None


# ── 11. Trigger Alert — disabled rule ────────────────────────────


class TestTriggerAlertDisabledRule:
    """Tests for trigger_alert with disabled/missing rules."""

    @pytest.mark.asyncio
    async def test_trigger_alert_disabled_rule_returns_none(self, service, mock_pool):
        """Disabled rule should not trigger an alert."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_rule = MagicMock()
        mock_rule.enabled = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_rule
        mock_session.execute.return_value = mock_result

        result = await service.trigger_alert(rule_id=1, metric_value=5.0)

        assert result is None
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_trigger_alert_missing_rule_returns_none(self, service, mock_pool):
        """Missing rule should return None."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service.trigger_alert(rule_id=999, metric_value=5.0)

        assert result is None


# ── 12. List Events ──────────────────────────────────────────────


class TestListEvents:
    """Tests for AlertService.list_events()."""

    @pytest.mark.asyncio
    async def test_list_events_no_filter(self, service, mock_pool):
        """list_events returns all events."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_event = MagicMock()
        mock_event.id = 1
        mock_event.rule_id = 1
        mock_event.entity_name = "TestEntity"
        mock_event.metric_value = 3.5
        mock_event.triggered_at = datetime(2026, 1, 1, tzinfo=UTC)
        mock_event.acknowledged_at = None
        mock_event.detail = {"z_score": 3.5}

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]
        mock_session.execute.return_value = mock_result

        result = await service.list_events()

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["acknowledged_at"] is None

    @pytest.mark.asyncio
    async def test_list_events_with_rule_id_filter(self, service, mock_pool):
        """list_events filters by rule_id."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await service.list_events(rule_id=42)

        assert result == []

    @pytest.mark.asyncio
    async def test_list_events_with_entity_filter(self, service, mock_pool):
        """list_events filters by entity_name."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await service.list_events(entity_name="TestEntity")

        assert result == []

    @pytest.mark.asyncio
    async def test_list_events_acknowledged_filter(self, service, mock_pool):
        """list_events filters by acknowledged status."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await service.list_events(acknowledged=True)

        assert result == []

    @pytest.mark.asyncio
    async def test_list_events_unacknowledged_filter(self, service, mock_pool):
        """list_events filters by unacknowledged status."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await service.list_events(acknowledged=False)

        assert result == []


# ── 13. Evaluate unknown operator ────────────────────────────────


class TestEvaluateUnknownOperator:
    """Tests for evaluate_condition with unknown operators."""

    def test_unknown_operator_returns_false(self, service):
        """Unknown operator should never trigger."""
        result = service.evaluate_condition(
            operator="unknown_op",
            threshold=1.0,
            current_value=100.0,
        )
        assert result is False


# ── Update Rule Field Whitelist ───────────────────────────────────


class TestUpdateRuleFieldWhitelist:
    """update_rule must restrict setattr to an explicit field allowlist (#49)."""

    @pytest.fixture
    def mock_update_session(self, mock_pool):
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_rule = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_rule
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        return mock_session, mock_rule

    @pytest.mark.asyncio
    async def test_updatable_field_is_set(self, service, mock_pool, mock_update_session):
        mock_session, mock_rule = mock_update_session
        mock_rule.id = 1

        await service.update_rule(1, enabled=False, threshold=5.0)

        assert mock_rule.enabled is False
        assert mock_rule.threshold == 5.0
        mock_pool.session_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_whitelisted_field_rejected(self, service, mock_pool, mock_update_session):
        mock_session, mock_rule = mock_update_session
        sentinel = object()
        mock_rule.id = sentinel
        mock_rule.attribute_set = MagicMock()

        with patch("modules.analytics.alert_service.log") as mock_log:
            await service.update_rule(1, attribute_set="evil", enabled=True)

        mock_rule.attribute_set.assert_not_called()
        assert mock_rule.enabled is True
        mock_log.warning.assert_called()
        mock_pool.session_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_nonexistent_rule_returns_none(self, service, mock_pool):
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        assert await service.update_rule(42, enabled=False) is None
