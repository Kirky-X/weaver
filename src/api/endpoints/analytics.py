# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Analytics API endpoints - sentiment shifts and daily briefings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.observability import get_logger

router = APIRouter(prefix="/analytics", tags=["analytics"])

log = get_logger(__name__)


def _get_analytics_storage():
    """Lazy import and create AnalyticsStorage from container."""
    from api.dependencies import get_relational_pool
    from modules.analytics import AnalyticsStorage

    pool = get_relational_pool()
    return AnalyticsStorage(pool=pool)


def _get_briefing_engine():
    """Lazy import and create DailyBriefingEngine from container."""
    from api.dependencies import get_relational_pool
    from modules.briefing import DailyBriefingEngine

    pool = get_relational_pool()
    return DailyBriefingEngine(pool=pool)


@router.get("/shifts", response_model=APIResponse)
async def get_shifts(
    community_id: str | None = Query(None, description="Filter by community ID"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results to return"),
    scope: str = Query(
        "community",
        description=(
            "Which shifts to return: 'community' (default, article_id IS NULL), "
            "'article' (article_id IS NOT NULL, T003 per-entity article-level), "
            "or 'all' (both)."
        ),
        pattern="^(community|article|all)$",
    ),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Get detected sentiment shifts.

    Returns a list of detected sentiment shifts, optionally filtered by community.
    Results are ordered by detection time (newest first).

    The ``scope`` parameter separates community-level shifts (detected by the
    scheduled SentimentShiftDetector) from article-level shifts (recorded by
    T003 SentimentTrackerNode when each article is processed). Default
    ``scope=community`` preserves historical behavior and avoids polluting
    community queries with per-entity article-level rows (Rule 14).
    """
    try:
        storage = _get_analytics_storage()
        shifts = await storage.get_shifts(community_id=community_id, limit=limit, scope=scope)
        return success_response({"shifts": shifts, "total": len(shifts)})
    except Exception as exc:
        # Rule 12: storage layer raises on DB error (T003-sub4 H2). Endpoint
        # catches to keep the API contract stable (200 + empty list) but must
        # log loudly — silently swallowing would hide DB failures from
        # operators (T003-sub4 architecture review H3).
        log.error(
            "analytics_shifts_endpoint_failed",
            community_id=community_id,
            scope=scope,
            limit=limit,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
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
    Each briefing includes its items with score_breakdown.
    """
    try:
        storage = _get_analytics_storage()
        briefings = await storage.get_briefings_with_items(date=date, limit=limit)
        return success_response({"briefings": briefings, "total": len(briefings)})
    except Exception:
        return success_response({"briefings": [], "total": 0})
