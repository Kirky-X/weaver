# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Trend detector — implements TrendDetectionProtocol (T015 / R-trend-002,003,005).

TrendDetector queries EventNode frequency over a time window, computes
per-entity frequency_change (current vs previous window), and optionally
blends sentiment contribution from SentimentTrendProtocol to produce a
trend_score. The detector returns:

- ``status='ok'`` when EventNode count >= 50 (R-trend-002 threshold).
- ``status='insufficient_data'`` when < 50 (R-trend-003). This is NOT an
  error — the detector returns this explicitly rather than raising
  (Rule 12: fail visible, but data insufficiency is a legitimate state).

Trend score formula (R-trend-005):
    trend_score = 0.6 * frequency_change + 0.4 * sentiment_change
    When sentiment data is unavailable (analyzer is None OR the analyzer
    returns empty shifts for the entity), trend_score degenerates to
    frequency_change alone. Degradation is per-entity, not global.

Direction thresholds (R-trend-005):
    trend_score > 0.2  → 'up'
    trend_score < -0.2 → 'down'
    otherwise         → 'stable'

Cross-database compatibility (Rule — Neo4j + LadybugDB):
    Neo4j stores EventNode.created_at as datetime; LadybugDB stores it as
    INT64 epoch seconds (ladybug_schema.py). TrendDetector detects
    ``pool.database_type == 'ladybug'`` (temporal.py pattern) and:
    - Generates different Cypher time predicates (datetime() vs INT64).
    - Parses returned created_at values into datetime via _parse_timestamp
      (handles both datetime objects and INT64 epoch ints).

Constructor injection (Rule — Protocol type, not concrete class):
    ``__init__(self, graph_pool: GraphPool, sentiment_analyzer: SentimentTrendProtocol | None = None)``
    accepts any pool implementing GraphPool (Neo4jPool / LadybugPool) and
    optionally any analyzer implementing SentimentTrendProtocol.

Spec conflict (Rule 7 — exposed):
    spec/tasks say "按 entity_type 过滤", but EventNode schema field is
    ``name`` (not ``event_type``). Implementation uses ``e.name`` for the
    filter — the ``entity_type`` parameter name is kept for API/spec
    compatibility (R-trend-002), internally mapped to EventNode.name.

Failure handling (Rule 12 — fail loud):
    Graph DB errors and sentiment analyzer errors propagate to the caller.
    The insufficient-data case is NOT an error — it returns the explicit
    status. Validation errors (invalid window_days) raise ValueError
    before touching the DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.trend.models import TrendDetectionResult

if TYPE_CHECKING:
    from core.protocols import GraphPool
    from core.protocols.services import SentimentTrendProtocol

log = get_logger(__name__)

# Spec R-trend-001 constraints: only 7 and 30 days are supported.
_SUPPORTED_WINDOW_DAYS: frozenset[int] = frozenset({7, 30})

# R-trend-003: minimum EventNode count to produce trends.
_MIN_EVENT_COUNT: int = 50

# R-trend-005: trend score weights.
_FREQ_WEIGHT: float = 0.6
_SENTIMENT_WEIGHT: float = 0.4

# R-trend-005: direction thresholds.
_UP_THRESHOLD: float = 0.2
_DOWN_THRESHOLD: float = -0.2


