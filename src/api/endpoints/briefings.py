# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefings API endpoints (T009 / R-briefing-004, R-briefing-005).

Endpoints:
- GET  /api/v1/briefings/daily          — fetch existing briefing by date + category
- POST /api/v1/briefings/daily/generate — on-demand generation with narrative_mode

narrative_mode boundary (T009 挡板):
    Before T021/T022 implement NarrativeBriefingGenerator, the POST endpoint
    refuses narrative_mode=true with HTTP 501 Not Implemented. This is a
    deliberate boundary (Rule 24 — cover the scenario explicitly rather than
    silently ignoring the param). T022 will remove this 挡板 and transparently
    forward narrative_mode to DailyBriefingService.generate_briefing.

Service construction (lazy pattern, mirrors analytics.py):
    DailyBriefingService is not registered in the container; instead
    ``_get_briefing_service`` lazy-constructs it from container accessors
    (relational_pool + llm_client + prompt_loader + TokenBudgetManager).
    Tests patch ``api.endpoints.briefings._get_briefing_service``.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.observability import get_logger

if TYPE_CHECKING:
    from modules.briefing.models import BriefingResult

router = APIRouter(prefix="/briefings", tags=["briefings"])

log = get_logger(__name__)

# Category whitelist (spec R-briefing-001: finance/tech/ai/general).
# None means "综合" (general) and is handled by the service layer.
_CATEGORY_PATTERN = r"^(finance|tech|ai|general)$"

# Module-level reference to date.today to avoid parameter name shadowing.
# spec R-briefing-001 mandates parameter name `date`, which shadows the
# `date` class inside handler bodies (Rule 7 — exposed conflict). Capturing
# `date.today` at module scope lets handlers compute today without referencing
# the shadowed class.
_today = date.today


def _get_briefing_service():
    """Lazy import and construct DailyBriefingService from container.

    Mirrors the ``_get_analytics_storage`` pattern in analytics.py: service
    is not container-registered, so we assemble it on-demand from container
    accessors. BriefingGenerator needs (llm, budget, prompt_loader, storage);
    DailyBriefingService wraps (generator, storage).

    Returns:
        DailyBriefingService instance.

    Raises:
        RuntimeError: If container or required dependencies are unavailable.
            Callers (endpoint handlers) catch and surface as HTTP 503/500.

    """
    from container import get_container
    from core.llm.config.token_budget import TokenBudgetManager
    from modules.analytics import AnalyticsStorage
    from modules.briefing import BriefingGenerator, DailyBriefingService

    container = get_container()
    pool = container.relational_pool()
    llm = container.llm_client()
    prompt_loader = container.prompt_loader()
    storage = AnalyticsStorage(pool=pool)
    generator = BriefingGenerator(
        llm=llm,
        budget=TokenBudgetManager(),
        prompt_loader=prompt_loader,
        storage=storage,
    )
    return DailyBriefingService(generator=generator, storage=storage)


def _serialize_briefing_result(result: BriefingResult) -> dict:
    """Serialize BriefingResult dataclass to a JSON-friendly dict.

    Args:
        result: BriefingResult from service.

    Returns:
        Dict with ISO-formatted date/timestamps for API response.

    """
    return {
        "date": result.date.isoformat() if result.date else None,
        "category": result.category,
        "summary": result.summary,
        "items": result.items,
        "generated_at": result.generated_at.isoformat() if result.generated_at else None,
        "narrative_mode": result.narrative_mode,
        "briefing_id": result.briefing_id,
    }


@router.get("/daily", response_model=APIResponse)
async def get_daily_briefing(
    date: date | None = Query(None, description="Briefing date (YYYY-MM-DD). Defaults to today."),
    category: str | None = Query(
        None,
        description="Briefing category: finance/tech/ai/general. None means 综合 (general).",
        pattern=_CATEGORY_PATTERN,
    ),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Get a daily briefing by date + category (R-briefing-004).

    Returns ``data: null`` when no briefing exists for the given date + category
    (HTTP 200, not 404 — briefings are generated asynchronously by the scheduler
    and may not exist yet).

    Args:
        date: Briefing date. Defaults to today.
        category: Briefing category. None means 综合 (general).

    Returns:
        APIResponse with BriefingResult dict, or data=null if not found.

    """
    target_date = date or _today()
    try:
        service = _get_briefing_service()
        result = await service.get_briefing(date=target_date, category=category)
    except HTTPException:
        raise
    except Exception as exc:
        log.error(
            "briefings_get_failed",
            date=str(target_date),
            category=category,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail=f"Failed to fetch briefing: {exc}") from exc

    if result is None:
        return success_response(None)
    return success_response(_serialize_briefing_result(result))


@router.post("/daily/generate", response_model=APIResponse)
async def generate_daily_briefing(
    date: date | None = Query(None, description="Briefing date (YYYY-MM-DD). Defaults to today."),
    category: str | None = Query(
        None,
        description="Briefing category: finance/tech/ai/general. None means 综合 (general).",
        pattern=_CATEGORY_PATTERN,
    ),
    narrative_mode: bool = Query(
        False,
        description=(
            "If true, generate via NarrativeBriefingGenerator (T021). "
            "Currently returns HTTP 501 — narrative mode not yet implemented."
        ),
    ),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Generate (or regenerate) a daily briefing on demand (R-briefing-005).

    Idempotent: same (date, category) replaces any existing briefing.

    narrative_mode boundary (T009 挡板):
        narrative_mode=true returns HTTP 501 Not Implemented. T021 implements
        NarrativeBriefingGenerator; T022 removes this 挡板 and forwards the
        param to DailyBriefingService.generate_briefing.

    Args:
        date: Briefing date. Defaults to today.
        category: Briefing category. None means 综合 (general).
        narrative_mode: If true, use narrative mode (501 until T022).

    Returns:
        APIResponse with generated BriefingResult dict.

    Raises:
        HTTPException: 501 if narrative_mode=true (T009 挡板).
        HTTPException: 500 on generation failure (Rule 12: fail loud).

    """
    if narrative_mode:
        # T009 挡板: refuse narrative_mode=true until T021/T022 implement it.
        # Rule 24: cover the scenario explicitly (501) rather than silently
        # ignoring the param.
        log.info("briefings_generate_narrative_mode_not_implemented")
        raise HTTPException(
            status_code=501,
            detail="narrative mode 尚未实现 (narrative mode not implemented, tracked in T021/T022)",
        )

    target_date = date or _today()
    try:
        service = _get_briefing_service()
        result = await service.generate_briefing(date=target_date, category=category)
    except HTTPException:
        raise
    except Exception as exc:
        log.error(
            "briefings_generate_failed",
            date=str(target_date),
            category=category,
            narrative_mode=narrative_mode,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail=f"Failed to generate briefing: {exc}") from exc

    return success_response(_serialize_briefing_result(result))


__all__ = ["router"]
