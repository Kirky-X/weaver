# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for TrendAlertEvaluator (T018 / R-alert-002,004).

Verifies:
- trend_spike trigger: trend_score > threshold → alert event inserted
- trend_drop trigger: trend_score < -threshold → alert event inserted
- sentiment_shift trigger (specific entity): |shift_value| > threshold → alert
- sentiment_shift trigger (wildcard '*'): direct table query → alert per entity
- 24h dedup: existing event with same payload_hash in 24h → skip insert
- Error isolation: one rule failure does NOT block other rules
- Disabled rules (enabled=false) are skipped
- Threshold rules (trigger_type='threshold') are skipped
- Payload structure per R-alert-004:
    trend_spike/trend_drop: {entity_name, trend_score, threshold, window_days}
    sentiment_shift: {entity_name, shift_value, threshold, window_days}
- Payload normalization: JSON sorted by key, sha256 hash for dedup

Patch surface:
- pool.session_context() → yields mock session
- session.execute() → returns rule rows / dedup results / shift rows via side_effect
- session.add() → captures AlertEvent ORM instances
- trend_detector.detect_trends → AsyncMock returning TrendDetectionResult-like
- sentiment_analyzer.analyze_trend → AsyncMock returning SentimentTrendResult-like
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.alert.trend_evaluator import TrendAlertEvaluator
from tests.helpers import AsyncContextManagerMock

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_rule(
    *,
    id: int = 1,
    trigger_type: str = "trend_spike",
    entity_name: str = "*",
    trend_window_days: int = 7,
    trend_threshold: float = 0.5,
    enabled: bool = True,
) -> SimpleNamespace:
    """Build a mock AlertRule-like row."""
    return SimpleNamespace(
        id=id,
        trigger_type=trigger_type,
        entity_name=entity_name,
        trend_window_days=trend_window_days,
        trend_threshold=Decimal(str(trend_threshold)),
        enabled=enabled,
    )


def _make_trend(
    *,
    entity_name: str = "Company A",
    trend_score: float = 0.7,
    direction: str = "up",
) -> dict:
    """Build a trend dict matching TrendDetectionResult.trends shape."""
    return {
        "entity_name": entity_name,
        "trend_score": trend_score,
        "direction": direction,
        "frequency_change": trend_score,
        "current_count": 10,
        "previous_count": 3,
    }


def _make_trend_result(
    *,
    trends: list[dict] | None = None,
    status: str = "ok",
) -> SimpleNamespace:
    """Build a TrendDetectionResult-like object."""
    return SimpleNamespace(
        trends=trends or [],
        status=status,
        window_days=7,
        entity_type=None,
        list=[],
    )


def _make_shift_row(
    *,
    entity_name: str = "Company A",
    shift_value: float = 0.6,
    detected_at: datetime | None = None,
    article_id: str | None = "00000000-0000-0000-0000-000000000001",
) -> SimpleNamespace:
    """Build a mock SentimentShift ORM row."""
    return SimpleNamespace(
        entity_name=entity_name,
        shift_value=shift_value,
        before_avg=0.50,
        after_avg=0.65,
        detected_at=detected_at or datetime.now(UTC),
        article_id=article_id,
        community_id=entity_name,
    )


def _make_sentiment_result(
    *,
    shifts: list[dict] | None = None,
    avg_shift: float = 0.0,
    trend_direction: str = "stable",
) -> SimpleNamespace:
    """Build a SentimentTrendResult-like object."""
    return SimpleNamespace(
        shifts=shifts or [],
        avg_shift=avg_shift,
        trend_direction=trend_direction,
        entity_name="Company A",
        window_days=7,
        list=[],
    )


def _make_session(execute_results: list) -> MagicMock:
    """Build a mock session with sequential execute() results.

    Args:
        execute_results: List of results returned by session.execute() in order.
    """
    session = MagicMock()
    session.execute = AsyncMock(side_effect=list(execute_results))
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _make_pool(session: MagicMock) -> MagicMock:
    """Build a mock RelationalPool yielding the given session."""
    pool = MagicMock()
    pool.session_context = MagicMock(return_value=AsyncContextManagerMock(session))
    return pool


def _make_rule_result(rules: list) -> MagicMock:
    """Build a session.execute() result for SELECT alert_rules."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rules
    return result


def _make_dedup_result_empty() -> MagicMock:
    """Build a session.execute() result for dedup check (no existing event)."""
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    return result


def _make_dedup_result_existing() -> MagicMock:
    """Build a session.execute() result for dedup check (existing event)."""
    result = MagicMock()
    result.scalars.return_value.first.return_value = SimpleNamespace(id=999)
    return result


def _make_shift_rows_result(rows: list) -> MagicMock:
    """Build a session.execute() result for SELECT sentiment_shifts (wildcard)."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _make_trend_detector(trend_result=None) -> MagicMock:
    """Build a mock TrendDetectionProtocol."""
    detector = MagicMock()
    detector.detect_trends = AsyncMock(return_value=trend_result or _make_trend_result())
    return detector


