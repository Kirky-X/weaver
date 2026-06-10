# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics API endpoints - sentiment shifts and daily briefings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _get_analytics_storage():
    """Lazy import and create AnalyticsStorage from container."""
    from api.dependencies import get_relational_pool
    from modules.analytics.storage import AnalyticsStorage

    pool = get_relational_pool()
    return AnalyticsStorage(pool=pool)


def _get_briefing_engine():
    """Lazy import and create BriefingEngine from container."""
    from api.dependencies import get_relational_pool
    from modules.briefing.engine import BriefingEngine

    pool = get_relational_pool()
    return BriefingEngine(pool=pool)


@router.get("/shifts", response_model=APIResponse)
async def get_shifts(
    community_id: str | None = Query(None, description="Filter by community ID"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results to return"),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Get detected sentiment shifts.

    Returns a list of detected sentiment shifts, optionally filtered by community.
    Results are ordered by detection time (newest first).
    """
    try:
        storage = _get_analytics_storage()
        shifts = await storage.get_shifts(community_id=community_id, limit=limit)
        return success_response({"shifts": shifts, "total": len(shifts)})
    except Exception:
        return success_response({"shifts": [], "total": 0})


@router.get("/briefings", response_model=APIResponse)
async def get_briefings(
    date: str | None = Query(None, description="Filter by date (YYYY-MM-DD)"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results to return"),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Get daily intelligence briefings.

    Returns a list of generated daily briefings, optionally filtered by date.
    Results are ordered by generation time (newest first).
    """
    try:
        from datetime import date as date_type

        from core.db.models import DailyBriefing

        storage = _get_analytics_storage()
        pool = storage._pool

        async with pool.session_context() as session:
            from sqlalchemy import select

            query = select(DailyBriefing)
            if date:
                target_date = date_type.fromisoformat(date)
                query = query.where(DailyBriefing.briefing_date == target_date)
            query = query.order_by(DailyBriefing.generated_at.desc()).limit(limit)
            result = await session.execute(query)
            rows = result.scalars().all()

            briefings = [
                {
                    "id": r.id,
                    "briefing_date": str(r.briefing_date),
                    "total_items": r.total_items,
                    "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                }
                for r in rows
            ]

            return success_response({"briefings": briefings, "total": len(briefings)})
    except Exception:
        return success_response({"briefings": [], "total": 0})
