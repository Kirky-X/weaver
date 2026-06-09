# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics storage — persist shift points to database."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from core.observability.logging import get_logger

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
                from core.db.models import SentimentShift as SentimentShiftModel

                record = SentimentShiftModel(
                    community_id=shift["community_id"],
                    shift_type=shift["shift_type"],
                    direction=shift["direction"],
                    magnitude=shift["magnitude"],
                    confidence=shift["confidence"],
                    detected_at=shift.get("detected_at", datetime.now()),
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

                from core.db.models import SentimentShift as SentimentShiftModel

                query = select(SentimentShiftModel)
                if community_id:
                    query = query.where(SentimentShiftModel.community_id == community_id)
                query = query.order_by(SentimentShiftModel.detected_at.desc()).limit(limit)
                result = await session.execute(query)
                rows = result.scalars().all()
                return [
                    {
                        "community_id": r.community_id,
                        "shift_type": r.shift_type,
                        "direction": r.direction,
                        "magnitude": float(r.magnitude) if r.magnitude else 0.0,
                        "confidence": float(r.confidence) if r.confidence else 0.0,
                        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                        "before_avg": float(r.before_avg) if r.before_avg else None,
                        "after_avg": float(r.after_avg) if r.after_avg else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            log.error("get_shifts_failed", error=str(exc))
            return []