def _make_sentiment_analyzer(sentiment_result=None) -> MagicMock:
    """Build a mock SentimentTrendProtocol."""
    analyzer = MagicMock()
    analyzer.analyze_trend = AsyncMock(return_value=sentiment_result or _make_sentiment_result())
    return analyzer


def _expected_payload_hash(payload: dict) -> str:
    """Compute expected payload_hash for assertion."""
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ── trend_spike trigger ─────────────────────────────────────────────────────


class TestTrendSpikeTrigger:
    """Tests for trend_spike trigger_type (R-alert-002, R-alert-004)."""

    @pytest.mark.asyncio
    async def test_trend_spike_triggers_when_score_above_threshold(self) -> None:
        """trend_spike: trend_score > threshold → alert event inserted."""
        rule = _make_rule(
            trigger_type="trend_spike",
            trend_threshold=0.5,
            trend_window_days=7,
        )
        trend = _make_trend(entity_name="Company A", trend_score=0.7, direction="up")
        trend_result = _make_trend_result(trends=[trend], status="ok")

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)
        analyzer = _make_sentiment_analyzer()

        evaluator = TrendAlertEvaluator(pool, detector, analyzer)
        count = await evaluator.evaluate()

        assert count == 1
        assert session.add.call_count == 1
        # Verify detect_trends called with correct window_days
        detector.detect_trends.assert_awaited_once()
        call_kwargs = detector.detect_trends.call_args.kwargs
        assert call_kwargs["window_days"] == 7

    @pytest.mark.asyncio
    async def test_trend_spike_does_not_trigger_when_score_below_threshold(self) -> None:
        """trend_spike: trend_score <= threshold → no alert."""
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5)
        trend = _make_trend(trend_score=0.3, direction="up")  # below 0.5
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule])])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 0
        assert session.add.call_count == 0

    @pytest.mark.asyncio
    async def test_trend_spike_payload_structure(self) -> None:
        """trend_spike payload must contain entity_name, trend_score, threshold, window_days (R-alert-004)."""
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5, trend_window_days=7)
        trend = _make_trend(entity_name="Company A", trend_score=0.7)
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        await evaluator.evaluate()

        # Verify the AlertEvent was added with correct payload
        added_event = session.add.call_args[0][0]
        assert added_event.entity_name == "Company A"
        assert float(added_event.metric_value) == 0.7
        assert added_event.rule_id == rule.id
        assert added_event.payload_hash is not None
        assert len(added_event.payload_hash) == 64  # sha256 hex
        # Verify payload dict structure
        detail = added_event.detail
        assert detail["entity_name"] == "Company A"
        assert detail["trend_score"] == 0.7
        assert detail["threshold"] == 0.5
        assert detail["window_days"] == 7

    @pytest.mark.asyncio
    async def test_trend_spike_wildcard_passes_entity_type_none(self) -> None:
        """trend_spike with entity_name='*' → detect_trends(entity_type=None)."""
        rule = _make_rule(trigger_type="trend_spike", entity_name="*")
        trend_result = _make_trend_result(trends=[])

        session = _make_session([_make_rule_result([rule])])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        await evaluator.evaluate()

        call_kwargs = detector.detect_trends.call_args.kwargs
        assert call_kwargs["entity_type"] is None

    @pytest.mark.asyncio
    async def test_trend_spike_specific_entity_passes_entity_type(self) -> None:
        """trend_spike with entity_name='Company A' → detect_trends(entity_type='Company A')."""
        rule = _make_rule(trigger_type="trend_spike", entity_name="Company A")
        trend_result = _make_trend_result(trends=[])

        session = _make_session([_make_rule_result([rule])])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        await evaluator.evaluate()

        call_kwargs = detector.detect_trends.call_args.kwargs
        assert call_kwargs["entity_type"] == "Company A"


# ── trend_drop trigger ──────────────────────────────────────────────────────


