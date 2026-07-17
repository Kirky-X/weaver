# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Briefings API endpoints (T009 / T022 / R-briefing-004, R-briefing-005).

Endpoints:
- GET  /api/v1/briefings/daily          — fetch existing briefing by date + category
- POST /api/v1/briefings/daily/generate — on-demand generation with narrative_mode

narrative_mode forwarding (T022):
    POST /daily/generate transparently forwards narrative_mode to
    DailyBriefingService.generate_briefing(narrative_mode=...). The 501 挡板
    introduced in T009 is removed. narrative_mode=True routes to
    NarrativeBriefingGenerator (injected by _get_briefing_service); on
    InsufficientNarrativeError the service degrades to template mode
    (BriefingResult.narrative_mode=False, summary still produced).

Service construction (lazy pattern, mirrors analytics.py + trends.py):
    DailyBriefingService is not registered in the container; instead
    ``_get_briefing_service`` lazy-constructs it from container accessors:
    - BriefingGenerator needs (llm, budget, prompt_loader, storage)
    - NarrativeBriefingGenerator needs (graph_pool, llm, budget,
      prompt_loader, storage) — graph_pool is required for narrative mode;
      when graph_pool is unavailable, narrative_generator is None and
      narrative_mode=True will raise HTTP 503 (R-briefing-008 fail-loud).
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

    Mirrors the ``_get_analytics_storage`` pattern in analytics.py + the
    ``_get_trend_detection_service`` pattern in trends.py: service is not
    container-registered, so we assemble it on-demand from container accessors.
    - BriefingGenerator needs (llm, budget, prompt_loader, storage)
    - NarrativeBriefingGenerator needs (graph_pool, llm, budget,
      prompt_loader, storage) — graph_pool is optional; when None,
      narrative_generator is None and narrative_mode=True raises
      ValueError in service layer (R-briefing-008 fail-loud). The endpoint
      handler surfaces ValueError as HTTP 503.

    Returns:
        DailyBriefingService instance with optional narrative_generator.

    Raises:
        HTTPException: 503 if relational pool is unavailable.
        RuntimeError: If container is not initialized (propagates to caller).
        HTTPException: 503 if graph pool is unavailable (only when narrative
            mode is required — caller passes narrative_mode through; service
            raises ValueError which handler maps to 503).

    """
    from container import get_container
    from core.llm.config.token_budget import TokenBudgetManager
    from modules.analytics import AnalyticsStorage
    from modules.briefing import BriefingGenerator, DailyBriefingService
    from modules.briefing.narrative import NarrativeBriefingGenerator

    container = get_container()
    pool = container.relational_pool()
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Relational pool not initialized",
        )
    llm = container.llm_client()
    prompt_loader = container.prompt_loader()
    storage = AnalyticsStorage(pool=pool)
    budget = TokenBudgetManager()
    generator = BriefingGenerator(
        llm=llm,
        budget=budget,
        prompt_loader=prompt_loader,
        storage=storage,
    )

    # Narrative generator is optional: graph_pool may be unavailable
    # (degraded mode). When None, narrative_mode=True raises ValueError
    # in service layer (R-briefing-008 fail-loud) — handler maps to 503.
    narrative_generator = None
    graph_pool = container.graph_pool()
    if graph_pool is not None:
        narrative_generator = NarrativeBriefingGenerator(
            graph_pool=graph_pool,
            llm=llm,
            budget=budget,
            prompt_loader=prompt_loader,
            storage=storage,
        )

    return DailyBriefingService(
        generator=generator,
        storage=storage,
        narrative_generator=narrative_generator,
    )


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
            "If true, generate via NarrativeBriefingGenerator (T020/T021). "
            "Degrades to template mode when NarrativeNode count < 3 "
            "(BriefingResult.narrative_mode=False on degradation, R-briefing-008)."
        ),
    ),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Generate (or regenerate) a daily briefing on demand (R-briefing-005).

    Idempotent: same (date, category) replaces any existing briefing.

    narrative_mode forwarding (T022):
        narrative_mode=true transparently forwards to
        DailyBriefingService.generate_briefing(narrative_mode=True). When
        narrative_generator is not injected (graph_pool unavailable), the
        service raises ValueError — handler maps to HTTP 503 (fail-loud,
        R-briefing-008). When NarrativeNode count < 3, the service catches
        InsufficientNarrativeError internally and degrades to template mode
        (BriefingResult.narrative_mode=False, summary still produced).

    Args:
        date: Briefing date. Defaults to today.
        category: Briefing category. None means 综合 (general).
        narrative_mode: If true, use narrative mode (degrades on insufficient data).

    Returns:
        APIResponse with generated BriefingResult dict.

    Raises:
        HTTPException: 503 if narrative_mode=true but narrative_generator
            is unavailable (graph_pool not initialized).
        HTTPException: 500 on generation failure (Rule 12: fail loud).

    """
    target_date = date or _today()
    try:
        service = _get_briefing_service()
        result = await service.generate_briefing(
            date=target_date,
            category=category,
            narrative_mode=narrative_mode,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        # narrative_mode=True without narrative_generator (Rule 12 fail-loud).
        # Map to 503: caller can retry with narrative_mode=false, or admin
        # must start graph_pool. Distinguish from 500 (programming bug).
        if "narrative_generator" in str(exc):
            log.warning(
                "briefings_generate_narrative_mode_unavailable",
                date=str(target_date),
                category=category,
                error=str(exc),
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "narrative mode unavailable: graph pool not initialized. "
                    "Retry with narrative_mode=false or start graph pool."
                ),
            ) from exc
        # Other ValueError (invalid category) → 400.
        raise HTTPException(status_code=400, detail=f"Invalid request: {exc}") from exc
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
