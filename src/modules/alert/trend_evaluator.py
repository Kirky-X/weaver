# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Trend alert evaluator — evaluates trend rules and triggers alert events (T018 / R-alert-002,004).

TrendAlertEvaluator is the core engine for C6 trend alerting. It runs
hourly (T019 scheduler integration) and evaluates all enabled trend rules
(trigger_type ∈ {trend_spike, trend_drop, sentiment_shift}) against the
latest trend data:

- trend_spike: TrendDetectionProtocol.detect_trends(window_days) → trigger
  when any trend.trend_score > rule.trend_threshold.
- trend_drop: TrendDetectionProtocol.detect_trends(window_days) → trigger
  when any trend.trend_score < -rule.trend_threshold.
- sentiment_shift (specific entity): SentimentTrendProtocol.analyze_trend(
  entity_name=rule.entity_name, window_days) → trigger when any
  |shift.shift_value| > rule.trend_threshold.
- sentiment_shift (wildcard '*'): SentimentTrendProtocol requires a
  specific entity_name (raises ValueError if both entity_name and
  community_id are None). For wildcard rules, the evaluator queries the
  sentiment_shifts table directly to fetch ALL shifts in the window across
  all entities. This is a pragmatic workaround for the analyzer's API
  limitation (Rule 7 — exposed: spec R-alert-002 says to call
  analyze_trend(window_days) without entity_name, but the analyzer
  requires at least one of entity_name/community_id).

24h dedup (R-alert-002):
    Before inserting an alert event, the evaluator checks for an existing
    event with the same (rule_id, payload_hash) within the last 24h.
    payload_hash = sha256(json.dumps(payload, sort_keys=True,
    ensure_ascii=False)). This prevents duplicate alerts for the same
    trend within 24h — the hourly scheduler would otherwise re-insert
    identical alerts every hour as long as the trend persists.

    Within-run dedup is also enforced via an in-memory set of
    (rule_id, payload_hash) tuples — if the same rule triggers multiple
    times for the same entity+payload in a single evaluate() call (e.g.
    detect_trends returns duplicate trends), only one alert is inserted.

Error isolation (R-alert-002 Constraints):
    A single rule failure (detector/analyzer exception, or DB error on
    dedup check) does NOT block other rules. The exception is logged at
    error level and the evaluator continues to the next rule. DB commit
    errors propagate (Rule 12 — fail loud).

Payload structure (R-alert-004):
    - trend_spike/trend_drop: {entity_name, trend_score, threshold, window_days}
    - sentiment_shift: {entity_name, shift_value, threshold, window_days}

Cross-database compatibility (Rule — PG + DuckDB):
    All queries use SQLAlchemy Core select() with parameter binding.
    DateTime math uses Python-side cutoff (datetime.now(UTC) - timedelta)
    rather than SQL interval functions to avoid dialect differences.

Constructor injection (Rule — Protocol types, not concrete classes):
    ``__init__(pool, trend_detector, sentiment_analyzer)`` accepts any
    pool implementing RelationalPool and any services implementing
    TrendDetectionProtocol / SentimentTrendProtocol.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from core.db.models.alert import AlertEvent, AlertRule
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool
    from core.protocols.services import SentimentTrendProtocol, TrendDetectionProtocol

log = get_logger(__name__)

# Trigger types evaluated by TrendAlertEvaluator.
_TREND_TRIGGER_TYPES: tuple[str, ...] = ("trend_spike", "trend_drop", "sentiment_shift")

# 24h dedup window (R-alert-002).
_DEDUP_WINDOW_HOURS: int = 24

# Wildcard entity_name — aggregates across all entities.
_WILDCARD_ENTITY: str = "*"