class TestTrendDropTrigger:
    """Tests for trend_drop trigger_type (R-alert-002)."""

    @pytest.mark.asyncio
    async def test_trend_drop_triggers_when_score_below_negative_threshold(self) -> None:
        """trend_drop: trend_score < -threshold → alert event inserted."""
        rule = _make_rule(trigger_type="trend_drop", trend_threshold=0.5)
        trend = _make_trend(entity_name="Company B", trend_score=-0.7, direction="down")
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 1
        assert session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_trend_drop_does_not_trigger_when_score_above_negative_threshold(self) -> None:
        """trend_drop: trend_score >= -threshold → no alert."""
        rule = _make_rule(trigger_type="trend_drop", trend_threshold=0.5)
        trend = _make_trend(trend_score=-0.3, direction="down")  # > -0.5
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule])])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 0
        assert session.add.call_count == 0

    @pytest.mark.asyncio
    async def test_trend_drop_does_not_trigger_on_positive_score(self) -> None:
        """trend_drop: positive trend_score never triggers drop alert."""
        rule = _make_rule(trigger_type="trend_drop", trend_threshold=0.5)
        trend = _make_trend(trend_score=0.7, direction="up")  # positive, not drop
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule])])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 0


# ── sentiment_shift trigger ─────────────────────────────────────────────────


class TestSentimentShiftTrigger:
    """Tests for sentiment_shift trigger_type (R-alert-002, R-alert-004)."""

    @pytest.mark.asyncio
    async def test_sentiment_shift_triggers_specific_entity(self) -> None:
        """sentiment_shift with specific entity: |shift_value| > threshold → alert."""
        rule = _make_rule(
            trigger_type="sentiment_shift",
            entity_name="Company A",
            trend_threshold=0.3,
            trend_window_days=7,
        )
        shift = {
            "entity_name": "Company A",
            "shift_value": 0.5,
            "article_id": "art-1",
        }
        sentiment_result = _make_sentiment_result(shifts=[shift], avg_shift=0.5)

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        analyzer = _make_sentiment_analyzer(sentiment_result)

        evaluator = TrendAlertEvaluator(pool, _make_trend_detector(), analyzer)
        count = await evaluator.evaluate()

        assert count == 1
        assert session.add.call_count == 1
        analyzer.analyze_trend.assert_awaited_once_with(entity_name="Company A", window_days=7)

    @pytest.mark.asyncio
    async def test_sentiment_shift_does_not_trigger_when_shift_below_threshold(self) -> None:
        """sentiment_shift: |shift_value| <= threshold → no alert."""
        rule = _make_rule(
            trigger_type="sentiment_shift",
            entity_name="Company A",
            trend_threshold=0.3,
        )
        shift = {"entity_name": "Company A", "shift_value": 0.2}  # below 0.3
        sentiment_result = _make_sentiment_result(shifts=[shift])

        session = _make_session([_make_rule_result([rule])])
        pool = _make_pool(session)
        analyzer = _make_sentiment_analyzer(sentiment_result)

        evaluator = TrendAlertEvaluator(pool, _make_trend_detector(), analyzer)
        count = await evaluator.evaluate()

        assert count == 0
        assert session.add.call_count == 0

    @pytest.mark.asyncio
    async def test_sentiment_shift_payload_structure(self) -> None:
        """sentiment_shift payload: {entity_name, shift_value, threshold, window_days} (R-alert-004)."""
        rule = _make_rule(
            trigger_type="sentiment_shift",
            entity_name="Company A",
            trend_threshold=0.3,
            trend_window_days=7,
        )
        shift = {"entity_name": "Company A", "shift_value": 0.5, "article_id": "a1"}
        sentiment_result = _make_sentiment_result(shifts=[shift])

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        analyzer = _make_sentiment_analyzer(sentiment_result)

        evaluator = TrendAlertEvaluator(pool, _make_trend_detector(), analyzer)
        await evaluator.evaluate()

        added_event = session.add.call_args[0][0]
        assert added_event.entity_name == "Company A"
        assert float(added_event.metric_value) == 0.5
        detail = added_event.detail
        assert detail["entity_name"] == "Company A"
        assert detail["shift_value"] == 0.5
        assert detail["threshold"] == 0.3
        assert detail["window_days"] == 7

    @pytest.mark.asyncio
    async def test_sentiment_shift_negative_value_triggers(self) -> None:
        """sentiment_shift: negative shift_value with |value| > threshold → alert."""
        rule = _make_rule(
            trigger_type="sentiment_shift",
            entity_name="Company A",
            trend_threshold=0.3,
        )
        shift = {"entity_name": "Company A", "shift_value": -0.5}
        sentiment_result = _make_sentiment_result(shifts=[shift])

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        analyzer = _make_sentiment_analyzer(sentiment_result)

        evaluator = TrendAlertEvaluator(pool, _make_trend_detector(), analyzer)
        count = await evaluator.evaluate()

        assert count == 1


