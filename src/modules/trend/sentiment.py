# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Sentiment trend analyzer — implements SentimentTrendProtocol (T012 / R-sentiment-002).

SentimentTrendAnalyzer queries the ``sentiment_shifts`` table for article-level
shifts (T003 SentimentTrackerNode output, article_id IS NOT NULL) within a
time window, then computes:

- ``avg_shift`` = mean(shift_value) across all matching rows.
- ``trend_direction``: 'up' if avg_shift > 0.1, 'down' if < -0.1, else 'stable'
  (threshold per spec R-sentiment-002).
- ``shifts``: raw shift records (list[dict]).
- ``list``: per-day aggregated buckets with ``day``/``avg_shift``/``count``,
  suitable for time-series visualization.

Two query paths:
- ``entity_name`` path: WHERE entity_name = ? AND article_id IS NOT NULL.
  Used by T013 endpoint ``GET /api/v1/trends/sentiment?entity=xxx``.
- ``community_id`` path: WHERE community_id = ?. Note that for article-level
  records, ``community_id`` column is reused to store ``entity_name`` (see
  migration 30 docstring + SentimentTrackerNode._track_single_entity), so
  the community_id path is functionally a query against that field. Both
  paths filter article_id IS NOT NULL + shift_value IS NOT NULL to ensure
  we only aggregate signed shift values from T003 (community-level rows
  lack shift_value).

Cross-database compatibility (Rule — PG + DuckDB):
- Uses SQLAlchemy Core select() with parameter binding; no DB-specific SQL.
- DateTime math uses Python-side cutoff (``datetime.now(UTC) - timedelta``)
  rather than SQL interval functions to avoid dialect differences.

Constructor injection (Rule — Protocol type, not concrete class):
    ``__init__(self, pool: RelationalPool)`` accepts any pool implementing
    RelationalPool (PostgresPool / DuckDBPool). The pool is used solely
    via ``pool.session_context()``.

Failure handling (Rule 12 — fail loud):
    DB errors from ``session.execute`` propagate to the caller. The
    no-data case is NOT an error — it returns the empty stable result
    (R-sentiment-002). Validation errors (both None / invalid window_days)
    raise ``ValueError`` before touching the DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.trend.models import SentimentTrendResult

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)

# Spec R-sentiment-001 constraints: only 7 and 30 days are supported.
_SUPPORTED_WINDOW_DAYS: frozenset[int] = frozenset({7, 30})

# Spec R-sentiment-002: direction thresholds.
_UP_THRESHOLD: float = 0.1
_DOWN_THRESHOLD: float = -0.1