class TrendAlertEvaluator:
    """Evaluate trend alert rules and trigger alert events (R-alert-002,004).

    Implements: hourly trend alert evaluation (called by AlertJobs T019).

    Args:
        pool: RelationalPool implementation (PostgresPool or DuckDBPool).
            Used via ``pool.session_context()`` for all DB access — querying
            alert_rules, querying sentiment_shifts (wildcard path), dedup
            checks against alert_events, and inserting new alert_events.
        trend_detector: TrendDetectionProtocol implementation (TrendDetector
            T015). Called for trend_spike / trend_drop rules.
        sentiment_analyzer: SentimentTrendProtocol implementation
            (SentimentTrendAnalyzer T012). Called for sentiment_shift rules
            with specific entity_name (not wildcard).

    Raises:
        TypeError: If injected dependencies don't satisfy their Protocol
            (delegated to runtime_checkable Protocol check at call site).
    """

    def __init__(
        self,
        pool: RelationalPool,
        trend_detector: TrendDetectionProtocol,
        sentiment_analyzer: SentimentTrendProtocol,
    ) -> None:
        self._pool = pool
        self._trend_detector = trend_detector
        self._sentiment_analyzer = sentiment_analyzer

    async def evaluate(self) -> int:
        """Evaluate all enabled trend rules and insert alert events.

        Queries alert_rules WHERE enabled=true AND trigger_type IN
        ('trend_spike', 'trend_drop', 'sentiment_shift'). For each rule,
        calls the appropriate trend service and inserts alert_events for
        triggers that pass 24h dedup.

        Returns:
            Number of new alert_events inserted.

        Raises:
            Exception: On DB commit error (Rule 12 — fail loud). Per-rule
                detector/analyzer errors are caught and logged (error
                isolation), but commit errors propagate.
        """
        # Within-run dedup: (rule_id, payload_hash) tuples already inserted.
        inserted_keys: set[tuple[int, str]] = set()
        total_inserted = 0

        async with self._pool.session_context() as session:
            # 1. Query enabled trend rules.
            result = await session.execute(
                select(AlertRule).where(
                    AlertRule.enabled.is_(True),
                    AlertRule.trigger_type.in_(_TREND_TRIGGER_TYPES),
                )
            )
            rules = result.scalars().all()

            log.info(
                "trend_alert_evaluate_start",
                rule_count=len(rules),
                trigger_types=_TREND_TRIGGER_TYPES,
            )

            # 2. Evaluate each rule (error isolation per rule).
            for rule in rules:
                try:
                    triggers = await self._evaluate_rule(rule)
                    # 3. For each trigger: dedup check + insert.
                    for trigger in triggers:
                        dedup_key = (rule.id, trigger["payload_hash"])
                        if dedup_key in inserted_keys:
                            # Within-run dedup — skip.
                            continue

                        # DB dedup: check alert_events for same payload_hash in 24h.
                        cutoff = datetime.now(UTC) - timedelta(hours=_DEDUP_WINDOW_HOURS)
                        dedup_result = await session.execute(
                            select(AlertEvent.id)
                            .where(
                                AlertEvent.rule_id == rule.id,
                                AlertEvent.payload_hash == trigger["payload_hash"],
                                AlertEvent.triggered_at > cutoff,
                            )
                            .limit(1)
                        )
                        if dedup_result.scalars().first() is not None:
                            # 24h dedup — skip.
                            continue

                        # Insert alert event.
                        session.add(
                            AlertEvent(
                                rule_id=rule.id,
                                entity_name=trigger["entity_name"],
                                metric_value=trigger["metric_value"],
                                triggered_at=datetime.now(UTC),
                                detail=trigger["payload"],
                                payload_hash=trigger["payload_hash"],
                            )
                        )
                        inserted_keys.add(dedup_key)
                        total_inserted += 1
                except Exception as exc:
                    # Error isolation: log and continue to next rule.
                    # Per-rule exceptions (detector/analyzer/DB) do NOT block
                    # other rules (R-alert-002 Constraints).
                    log.error(
                        "trend_alert_rule_evaluation_failed",
                        rule_id=rule.id,
                        trigger_type=rule.trigger_type,
                        error=str(exc),
                        exc_type=type(exc).__name__,
                    )
                    continue

            # Commit all inserts (single transaction).
            await session.commit()

        log.info(
            "trend_alert_evaluate_complete",
            rule_count=len(rules),
            events_inserted=total_inserted,
        )
        return total_inserted

    async def _evaluate_rule(self, rule: AlertRule) -> list[dict[str, Any]]:
        """Evaluate a single rule and return trigger payloads.

        Args:
            rule: AlertRule with trigger_type ∈ {trend_spike, trend_drop,
                sentiment_shift}.

        Returns:
            List of trigger dicts, each containing:
            - entity_name: Entity that triggered the alert.
            - metric_value: trend_score or shift_value (float).
            - payload: Dict matching R-alert-004 structure.
            - payload_hash: sha256 hex digest of normalized payload.

        Raises:
            Exception: On detector/analyzer error (Rule 12 — propagate to
                caller for error isolation handling).
            ValueError: If rule.trend_window_days or rule.trend_threshold
                is None (defensive — CHECK constraint should prevent this).
        """
        # Defensive validation — CHECK constraint chk_alert_trend_fields_required
        # ensures trend rules have both fields, but validate anyway.
        if rule.trend_window_days is None or rule.trend_threshold is None:
            raise ValueError(
                f"Rule {rule.id} (trigger_type={rule.trigger_type}) has "
                f"trend_window_days={rule.trend_window_days}, "
                f"trend_threshold={rule.trend_threshold}. Both must be non-NULL "
                f"for trend rules (CHECK constraint chk_alert_trend_fields_required)."
            )

        threshold = float(rule.trend_threshold)
        window_days = int(rule.trend_window_days)

        if rule.trigger_type in ("trend_spike", "trend_drop"):
            return await self._evaluate_trend_rule(
                rule=rule,
                threshold=threshold,
                window_days=window_days,
            )
        elif rule.trigger_type == "sentiment_shift":
            return await self._evaluate_sentiment_rule(
                rule=rule,
                threshold=threshold,
                window_days=window_days,
            )
        else:
            # Should not happen — query filters by trigger_type IN _TREND_TRIGGER_TYPES.
            log.warning(
                "trend_alert_unexpected_trigger_type",
                rule_id=rule.id,
                trigger_type=rule.trigger_type,
            )
            return []

    async def _evaluate_trend_rule(
        self,
        *,
        rule: AlertRule,
        threshold: float,
        window_days: int,
    ) -> list[dict[str, Any]]:
        """Evaluate trend_spike or trend_drop rule via TrendDetectionProtocol.

        Args:
            rule: AlertRule with trigger_type ∈ {trend_spike, trend_drop}.
            threshold: rule.trend_threshold as float.
            window_days: rule.trend_window_days as int.

        Returns:
            List of trigger dicts for trends exceeding the threshold.
        """
        # entity_type: None for wildcard (aggregate all), specific name otherwise.
        entity_type = None if rule.entity_name == _WILDCARD_ENTITY else rule.entity_name

        result = await self._trend_detector.detect_trends(
            window_days=window_days,
            entity_type=entity_type,
        )

        triggers: list[dict[str, Any]] = []
        for trend in result.trends:
            trend_score = float(trend["trend_score"])
            entity_name = trend["entity_name"]

            # Determine if this trend triggers the rule.
            triggered = False
            if rule.trigger_type == "trend_spike":
                # Spike: score > threshold (positive trend exceeds threshold).
                if trend_score > threshold:
                    triggered = True
            elif rule.trigger_type == "trend_drop":
                # Drop: score < -threshold (negative trend exceeds threshold).
                if trend_score < -threshold:
                    triggered = True

            if not triggered:
                continue

            payload = {
                "entity_name": entity_name,
                "trend_score": trend_score,
                "threshold": threshold,
                "window_days": window_days,
            }
            triggers.append(self._build_trigger(entity_name, trend_score, payload))

        return triggers

    async def _evaluate_sentiment_rule(
        self,
        *,
        rule: AlertRule,
        threshold: float,
        window_days: int,
    ) -> list[dict[str, Any]]:
        """Evaluate sentiment_shift rule via SentimentTrendProtocol or direct query.

        For specific entity_name (not '*'): calls SentimentTrendProtocol.
        analyze_trend(entity_name=rule.entity_name, window_days=...).

        For wildcard entity_name='*': queries sentiment_shifts table directly
        (SentimentTrendProtocol requires a specific entity_name, so wildcard
        bypasses the analyzer). This is a documented Rule 7 conflict — spec
        R-alert-002 says to call analyze_trend(window_days) without entity_name,
        but the analyzer raises ValueError if both entity_name and community_id
        are None.

        Args:
            rule: AlertRule with trigger_type='sentiment_shift'.
            threshold: rule.trend_threshold as float.
            window_days: rule.trend_window_days as int.

        Returns:
            List of trigger dicts for shifts exceeding the threshold.
        """
        if rule.entity_name == _WILDCARD_ENTITY:
            # Wildcard: query sentiment_shifts table directly (all entities).
            shifts = await self._query_all_shifts(window_days)
        else:
            # Specific entity: use the analyzer.
            result = await self._sentiment_analyzer.analyze_trend(
                entity_name=rule.entity_name,
                window_days=window_days,
            )
            shifts = result.shifts

        triggers: list[dict[str, Any]] = []
        for shift in shifts:
            shift_value = float(shift["shift_value"])
            entity_name = shift["entity_name"]

            # |shift_value| > threshold → trigger.
            if abs(shift_value) <= threshold:
                continue

            payload = {
                "entity_name": entity_name,
                "shift_value": shift_value,
                "threshold": threshold,
                "window_days": window_days,
            }
            triggers.append(self._build_trigger(entity_name, shift_value, payload))

        return triggers

    async def _query_all_shifts(self, window_days: int) -> list[dict[str, Any]]:
        """Query all sentiment_shifts in the window (wildcard path).

        Mirrors SentimentTrendAnalyzer's query but without entity_name filter:
        - article_id IS NOT NULL (article-level shifts only)
        - shift_value IS NOT NULL (must have signed shift)
        - detected_at >= cutoff (within window_days)

        Args:
            window_days: Time window in days.

        Returns:
            List of shift dicts with entity_name and shift_value keys.
        """
        cutoff = datetime.now(UTC) - timedelta(days=window_days)

        async with self._pool.session_context() as session:
            from core.db import SentimentShift as SentimentShiftModel

            query = (
                select(SentimentShiftModel)
                .where(SentimentShiftModel.article_id.is_not(None))
                .where(SentimentShiftModel.shift_value.is_not(None))
                .where(SentimentShiftModel.detected_at >= cutoff)
            )
            result = await session.execute(query)
            rows = result.scalars().all()

        return [
            {
                "entity_name": row.entity_name,
                "shift_value": float(row.shift_value),
                "article_id": str(row.article_id) if row.article_id else None,
            }
            for row in rows
        ]

    @staticmethod
    def _build_trigger(
        entity_name: str,
        metric_value: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a trigger dict with normalized payload and sha256 hash.

        Args:
            entity_name: Entity that triggered the alert.
            metric_value: trend_score or shift_value (for AlertEvent.metric_value).
            payload: Dict matching R-alert-004 structure.

        Returns:
            Dict with entity_name, metric_value, payload, payload_hash keys.
        """
        # Normalize payload: JSON keys sorted ascending, ensure_ascii=False.
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        payload_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        return {
            "entity_name": entity_name,
            "metric_value": metric_value,
            "payload": payload,
            "payload_hash": payload_hash,
        }


__all__ = ["TrendAlertEvaluator"]