# ── 24h dedup ───────────────────────────────────────────────────────────────


class TestTrendAlertDedup:
    """Tests for 24h dedup logic (R-alert-002)."""

    @pytest.mark.asyncio
    async def test_dedup_skips_when_same_payload_hash_exists_in_24h(self) -> None:
        """Existing event with same payload_hash in 24h → skip insert."""
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5)
        trend = _make_trend(entity_name="Company A", trend_score=0.7)
        trend_result = _make_trend_result(trends=[trend])

        # execute results: [rules, dedup_existing]
        session = _make_session([_make_rule_result([rule]), _make_dedup_result_existing()])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 0
        assert session.add.call_count == 0

    @pytest.mark.asyncio
    async def test_dedup_inserts_when_no_existing_payload_hash(self) -> None:
        """No existing event with same payload_hash → insert."""
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5)
        trend = _make_trend(entity_name="Company A", trend_score=0.7)
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 1
        assert session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_dedup_payload_hash_is_sha256_of_sorted_json(self) -> None:
        """payload_hash = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False))."""
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5, trend_window_days=7)
        trend = _make_trend(entity_name="Company A", trend_score=0.7)
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        await evaluator.evaluate()

        added_event = session.add.call_args[0][0]
        expected_payload = {
            "entity_name": "Company A",
            "trend_score": 0.7,
            "threshold": 0.5,
            "window_days": 7,
        }
        expected_hash = _expected_payload_hash(expected_payload)
        assert added_event.payload_hash == expected_hash

    @pytest.mark.asyncio
    async def test_dedup_within_run_same_entity_same_score(self) -> None:
        """Same rule triggering twice for same entity+score in one run → only 1 insert.

        Even if detect_trends returns duplicate trends (shouldn't happen but
        defensive), the evaluator should dedup within the run via payload_hash.
        """
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5)
        # Two identical trends (same entity, same score)
        trend = _make_trend(entity_name="Company A", trend_score=0.7)
        trend_result = _make_trend_result(trends=[trend, trend])

        # execute: [rules, dedup_empty, dedup_empty]
        session = _make_session(
            [
                _make_rule_result([rule]),
                _make_dedup_result_empty(),
                _make_dedup_result_empty(),
            ]
        )
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        # Only 1 inserted — second is deduped within run
        assert count == 1


# ── Error isolation ─────────────────────────────────────────────────────────


class TestTrendAlertErrorIsolation:
    """Tests for error isolation — one rule failure does NOT block others (R-alert-002)."""

    @pytest.mark.asyncio
    async def test_detector_exception_does_not_block_other_rules(self) -> None:
        """If detect_trends raises for rule 1, rule 2 still evaluates."""
        rule1 = _make_rule(id=1, trigger_type="trend_spike", trend_threshold=0.5)
        rule2 = _make_rule(id=2, trigger_type="trend_spike", trend_threshold=0.5)
        trend_ok = _make_trend(entity_name="Company B", trend_score=0.7)
        trend_result_ok = _make_trend_result(trends=[trend_ok])

        detector = MagicMock()
        detector.detect_trends = AsyncMock(
            side_effect=[RuntimeError("DB error for rule 1"), trend_result_ok]
        )

        # execute: [rules, dedup_empty_for_rule2]
        session = _make_session([_make_rule_result([rule1, rule2]), _make_dedup_result_empty()])
        pool = _make_pool(session)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        # Rule 1 failed (0 inserts), rule 2 succeeded (1 insert)
        assert count == 1
        assert detector.detect_trends.await_count == 2

    @pytest.mark.asyncio
    async def test_analyzer_exception_does_not_block_other_rules(self) -> None:
        """If analyze_trend raises for rule 1, rule 2 still evaluates."""
        # Use threshold=0.3 so |shift_value|=0.5 > 0.3 triggers the alert
        # (default threshold=0.5 would skip since abs(0.5) <= 0.5).
        rule1 = _make_rule(
            id=1,
            trigger_type="sentiment_shift",
            entity_name="Company A",
            trend_threshold=0.3,
        )
        rule2 = _make_rule(
            id=2,
            trigger_type="sentiment_shift",
            entity_name="Company B",
            trend_threshold=0.3,
        )
        shift_ok = {"entity_name": "Company B", "shift_value": 0.5}
        sentiment_result_ok = _make_sentiment_result(shifts=[shift_ok])

        analyzer = MagicMock()
        analyzer.analyze_trend = AsyncMock(
            side_effect=[RuntimeError("Analyzer error"), sentiment_result_ok]
        )

        session = _make_session([_make_rule_result([rule1, rule2]), _make_dedup_result_empty()])
        pool = _make_pool(session)

        evaluator = TrendAlertEvaluator(pool, _make_trend_detector(), analyzer)
        count = await evaluator.evaluate()

        assert count == 1
        assert analyzer.analyze_trend.await_count == 2

    @pytest.mark.asyncio
    async def test_db_error_on_insert_does_not_block_other_rules(self) -> None:
        """If session.commit raises (DB error), evaluator propagates (Rule 12).

        Note: The evaluator uses a single session for all rules. If commit
        fails, the error propagates. Error isolation is at the rule level
        (detector/analyzer exceptions), not at the DB commit level.
        """
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5)
        trend = _make_trend(trend_score=0.7)
        trend_result = _make_trend_result(trends=[trend])

        session = _make_session([_make_rule_result([rule]), _make_dedup_result_empty()])
        session.commit = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        # DB commit error propagates (Rule 12: fail loud)
        with pytest.raises(RuntimeError, match="DB connection lost"):
            await evaluator.evaluate()