class SentimentTrendAnalyzer:
    """Analyze sentiment shifts over a time window for an entity or community.

    Implements: SentimentTrendProtocol (core.protocols.services)

    Args:
        pool: RelationalPool implementation (PostgresPool or DuckDBPool).
            Used via ``pool.session_context()`` for all DB access.

    Raises:
        TypeError: If pool does not implement RelationalPool (delegated to
            runtime_checkable Protocol check).
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def analyze_trend(
        self,
        entity_name: str | None = None,
        community_id: str | None = None,
        window_days: int = 7,
    ) -> SentimentTrendResult:
        """Analyze sentiment shifts for an entity or community over a window.

        Args:
            entity_name: Canonical entity name (article-level shifts filter).
            community_id: Community identifier (community_id column filter).
            window_days: Time window in days — MUST be 7 or 30 per spec.

        Returns:
            SentimentTrendResult with raw shifts, aggregated list,
            avg_shift, and trend_direction.

        Raises:
            ValueError: If both entity_name and community_id are None,
                or window_days not in {7, 30}.
            Exception: On DB error (Rule 12 — propagate, do not swallow).
        """
        # Validate inputs BEFORE touching the DB (cheap-fail principle).
        if entity_name is None and community_id is None:
            raise ValueError(
                "SentimentTrendAnalyzer.analyze_trend requires at least one of "
                "entity_name or community_id (both are None)."
            )
        if window_days not in _SUPPORTED_WINDOW_DAYS:
            raise ValueError(
                f"window_days must be one of {sorted(_SUPPORTED_WINDOW_DAYS)}, got {window_days}."
            )

        # Time window cutoff — computed Python-side for DB dialect portability.
        cutoff = datetime.now(UTC) - timedelta(days=window_days)

        rows = await self._query_shifts(
            entity_name=entity_name,
            community_id=community_id,
            cutoff=cutoff,
        )

        # No-data contract (R-sentiment-002): return empty stable result.
        if not rows:
            return SentimentTrendResult(
                entity_name=entity_name,
                window_days=window_days,
                shifts=[],
                list=[],
                avg_shift=0.0,
                trend_direction="stable",
            )

        # Build raw shifts list (list[dict]) for client transparency.
        shifts = [self._row_to_dict(row) for row in rows]

        # Compute avg_shift = mean(shift_value).
        shift_values = [float(row.shift_value) for row in rows if row.shift_value is not None]
        avg_shift = sum(shift_values) / len(shift_values) if shift_values else 0.0

        # Aggregate per-day buckets for the `list` field.
        aggregated = self._aggregate_by_day(rows)

        # Determine trend direction per spec R-sentiment-002 thresholds.
        if avg_shift > _UP_THRESHOLD:
            direction = "up"
        elif avg_shift < _DOWN_THRESHOLD:
            direction = "down"
        else:
            direction = "stable"

        return SentimentTrendResult(
            entity_name=entity_name,
            window_days=window_days,
            shifts=shifts,
            list=aggregated,
            avg_shift=avg_shift,
            trend_direction=direction,
        )

    async def _query_shifts(
        self,
        *,
        entity_name: str | None,
        community_id: str | None,
        cutoff: datetime,
    ) -> list[Any]:
        """Query sentiment_shifts for matching rows.

        Both query paths filter:
        - article_id IS NOT NULL (T003 article-level shifts only)
        - shift_value IS NOT NULL (must have signed shift for mean calc)
        - detected_at >= cutoff (within window_days)

        Args:
            entity_name: If given, filter by entity_name column.
            community_id: If given, filter by community_id column.
            cutoff: Earliest detected_at to include.

        Returns:
            List of SentimentShift ORM rows.

        Raises:
            Exception: On DB error (Rule 12 — propagate).
        """
        async with self._pool.session_context() as session:
            from sqlalchemy import select

            from core.db import SentimentShift as SentimentShiftModel

            query = (
                select(SentimentShiftModel)
                .where(SentimentShiftModel.article_id.is_not(None))
                .where(SentimentShiftModel.shift_value.is_not(None))
                .where(SentimentShiftModel.detected_at >= cutoff)
            )
            if entity_name is not None:
                query = query.where(SentimentShiftModel.entity_name == entity_name)
            elif community_id is not None:
                query = query.where(SentimentShiftModel.community_id == community_id)

            query = query.order_by(SentimentShiftModel.detected_at.desc())

            result = await session.execute(query)
            return list(result.scalars().all())

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a SentimentShift ORM row to a dict for the ``shifts`` field.

        Only includes fields relevant to sentiment trend analysis — not all
        columns. Kept narrow to avoid leaking schema internals to API clients.
        """
        return {
            "article_id": str(row.article_id) if row.article_id is not None else None,
            "entity_name": row.entity_name,
            "community_id": row.community_id,
            "shift_value": float(row.shift_value) if row.shift_value is not None else None,
            "before_avg": float(row.before_avg) if row.before_avg is not None else None,
            "after_avg": float(row.after_avg) if row.after_avg is not None else None,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        }

    @staticmethod
    def _aggregate_by_day(rows: list[Any]) -> list[dict[str, Any]]:
        """Aggregate shift rows into per-day buckets.

        Each bucket contains:
        - ``day``: ISO date string (YYYY-MM-DD)
        - ``avg_shift``: mean shift_value within that day
        - ``count``: number of shifts in that day

        Buckets are sorted by day ascending (oldest first) for natural
        time-series ordering. Days with no shifts are omitted (sparse data).

        Args:
            rows: SentimentShift ORM rows.

        Returns:
            List of per-day aggregation dicts. Empty if no rows.
        """
        buckets: dict[str, list[float]] = {}
        for row in rows:
            if row.detected_at is None or row.shift_value is None:
                continue
            day_key = row.detected_at.date().isoformat()
            buckets.setdefault(day_key, []).append(float(row.shift_value))

        return [
            {
                "day": day,
                "avg_shift": sum(values) / len(values),
                "count": len(values),
            }
            for day, values in sorted(buckets.items())
        ]


__all__ = ["SentimentTrendAnalyzer"]
