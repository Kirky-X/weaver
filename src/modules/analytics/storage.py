# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Analytics storage — persist shift points to database."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)


class AnalyticsStorage:
    """Persist and retrieve analytics data.

    Implements: AnalyticsStorageProtocol
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def save_shift(self, shift: dict[str, Any]) -> None:
        """Save a sentiment shift to the database."""
        try:
            async with self._pool.session_context() as session:
                from core.db import SentimentShift as SentimentShiftModel

                record = SentimentShiftModel(
                    community_id=shift["community_id"],
                    community_title=shift.get("community_title"),
                    shift_type=shift["shift_type"],
                    direction=shift["direction"],
                    magnitude=shift["magnitude"],
                    confidence=shift["confidence"],
                    detected_at=shift.get("detected_at", datetime.now()),
                    window_start=shift.get("window_start"),
                    window_end=shift.get("window_end"),
                    before_avg=shift.get("before_avg"),
                    after_avg=shift.get("after_avg"),
                    trigger_article_ids=shift.get("trigger_article_ids", []),
                )
                session.add(record)
                await session.commit()
        except Exception as exc:
            log.error("save_shift_failed", error=str(exc))
            raise

    async def get_shifts(
        self,
        community_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent sentiment shifts."""
        try:
            async with self._pool.session_context() as session:
                from sqlalchemy import select

                from core.db import SentimentShift as SentimentShiftModel

                query = select(SentimentShiftModel)
                if community_id:
                    query = query.where(SentimentShiftModel.community_id == community_id)
                query = query.order_by(SentimentShiftModel.detected_at.desc()).limit(limit)
                result = await session.execute(query)
                rows = result.scalars().all()
                return [
                    {
                        "community_id": r.community_id,
                        "community_title": r.community_title,
                        "shift_type": r.shift_type,
                        "direction": r.direction,
                        "magnitude": float(r.magnitude) if r.magnitude else 0.0,
                        "confidence": float(r.confidence) if r.confidence else 0.0,
                        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                        "window_start": r.window_start.isoformat() if r.window_start else None,
                        "window_end": r.window_end.isoformat() if r.window_end else None,
                        "before_avg": float(r.before_avg) if r.before_avg else None,
                        "after_avg": float(r.after_avg) if r.after_avg else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            log.error("get_shifts_failed", error=str(exc))
            return []

    async def get_briefings_with_items(
        self,
        date: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get daily briefings with their items eagerly loaded.

        Args:
            date: Optional date filter in YYYY-MM-DD format.
            limit: Maximum number of briefings to return.

        Returns:
            List of briefing dicts, each including an ``items`` list with
            score breakdown and reason. Ordered by generation time desc.
        """
        try:
            async with self._pool.session_context() as session:
                from datetime import date as date_type

                from sqlalchemy import select
                from sqlalchemy.orm import selectinload

                from core.db import DailyBriefing

                query = select(DailyBriefing).options(selectinload(DailyBriefing.items))
                if date:
                    target_date = date_type.fromisoformat(date)
                    query = query.where(DailyBriefing.briefing_date == target_date)
                query = query.order_by(DailyBriefing.generated_at.desc()).limit(limit)
                result = await session.execute(query)
                rows = result.scalars().all()
                return [
                    {
                        "id": r.id,
                        "briefing_date": str(r.briefing_date),
                        "title": r.title,
                        "summary": r.summary,
                        "status": r.status,
                        "total_items": r.total_items,
                        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                        "items": [
                            {
                                "rank": item.rank,
                                "article_id": str(item.article_id),
                                "category": item.category,
                                "score": float(item.score) if item.score else None,
                                "score_breakdown": item.score_breakdown,
                                "reason": item.reason,
                            }
                            for item in r.items
                        ],
                    }
                    for r in rows
                ]
        except Exception as exc:
            log.error("get_briefings_with_items_failed", error=str(exc))
            return []