# ── Rule filtering ──────────────────────────────────────────────────────────


class TestTrendAlertRuleFiltering:
    """Tests for rule filtering — disabled and threshold rules are skipped."""

    @pytest.mark.asyncio
    async def test_disabled_rules_are_skipped(self) -> None:
        """Rules with enabled=false are not evaluated."""
        rule = _make_rule(trigger_type="trend_spike", enabled=False)
        trend_result = _make_trend_result(trends=[])

        session = _make_session([_make_rule_result([])])  # empty rules list
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 0
        # detect_trends should NOT be called (no rules to evaluate)
        detector.detect_trends.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_threshold_rules_are_skipped(self) -> None:
        """Rules with trigger_type='threshold' are not evaluated by TrendAlertEvaluator."""
        # The query filters trigger_type IN ('trend_spike','trend_drop','sentiment_shift'),
        # so threshold rules never appear in the result set.
        session = _make_session([_make_rule_result([])])  # empty (filtered out)
        pool = _make_pool(session)
        detector = _make_trend_detector()

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 0
        detector.detect_trends.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_rules_returns_zero(self) -> None:
        """Empty rules list → 0 events inserted."""
        session = _make_session([_make_rule_result([])])
        pool = _make_pool(session)

        evaluator = TrendAlertEvaluator(pool, _make_trend_detector(), _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 0


# ── Multiple triggers ───────────────────────────────────────────────────────


class TestTrendAlertMultipleTriggers:
    """Tests for multiple triggers in a single evaluate() call."""

    @pytest.mark.asyncio
    async def test_multiple_trends_trigger_multiple_alerts(self) -> None:
        """Multiple trends exceeding threshold → multiple alert events."""
        rule = _make_rule(trigger_type="trend_spike", trend_threshold=0.5)
        trends = [
            _make_trend(entity_name="Company A", trend_score=0.7),
            _make_trend(entity_name="Company B", trend_score=0.8),
            _make_trend(entity_name="Company C", trend_score=0.3),  # below threshold
        ]
        trend_result = _make_trend_result(trends=trends)

        session = _make_session(
            [
                _make_rule_result([rule]),
                _make_dedup_result_empty(),  # Company A dedup
                _make_dedup_result_empty(),  # Company B dedup
            ]
        )
        pool = _make_pool(session)
        detector = _make_trend_detector(trend_result)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 2  # Company A + Company B (C below threshold)

    @pytest.mark.asyncio
    async def test_mixed_trigger_types_in_one_run(self) -> None:
        """Rules with different trigger_types are all evaluated in one run."""
        rule_spike = _make_rule(id=1, trigger_type="trend_spike", trend_threshold=0.5)
        rule_drop = _make_rule(id=2, trigger_type="trend_drop", trend_threshold=0.5)

        trend_up = _make_trend(entity_name="Company A", trend_score=0.7)
        trend_down = _make_trend(entity_name="Company B", trend_score=-0.7)

        detector = MagicMock()
        detector.detect_trends = AsyncMock(
            side_effect=[
                _make_trend_result(trends=[trend_up]),
                _make_trend_result(trends=[trend_down]),
            ]
        )

        session = _make_session(
            [
                _make_rule_result([rule_spike, rule_drop]),
                _make_dedup_result_empty(),  # spike dedup
                _make_dedup_result_empty(),  # drop dedup
            ]
        )
        pool = _make_pool(session)

        evaluator = TrendAlertEvaluator(pool, detector, _make_sentiment_analyzer())
        count = await evaluator.evaluate()

        assert count == 2