class TrendDetector:
    """Detect trending entities over a time window (R-trend-001).

    Implements: TrendDetectionProtocol (core.protocols.services)

    Args:
        graph_pool: GraphPool implementation (Neo4jPool or LadybugPool).
            Used via ``pool.execute_query()`` for all graph DB access.
        sentiment_analyzer: Optional SentimentTrendProtocol for sentiment
            contribution to trend_score. None disables sentiment blending
            (trend_score degenerates to frequency_change alone).

    Raises:
        TypeError: If graph_pool does not implement GraphPool (delegated
            to runtime_checkable Protocol check at call site).
    """

    def __init__(
        self,
        graph_pool: GraphPool,
        sentiment_analyzer: SentimentTrendProtocol | None = None,
    ) -> None:
        self._pool = graph_pool
        self._analyzer = sentiment_analyzer
        # Detect LadybugDB for cross-database Cypher syntax (temporal.py pattern).
        # GraphPool Protocol does not declare database_type, but both Neo4jPool
        # and LadybugPool expose it (concrete impl detail). getattr fallback
        # keeps the Protocol pure while enabling branch selection.
        self._is_ladybug = getattr(graph_pool, "database_type", None) == "ladybug"

    async def detect_trends(
        self,
        window_days: int = 7,
        entity_type: str | None = None,
    ) -> TrendDetectionResult:
        """Detect trending entities over a time window (R-trend-002/003).

        Args:
            window_days: Time window in days — MUST be 7 or 30 per spec.
            entity_type: Optional EventNode.name filter (R-trend-002).
                None aggregates across all entity types.

        Returns:
            TrendDetectionResult with per-entity trends, aggregated
            MENTIONS heat time-series, and status.

        Raises:
            ValueError: If window_days is not in {7, 30}.
            Exception: On graph DB or sentiment analyzer error (Rule 12).
        """
        # Validate inputs BEFORE touching the DB (cheap-fail principle).
        if window_days not in _SUPPORTED_WINDOW_DAYS:
            raise ValueError(
                f"window_days must be one of {sorted(_SUPPORTED_WINDOW_DAYS)}, got {window_days}."
            )

        now = datetime.now(UTC)
        # Query [now - 2*window_days, now] so we can split into current +
        # previous windows Python-side (avoids 2 DB round-trips).
        cutoff_start = now - timedelta(days=2 * window_days)
        boundary = now - timedelta(days=window_days)

        rows = await self._query_events(
            cutoff_start=cutoff_start,
            entity_type=entity_type,
        )

        # R-trend-003: insufficient data is NOT an error — return explicit status.
        if len(rows) < _MIN_EVENT_COUNT:
            log.info(
                "trend_detection_insufficient_data",
                event_count=len(rows),
                threshold=_MIN_EVENT_COUNT,
                window_days=window_days,
                entity_type=entity_type,
            )
            return TrendDetectionResult(
                window_days=window_days,
                entity_type=entity_type,
                trends=[],
                list=[],
                status="insufficient_data",
            )

        # Bucket events into current + previous windows, per entity name.
        current_counts: dict[str, int] = {}
        previous_counts: dict[str, int] = {}
        all_rows_for_list = list(rows)  # keep for MENTIONS aggregation

        for row in rows:
            name = row.get("name")
            if name is None:
                continue
            created_at = self._parse_timestamp(row.get("created_at"))
            if created_at >= boundary:
                current_counts[name] = current_counts.get(name, 0) + 1
            else:
                previous_counts[name] = previous_counts.get(name, 0) + 1

        # Build per-entity trends.
        trends = await self._build_trends(
            current_counts=current_counts,
            previous_counts=previous_counts,
            window_days=window_days,
        )

        # Aggregate MENTIONS heat time-series (list field, R-trend-002).
        list_data = self._aggregate_mentions(all_rows_for_list)

        log.info(
            "trend_detection_ok",
            event_count=len(rows),
            entity_count=len(trends),
            window_days=window_days,
            entity_type=entity_type,
        )

        return TrendDetectionResult(
            window_days=window_days,
            entity_type=entity_type,
            trends=trends,
            list=list_data,
            status="ok",
        )

    async def _query_events(
        self,
        *,
        cutoff_start: datetime,
        entity_type: str | None,
    ) -> list[dict[str, Any]]:
        """Query EventNode rows in [cutoff_start, now] with name + created_at.

        Cross-database Cypher (temporal.py pattern):
        - Neo4j: ``WHERE e.created_at >= datetime($cutoff_iso)``
        - LadybugDB: ``WHERE e.created_at >= $cutoff_epoch`` (INT64)

        Args:
            cutoff_start: Earliest created_at to include.
            entity_type: Optional EventNode.name filter.

        Returns:
            List of dict rows with ``name`` + ``created_at`` fields.

        Raises:
            Exception: On graph DB error (Rule 12 — propagate).
        """
        if self._is_ladybug:
            time_predicate = "e.created_at >= $cutoff_epoch"
            params: dict[str, Any] = {
                "cutoff_epoch": int(cutoff_start.timestamp()),
            }
        else:
            time_predicate = "e.created_at >= datetime($cutoff_iso)"
            params = {
                "cutoff_iso": cutoff_start.isoformat(),
            }

        # entity_type filter (Rule 7 — spec says entity_type, schema field is name).
        entity_predicate = ""
        if entity_type is not None:
            entity_predicate = " AND e.name = $entity_type"
            params["entity_type"] = entity_type

        query = f"""
        MATCH (e:EventNode)
        WHERE {time_predicate}{entity_predicate}
        RETURN e.name AS name, e.created_at AS created_at
        """

        return await self._pool.execute_query(query, params)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        """Parse created_at value into timezone-aware datetime.

        Handles cross-database type differences:
        - Neo4j returns datetime objects.
        - LadybugDB returns INT64 epoch seconds.

        Args:
            value: created_at value from graph DB row.

        Returns:
            Timezone-aware datetime in UTC.

        Note:
            Falls back to ``now(UTC)`` for unexpected types (defensive —
            should not happen with well-formed data). Logged at debug.
        """
        # bool is a subclass of int — exclude before int check.
        if isinstance(value, bool):
            return datetime.now(UTC)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        # Defensive fallback for None / unexpected types.
        return datetime.now(UTC)

    async def _build_trends(
        self,
        *,
        current_counts: dict[str, int],
        previous_counts: dict[str, int],
        window_days: int,
    ) -> list[dict[str, Any]]:
        """Build per-entity trend entries with trend_score + direction.

        For each entity (union of current + previous names):
        - frequency_change = (current - previous) / max(previous, 1)
        - If analyzer available AND returns non-empty shifts:
            trend_score = 0.6 * freq_change + 0.4 * sentiment_change
        - Else (analyzer None OR empty shifts):
            trend_score = freq_change (degraded — R-trend-005)
        - direction: >0.2 'up', <-0.2 'down', else 'stable'

        Args:
            current_counts: Entity name → count in current window.
            previous_counts: Entity name → count in previous window.
            window_days: Window size (for sentiment analyzer call).

        Returns:
            List of trend dicts, each with entity_name, trend_score,
            direction, frequency_change, current_count, previous_count.

        Raises:
            Exception: On sentiment analyzer error (Rule 12 — propagate).
        """
        trends: list[dict[str, Any]] = []
        all_names = set(current_counts) | set(previous_counts)

        for name in sorted(all_names):
            current = current_counts.get(name, 0)
            previous = previous_counts.get(name, 0)
            # Avoid division by zero: max(previous, 1).
            freq_change = (current - previous) / max(previous, 1)

            sentiment_change = 0.0
            has_sentiment = False

            if self._analyzer is not None:
                # Query sentiment for this entity. Errors propagate (Rule 12).
                sentiment_result = await self._analyzer.analyze_trend(
                    entity_name=name,
                    window_days=window_days,
                )
                # Degradation condition (R-trend-005): empty shifts means
                # no sentiment data for this entity → freq-only.
                if sentiment_result.shifts:
                    sentiment_change = sentiment_result.avg_shift
                    has_sentiment = True

            # Compute trend_score with optional sentiment blend.
            if has_sentiment:
                trend_score = _FREQ_WEIGHT * freq_change + _SENTIMENT_WEIGHT * sentiment_change
            else:
                trend_score = freq_change

            # Direction per R-trend-005 thresholds.
            if trend_score > _UP_THRESHOLD:
                direction = "up"
            elif trend_score < _DOWN_THRESHOLD:
                direction = "down"
            else:
                direction = "stable"

            trends.append(
                {
                    "entity_name": name,
                    "trend_score": trend_score,
                    "direction": direction,
                    "frequency_change": freq_change,
                    "current_count": current,
                    "previous_count": previous,
                }
            )

        return trends

    @staticmethod
    def _aggregate_mentions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggregate EventNode rows into per-day MENTIONS heat buckets.

        Each bucket contains:
        - ``day``: ISO date string (YYYY-MM-DD)
        - ``mentions``: number of EventNode rows on that day
        - ``count``: alias for mentions (kept for client compat with
          SentimentTrendResult.list bucket shape)

        Buckets are sorted by day ascending (oldest first) for natural
        time-series ordering. Days with no events are omitted (sparse).

        Args:
            rows: EventNode dict rows with name + created_at.

        Returns:
            List of per-day aggregation dicts. Empty if no rows.
        """
        buckets: dict[str, int] = {}
        for row in rows:
            if row.get("name") is None:
                continue
            created_at = TrendDetector._parse_timestamp(row.get("created_at"))
            day_key = created_at.date().isoformat()
            buckets[day_key] = buckets.get(day_key, 0) + 1

        return [
            {
                "day": day,
                "mentions": count,
                "count": count,
            }
            for day, count in sorted(buckets.items())
        ]


__all__ = ["TrendDetector"]
