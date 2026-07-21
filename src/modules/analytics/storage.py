# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Analytics storage — persist shift points to database."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)

ShiftScope = Literal["community", "article", "all"]


class AnalyticsStorage:
    """Persist and retrieve analytics data.

    Implements: AnalyticsStorageProtocol (core.protocols.repositories)
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
                    # Migration 30: article-level tracking fields (T003).
                    # Optional — community-level shifts leave these None.
                    article_id=shift.get("article_id"),
                    entity_name=shift.get("entity_name"),
                    shift_value=shift.get("shift_value"),
                )
                session.add(record)
                await session.commit()
        except Exception as exc:
            log.error("save_shift_failed", error=str(exc))
            raise

    async def get_last_article_shift(self, entity_name: str) -> dict[str, Any] | None:
        """Get the most recent article-level shift for an entity.

        Used by SentimentTrackerNode to compare the current article's
        sentiment_score against the previous article mentioning the same
        entity. Only article-level records (article_id IS NOT NULL) are
        considered — community-level shifts are excluded.

        Args:
            entity_name: Canonical entity name to query.

        Returns:
            Dict with article_id/entity_name/shift_value/before_avg/
            after_avg/detected_at, or None when no article-level record
            exists for the entity.

        Raises:
            Exception: On DB error. Rule 12 — failures must surface to the
                caller; SentimentTrackerNode._track_single_entity catches
                and marks ``sentiment_shift`` in degraded_fields. Returning
                None on error would be misread as "no previous article"
                and trigger an incorrect seed record (T003-sub4 H2).
        """
        async with self._pool.session_context() as session:
            from sqlalchemy import select

            from core.db import SentimentShift as SentimentShiftModel

            query = (
                select(SentimentShiftModel)
                .where(SentimentShiftModel.entity_name == entity_name)
                .where(SentimentShiftModel.article_id.is_not(None))
                .order_by(SentimentShiftModel.detected_at.desc())
                .limit(1)
            )
            result = await session.execute(query)
            row = result.scalars().first()
            if row is None:
                return None
            return {
                "article_id": row.article_id,
                "entity_name": row.entity_name,
                "shift_value": float(row.shift_value) if row.shift_value is not None else None,
                "before_avg": float(row.before_avg) if row.before_avg is not None else None,
                "after_avg": float(row.after_avg) if row.after_avg is not None else None,
                "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            }

    async def get_shifts(
        self,
        community_id: str | None = None,
        limit: int = 50,
        scope: ShiftScope = "community",
    ) -> list[dict[str, Any]]:
        """Get recent sentiment shifts.

        Args:
            community_id: Optional community filter (matches community_id
                column for community-level rows, or entity_name stored in
                community_id column for article-level rows).
            limit: Maximum number of rows to return.
            scope: Which shifts to return. Defaults to ``"community"`` to
                preserve the historical API behavior (community-level only,
                i.e. article_id IS NULL) and avoid polluting community
                queries with T003 article-level records (Rule 14).
                - ``"community"``: only community-level shifts (article_id IS NULL)
                - ``"article"``: only article-level shifts (article_id IS NOT NULL)
                - ``"all"``: both (back-compat for callers that want everything)

        Returns:
            List of shift dicts ordered by detected_at desc.

        Raises:
            Exception: On DB error (Rule 12). API endpoint catches and
                returns an empty list to the client.
        """
        async with self._pool.session_context() as session:
            from sqlalchemy import select

            from core.db import SentimentShift as SentimentShiftModel

            query = select(SentimentShiftModel)
            if scope == "community":
                query = query.where(SentimentShiftModel.article_id.is_(None))
            elif scope == "article":
                query = query.where(SentimentShiftModel.article_id.is_not(None))
            # scope == "all": no article_id filter
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

        Raises:
            Exception: On DB error (Rule 12). API endpoint catches and
                returns an empty list to the client.
        """
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
                    "category": r.category,
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

    # ── T004: BriefingGenerator support ────────────────────────────────────

    # Briefing category → articles_core.category mapping.
    # - finance → 经济 (CategoryType.ECONOMY)
    # - tech → 科技 (CategoryType.TECHNOLOGY)
    # - ai → keyword match on title/body (no direct enum equivalent)
    # - general → no filter (all categories)
    # AI_KEYWORDS used for ai category filter (case-insensitive substring).
    AI_KEYWORDS: tuple[str, ...] = (
        "AI",
        "人工智能",
        "大模型",
        "LLM",
        "GPT",
        "Claude",
        "Gemini",
        "机器学习",
        "深度学习",
        "神经网络",
    )

    async def fetch_articles_for_briefing(
        self,
        briefing_date: date,
        category: str,
    ) -> list[dict[str, Any]]:
        """Fetch articles for a given date filtered by briefing category.

        Implements the category mapping decision (Rule 7 — exposed conflict,
        decision: hybrid):
        - finance → articles_core.category == CategoryType.ECONOMY ('经济')
        - tech → articles_core.category == CategoryType.TECHNOLOGY ('科技')
        - ai → title OR body contains any AI_KEYWORDS (case-insensitive)
        - general → no category filter (all articles on that date)

        Body is fetched via LEFT JOIN to article_bodies (vertical split per
        Weaver-数据库设计文档 §9.1). Required by spec R-briefing-003 — LLM
        summary needs article body, not just title (Rule 24 — no simplified
        implementation).

        Args:
            briefing_date: Date to fetch articles for. publish_time window is
                [briefing_date 00:00:00, briefing_date 23:59:59] (same day,
                no -24h lookback — that was a bug).
            category: Briefing category — one of {finance, tech, ai, general}.

        Returns:
            List of article dicts with article_id/title/body/category/score/
            sentiment_score/credibility_score/quality_score/publish_time.

        Raises:
            ValueError: If category is not in {finance, tech, ai, general}.
            Exception: On DB error (Rule 12). BriefingGenerator propagates
                to caller.
        """
        if category not in {"finance", "tech", "ai", "general"}:
            raise ValueError(
                f"Invalid briefing category '{category}'. Valid: finance/tech/ai/general"
            )

        async with self._pool.session_context() as session:
            from datetime import datetime as dt

            from sqlalchemy import or_, select

            from core.db import ArticleBody, ArticleCore
            from core.db.models.base import CategoryType

            # Same-day window [00:00:00, 23:59:59]. No -24h lookback —
            # previous fix incorrectly expanded the window to 48h.
            start_dt = dt(briefing_date.year, briefing_date.month, briefing_date.day)
            end_dt = dt(briefing_date.year, briefing_date.month, briefing_date.day, 23, 59, 59)

            # LEFT JOIN article_bodies to fetch body in the same query
            # (vertical split per §9.1). Body is required by spec R-briefing-003
            # for LLM summary input — returning body="" was a Rule 24 violation.
            query = (
                select(ArticleCore, ArticleBody.body)
                .outerjoin(ArticleBody, ArticleBody.article_id == ArticleCore.id)
                .where(
                    ArticleCore.publish_time >= start_dt,
                    ArticleCore.publish_time <= end_dt,
                )
                .order_by(ArticleCore.publish_time.desc())
            )

            # Apply category filter.
            if category == "finance":
                query = query.where(ArticleCore.category == CategoryType.ECONOMY)
            elif category == "tech":
                query = query.where(ArticleCore.category == CategoryType.TECHNOLOGY)
            elif category == "ai":
                # Keyword match on title OR body (Rule 24 — must match body
                # too, not just title). Body is now available via the JOIN.
                title_conditions = [ArticleCore.title.ilike(f"%{kw}%") for kw in self.AI_KEYWORDS]
                body_conditions = [ArticleBody.body.ilike(f"%{kw}%") for kw in self.AI_KEYWORDS]
                query = query.where(or_(*title_conditions, *body_conditions))
            # general: no filter

            result = await session.execute(query)
            rows = result.all()

            return [
                {
                    "article_id": str(r.ArticleCore.id),
                    "title": r.ArticleCore.title,
                    "body": r.body or "",
                    "category": r.ArticleCore.category,
                    "score": float(r.ArticleCore.score) if r.ArticleCore.score else 0.0,
                    "sentiment_score": (
                        float(r.ArticleCore.sentiment_score)
                        if r.ArticleCore.sentiment_score
                        else None
                    ),
                    "credibility_score": (
                        float(r.ArticleCore.credibility_score)
                        if r.ArticleCore.credibility_score
                        else None
                    ),
                    "quality_score": None,  # lives in article_analysis (separate join)
                    "publish_time": r.ArticleCore.publish_time,
                }
                for r in rows
            ]

    async def save_briefing(
        self,
        briefing_date: date,
        category: str,
        summary: str | None,
        items: list[dict[str, Any]],
    ) -> int:
        """Persist a daily briefing + items.

        Idempotent: if a briefing with the same (briefing_date, category)
        already exists, it is replaced (delete + insert). This matches the
        spec R-briefing-002 'same-day same-category 覆盖' semantics.

        Args:
            briefing_date: Briefing date.
            category: Briefing category (finance/tech/ai/general).
            summary: LLM-generated summary (None if LLM failed).
            items: List of item dicts with article_id/rank/score/category/reason.

        Returns:
            The persisted briefing id.

        Raises:
            Exception: On DB error (Rule 12). BriefingGenerator propagates
                to caller (T010 scheduler / T009 endpoint).
        """
        async with self._pool.session_context() as session:
            from sqlalchemy import delete, select

            from core.db import DailyBriefing, DailyBriefingItem

            # Idempotency: delete existing briefing with same (date, category).
            # CASCADE on daily_briefing_items.briefing_id will auto-delete items.
            existing = await session.execute(
                select(DailyBriefing).where(
                    DailyBriefing.briefing_date == briefing_date,
                    DailyBriefing.category == category,
                )
            )
            existing_row = existing.scalar_one_or_none()
            if existing_row:
                await session.execute(
                    delete(DailyBriefing).where(DailyBriefing.id == existing_row.id)
                )

            briefing = DailyBriefing(
                briefing_date=briefing_date,
                title=f"Daily briefing — {category}",
                summary=summary,
                status="published" if summary else "draft",
                total_items=len(items),
                category=category,
            )
            session.add(briefing)
            await session.flush()

            for item in items:
                # Explicit UUID conversion — DailyBriefingItem.article_id is
                # UUID(as_uuid=True). Items from BriefingGenerator carry str
                # article_id; explicit conversion ensures DuckDB compatibility
                # (DuckDB's UUID type is stricter than PostgreSQL's).
                briefing_item = DailyBriefingItem(
                    briefing_id=briefing.id,
                    article_id=uuid.UUID(item["article_id"]),
                    rank=item["rank"],
                    score=item.get("score", 0.0),
                    score_breakdown=item.get("score_breakdown"),
                    category=item.get("category"),
                    reason=item.get("reason"),
                )
                session.add(briefing_item)

            await session.commit()
            return int(briefing.id)

    # ── T008: DailyBriefingService query support ────────────────────────

    async def get_briefing(
        self,
        briefing_date: date,
        category: str,
    ) -> dict[str, Any] | None:
        """Fetch a single persisted briefing by (date, category).

        Args:
            briefing_date: Date to query.
            category: Briefing category (finance/tech/ai/general). Must be
                normalized by caller (None → 'general').

        Returns:
            Briefing dict with id/briefing_date/category/summary/items/
            generated_at, or None if not found. Items is a list of dicts
            with rank/article_id/category/score/reason.

        Raises:
            Exception: On DB error (Rule 12 — failures must surface).
        """
        async with self._pool.session_context() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from core.db import DailyBriefing

            query = (
                select(DailyBriefing)
                .options(selectinload(DailyBriefing.items))
                .where(
                    DailyBriefing.briefing_date == briefing_date,
                    DailyBriefing.category == category,
                )
            )
            result = await session.execute(query)
            row = result.scalars().first()
            if row is None:
                return None
            return self._briefing_row_to_dict(row)

    async def list_briefings(
        self,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        """List briefings within a date range (inclusive).

        Args:
            date_from: Start date (inclusive).
            date_to: End date (inclusive).

        Returns:
            List of briefing dicts (same shape as get_briefing's return)
            ordered by briefing_date descending. Empty list if none in range.

        Raises:
            Exception: On DB error (Rule 12 — failures must surface).
        """
        async with self._pool.session_context() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from core.db import DailyBriefing

            query = (
                select(DailyBriefing)
                .options(selectinload(DailyBriefing.items))
                .where(
                    DailyBriefing.briefing_date >= date_from,
                    DailyBriefing.briefing_date <= date_to,
                )
                .order_by(DailyBriefing.briefing_date.desc())
            )
            result = await session.execute(query)
            rows = result.scalars().all()
            return [self._briefing_row_to_dict(r) for r in rows]

    @staticmethod
    def _briefing_row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a DailyBriefing ORM row (with loaded items) to dict.

        Shared by get_briefing + list_briefings to ensure consistent shape.
        Matches BriefingGenerator.generate() return shape (id/briefing_date/
        category/summary/items/generated_at) so DailyBriefingService.
        _map_to_briefing_result can handle both uniformly.
        """
        return {
            "id": row.id,
            "briefing_date": row.briefing_date,
            "category": row.category,
            "summary": row.summary,
            "items": [
                {
                    "rank": item.rank,
                    "article_id": str(item.article_id),
                    "category": item.category,
                    "score": float(item.score) if item.score else None,
                    "reason": item.reason,
                }
                for item in row.items
            ],
            "generated_at": row.generated_at,
        }
