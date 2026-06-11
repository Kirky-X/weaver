# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Briefing engine — generate daily news briefings."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

from modules.briefing.diversity import CategoryDiversity
from modules.briefing.scorer import BriefingScorer

log = get_logger(__name__)


class DailyBriefingEngine:
    """Generate daily briefings from recent articles.

    Implements: Briefing generation with five-dimensional weighted scoring.
    """

    def __init__(
        self,
        pool: RelationalPool,
        scorer: BriefingScorer | None = None,
        diversity: CategoryDiversity | None = None,
    ) -> None:
        self._pool = pool
        self._scorer = scorer or BriefingScorer()
        self._diversity = diversity or CategoryDiversity(max_per_category=3)

    async def generate(self, briefing_date: date | None = None) -> dict[str, Any]:
        """Generate briefing for the given date.

        Args:
            briefing_date: Date to generate briefing for (default: today).

        Returns:
            Briefing dict with id, date, items.
        """
        target_date = briefing_date or date.today()

        articles = await self._fetch_articles(target_date)
        if not articles:
            log.info("no_articles_for_briefing", date=str(target_date))
            return {"briefing_date": target_date, "items": []}

        for article in articles:
            score, breakdown = self._scorer.score(article)
            article["_score"] = score
            article["score_breakdown"] = breakdown

        articles.sort(key=lambda a: a.get("_score", 0), reverse=True)

        selected = self._diversity.apply(articles)

        briefing_id = await self._persist(target_date, selected)

        log.info(
            "briefing_generated",
            date=str(target_date),
            items=len(selected),
        )

        return {
            "id": briefing_id,
            "briefing_date": target_date,
            "items": [
                {
                    "rank": i + 1,
                    "article_id": a.get("article_id") or a.get("id"),
                    "category": a.get("category"),
                    "score": a.get("_score", 0),
                    "score_breakdown": a.get("score_breakdown"),
                }
                for i, a in enumerate(selected)
            ],
        }

    async def _fetch_articles(self, target_date: date) -> list[dict[str, Any]]:
        """Fetch articles from the last 24 hours."""
        try:
            async with self._pool.session_context() as session:
                from datetime import datetime, timedelta

                from sqlalchemy import select

                from core.db import ArticleCore

                start_dt = datetime(
                    target_date.year, target_date.month, target_date.day
                ) - timedelta(hours=24)
                end_dt = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)

                query = (
                    select(ArticleCore)
                    .where(
                        ArticleCore.publish_time >= start_dt,
                        ArticleCore.publish_time <= end_dt,
                    )
                    .order_by(ArticleCore.publish_time.desc())
                )

                result = await session.execute(query)
                rows = result.scalars().all()

                return [
                    {
                        "article_id": str(r.id),
                        "title": r.title,
                        "category": getattr(r, "category", None),
                        "score": float(r.score) if r.score else 0.0,
                        "credibility_score": (
                            float(r.credibility_score) if r.credibility_score else 0.0
                        ),
                        "quality_score": float(r.quality_score) if r.quality_score else 0.0,
                    }
                    for r in rows
                ]
        except Exception as exc:
            log.error("fetch_articles_failed", error=str(exc))
            return []

    async def _persist(self, briefing_date: date, items: list[dict[str, Any]]) -> int:
        """Persist briefing to database."""
        try:
            async with self._pool.session_context() as session:
                from sqlalchemy import select

                from core.db import DailyBriefing, DailyBriefingItem

                existing = await session.execute(
                    select(DailyBriefing).where(DailyBriefing.briefing_date == briefing_date)
                )
                if existing.scalar_one_or_none():
                    log.info("briefing_already_exists", date=str(briefing_date))
                    return 0

                briefing = DailyBriefing(
                    briefing_date=briefing_date,
                    title=items[0].get("briefing_title") if items else None,
                    summary=items[0].get("briefing_summary") if items else None,
                    status="generated",
                    total_items=len(items),
                )
                session.add(briefing)
                await session.flush()

                for i, item in enumerate(items):
                    briefing_item = DailyBriefingItem(
                        briefing_id=briefing.id,
                        article_id=item.get("article_id") or item.get("id"),
                        rank=i + 1,
                        score=item.get("score", 0.0) or item.get("_score", 0.0),
                        score_breakdown=item.get("score_breakdown"),
                        category=item.get("category"),
                        reason=item.get("reason"),
                    )
                    session.add(briefing_item)

                await session.commit()
                return briefing.id
        except Exception as exc:
            log.error("persist_briefing_failed", error=str(exc))
            return 0
