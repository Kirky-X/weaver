# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Sentiment aggregator — groups sentiment by community and date."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)


class SentimentAggregator:
    """Aggregate sentiment scores by community and date.

    Implements: AnalyticsAggregator
    """

    def __init__(self, pool: RelationalPool | None = None) -> None:
        self._pool = pool

    async def aggregate(
        self,
        community_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Aggregate daily sentiment for a community.

        Queries sentiment shifts for the given community and date range,
        returning a daily series of average sentiment values.

        Args:
            community_id: The community to aggregate for.
            start_date: Start date (inclusive).
            end_date: End date (inclusive).

        Returns:
            List of {date, avg_sentiment, article_count} dicts.
        """
        if not self._pool:
            return []

        try:
            async with self._pool.session_context() as session:
                from datetime import datetime

                from sqlalchemy import func, select

                from core.db.models import SentimentShift

                start_dt = datetime(start_date.year, start_date.month, start_date.day)
                end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

                query = (
                    select(
                        func.date(SentimentShift.detected_at).label("date"),
                        func.avg((SentimentShift.before_avg + SentimentShift.after_avg) / 2).label(
                            "avg_sentiment"
                        ),
                        func.count(SentimentShift.id).label("article_count"),
                    )
                    .where(
                        SentimentShift.community_id == community_id,
                        SentimentShift.detected_at >= start_dt,
                        SentimentShift.detected_at <= end_dt,
                    )
                    .group_by(func.date(SentimentShift.detected_at))
                    .order_by(func.date(SentimentShift.detected_at))
                )

                result = await session.execute(query)
                rows = result.scalars().all()

                return [
                    {
                        "date": row.date,
                        "avg_sentiment": float(row.avg_sentiment) if row.avg_sentiment else 0.0,
                        "article_count": int(row.article_count),
                    }
                    for row in rows
                ]
        except Exception as exc:
            log.error("aggregate_failed", error=str(exc))
            return []
