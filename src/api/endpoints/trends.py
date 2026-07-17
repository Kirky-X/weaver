# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Trends API endpoints (T013 / R-sentiment-003, T016 / R-trend-004).

Endpoints:
- GET /api/v1/trends/sentiment — sentiment trend analysis for an entity (T013)
- GET /api/v1/trends/detection — trend detection over a window with optional
  entity_type filter (T016)

Service construction (lazy pattern, mirrors briefings.py):
    SentimentTrendAnalyzer and TrendDetector are not registered in the
    container; instead ``_get_sentiment_trend_service`` and
    ``_get_trend_detection_service`` lazy-construct them from the container.
    Tests patch ``api.endpoints.trends._get_sentiment_trend_service`` and
    ``api.endpoints.trends._get_trend_detection_service``.

Spec conflict (Rule 7 — exposed):
    R-sentiment-003 says "entity 参数可选" (entity param optional), but
    Constraints say "entity_name 和 community_id 不能同时为 None". The
    sentiment endpoint only exposes ``entity`` (no community_id param), so
    entity is declared Optional in the signature (spec compliance) but the
    handler returns HTTP 400 when entity is missing or empty (Constraints
    compliance + user task spec: "entity 必传 (HTTP 400 if missing)"). This
    is the deliberate resolution — cover the scenario explicitly (Rule 24)
    rather than silently forwarding None to the service.

    T016: spec R-trend-002 says "按 entity_type 过滤" but EventNode schema
    field is ``name`` (not ``event_type``). The detection endpoint exposes
    ``entity_type`` param (spec compliance) and forwards it to
    TrendDetector which internally maps to EventNode.name (Rule 7 — exposed
    in TrendDetector docstring; spec param name preserved for API
    compatibility).

    T016 insufficient-data contract (R-trend-003/004): status='insufficient_data'
    returns HTTP 200 (not 400/500). Data insufficiency (EventNode < 50) is
    a legitimate state reported via the status field, not an error.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.observability import get_logger

if TYPE_CHECKING:
    from modules.trend.models import SentimentTrendResult, TrendDetectionResult

router = APIRouter(prefix="/trends", tags=["trends"])

log = get_logger(__name__)

# Spec R-sentiment-001 constraints: only 7 and 30 days are supported.
# Window param is a string like '7d' / '30d' (spec R-sentiment-003).
_SUPPORTED_WINDOW_DAYS: frozenset[int] = frozenset({7, 30})
_WINDOW_PATTERN = re.compile(r"^(\d+)d$")


def _parse_window(window: str) -> int:
    """Parse window string (e.g. '7d', '30d') into an integer day count.

    Args:
        window: Window string in ``Nd`` format.

    Returns:
        Integer number of days (7 or 30).

    Raises:
        HTTPException: 400 if format is invalid or value is not in {7, 30}.

    """
    match = _WINDOW_PATTERN.match(window)
    if not match:
        raise HTTPException(
            status_code=400,
            detail=(f"Invalid window format '{window}'. Expected 'Nd' format (e.g. '7d', '30d')."),
        )
    days = int(match.group(1))
    if days not in _SUPPORTED_WINDOW_DAYS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported window value '{window}'. Only 7d and 30d are supported (got {days}d)."
            ),
        )
    return days


def _get_sentiment_trend_service():
    """Lazy import and construct SentimentTrendAnalyzer from container.

    Mirrors the ``_get_briefing_service`` pattern in briefings.py: service
    is not container-registered, so we assemble it on-demand from the
    container's relational_pool. SentimentTrendAnalyzer only needs a
    RelationalPool (PG or DuckDB) for sentiment_shifts table access.

    Returns:
        SentimentTrendAnalyzer instance (implements SentimentTrendProtocol).

    Raises:
        HTTPException: 503 if relational pool is unavailable.
        RuntimeError: If container is not initialized (propagates to caller).

    """
    from container import get_container
    from modules.trend import SentimentTrendAnalyzer

    container = get_container()
    try:
        pool = container.relational_pool()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Relational pool not initialized",
        ) from exc
    return SentimentTrendAnalyzer(pool=pool)


def _serialize_trend_result(result: SentimentTrendResult) -> dict:
    """Serialize SentimentTrendResult dataclass to a JSON-friendly dict.

    All 6 fields from spec R-sentiment-001 are included. The ``list`` field
    name is preserved per spec (shadows Python builtin within the dataclass;
    serialized as a regular dict key here, no shadowing concern).

    Args:
        result: SentimentTrendResult from service.

    Returns:
        Dict with all 6 SentimentTrendResult fields.

    """
    return {
        "entity_name": result.entity_name,
        "window_days": result.window_days,
        "shifts": result.shifts,
        "list": result.list,
        "avg_shift": result.avg_shift,
        "trend_direction": result.trend_direction,
    }


@router.get("/sentiment", response_model=APIResponse)
async def get_sentiment_trend(
    entity: str | None = Query(
        None,
        description=(
            "Canonical entity name to filter sentiment shifts. "
            "Required (HTTP 400 if missing or empty) — spec Constraints "
            "mandate at least one filter, and this endpoint only exposes "
            "entity (no community_id param)."
        ),
    ),
    window: str = Query(
        "7d",
        description=(
            "Time window in 'Nd' format. Supported values: '7d', '30d'. "
            "Defaults to '7d'. Other values return HTTP 400."
        ),
    ),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Get sentiment trend for an entity over a time window (R-sentiment-003).

    Returns ``SentimentTrendResult`` with:
    - ``shifts``: raw shift records from sentiment_shifts table.
    - ``list``: per-day aggregated buckets (day/avg_shift/count).
    - ``avg_shift``: mean shift_value across all shifts in the window.
    - ``trend_direction``: 'up' (>0.1) / 'down' (<-0.1) / 'stable'.

    No-data contract (R-sentiment-002): HTTP 200 with
    ``shifts=[], list=[], avg_shift=0.0, trend_direction='stable'``
    when no shifts are found in the window — NOT an error.

    Args:
        entity: Canonical entity name (required, non-empty).
        window: Time window string ('7d' or '30d', default '7d').

    Returns:
        APIResponse with SentimentTrendResult dict.

    Raises:
        HTTPException: 400 if entity is missing/empty or window is invalid.
        HTTPException: 500 on service failure (Rule 12: fail loud).
        HTTPException: 503 if relational pool is unavailable.

    """
    # Validate entity (spec Constraints: at least one filter required).
    # entity is declared Optional per spec R-sentiment-003 ("entity 参数可选"),
    # but the handler enforces non-empty (Constraints + user task spec).
    if not entity or not entity.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "entity parameter is required and must not be empty. "
                "Spec Constraints require at least one filter "
                "(entity_name or community_id); this endpoint only exposes entity."
            ),
        )
    entity_clean = entity.strip()

    # Parse window string → int days (validates format + supported values).
    window_days = _parse_window(window)

    try:
        service = _get_sentiment_trend_service()
        result = await service.analyze_trend(
            entity_name=entity_clean,
            window_days=window_days,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        # Service-layer validation (defense-in-depth): map to 400.
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request parameters: {exc}",
        ) from exc
    except Exception as exc:
        log.error(
            "sentiment_trend_failed",
            entity_name=entity_clean,
            window_days=window_days,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze sentiment trend: {exc}",
        ) from exc

    return success_response(_serialize_trend_result(result))


# ────────────────────────────────────────────────────────────────────
# T016 / R-trend-004: GET /api/v1/trends/detection
# ────────────────────────────────────────────────────────────────────


def _get_trend_detection_service():
    """Lazy import and construct TrendDetector from container (T016).

    Mirrors ``_get_sentiment_trend_service`` pattern. TrendDetector needs:
    - graph_pool (REQUIRED): Neo4jPool or LadybugPool for EventNode queries.
    - sentiment_analyzer (OPTIONAL): SentimentTrendAnalyzer for sentiment
      blending into trend_score. Built from relational_pool; on failure
      (pool unavailable or construction error), the analyzer is set to None
      and TrendDetector degrades to frequency-only trend_score (R-trend-005).
      This is a deliberate graceful degradation, NOT silent failure — the
      degradation is logged at WARNING level.

    Returns:
        TrendDetector instance (implements TrendDetectionProtocol).

    Raises:
        HTTPException: 503 if graph pool is unavailable.
        RuntimeError: If container is not initialized (propagates to caller).

    """
    from container import get_container
    from modules.trend import SentimentTrendAnalyzer, TrendDetector

    container = get_container()

    # Required: graph pool (Neo4j or LadybugDB).
    graph_pool = container.graph_pool()
    if graph_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Graph pool not initialized",
        )

    # Optional: sentiment analyzer for trend_score blending.
    # Degrade to None on any failure (R-trend-005 graceful degradation).
    sentiment_analyzer = None
    try:
        relational_pool = container.relational_pool()
        sentiment_analyzer = SentimentTrendAnalyzer(pool=relational_pool)
    except Exception as exc:
        log.warning(
            "trend_detection_sentiment_analyzer_unavailable",
            error=str(exc),
            exc_type=type(exc).__name__,
            degradation="frequency_only",
        )

    return TrendDetector(graph_pool=graph_pool, sentiment_analyzer=sentiment_analyzer)


def _serialize_detection_result(result: TrendDetectionResult) -> dict:
    """Serialize TrendDetectionResult dataclass to a JSON-friendly dict.

    All 5 fields from spec R-trend-001 are included. The ``list`` field
    name is preserved per spec (shadows Python builtin within the dataclass;
    serialized as a regular dict key here, no shadowing concern — mirrors
    the SentimentTrendResult.list handling in ``_serialize_trend_result``).

    Args:
        result: TrendDetectionResult from service.

    Returns:
        Dict with all 5 TrendDetectionResult fields.

    """
    return {
        "window_days": result.window_days,
        "entity_type": result.entity_type,
        "trends": result.trends,
        "list": result.list,
        "status": result.status,
    }


@router.get("/detection", response_model=APIResponse)
async def get_trend_detection(
    window: str = Query(
        "7d",
        description=(
            "Time window in 'Nd' format. Supported values: '7d', '30d'. "
            "Defaults to '7d'. Other values return HTTP 400."
        ),
    ),
    entity_type: str | None = Query(
        None,
        description=(
            "Optional entity_type filter applied to EventNode.name "
            "(R-trend-002: '按 entity_type 过滤'). None aggregates trends "
            "across all entity types. URL-encoded special chars are "
            "supported (e.g. 'Johnson & Johnson' → 'Johnson%20%26%20Johnson')."
        ),
    ),
    _: str = Depends(verify_api_key),
) -> APIResponse[dict]:
    """Detect trending entities over a time window (R-trend-004).

    Returns ``TrendDetectionResult`` with:
    - ``trends``: per-entity entries with trend_score, direction, and
      frequency_change. Empty when status='insufficient_data'.
    - ``list``: aggregated MENTIONS heat per-day buckets (day/mentions/count).
    - ``status``: 'ok' when EventNode count >= 50 (R-trend-002);
      'insufficient_data' when < 50 (R-trend-003).

    No-data contract (R-trend-003/004): HTTP 200 with
    ``status='insufficient_data', trends=[], list=[]`` when EventNode count
    < 50 — data insufficiency is NOT an error, reported via the status field.

    Args:
        window: Time window string ('7d' or '30d', default '7d').
        entity_type: Optional EventNode.name filter (default None).

    Returns:
        APIResponse with TrendDetectionResult dict.

    Raises:
        HTTPException: 400 if window format/value is invalid or service
            raises ValueError (defense-in-depth).
        HTTPException: 500 on service failure (Rule 12: fail loud).
        HTTPException: 503 if graph pool is unavailable.

    """
    # Parse window string → int days (validates format + supported values).
    # Shares _parse_window with sentiment endpoint (T013).
    window_days = _parse_window(window)

    # Normalize entity_type: empty string → None (treat as "no filter").
    # entity_type is genuinely optional per spec R-trend-002 (None aggregates
    # all), unlike sentiment entity which is required (Constraints).
    entity_type_clean: str | None = None
    if entity_type is not None and entity_type.strip():
        entity_type_clean = entity_type.strip()

    try:
        service = _get_trend_detection_service()
        result = await service.detect_trends(
            window_days=window_days,
            entity_type=entity_type_clean,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        # Service-layer validation (defense-in-depth): map to 400.
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request parameters: {exc}",
        ) from exc
    except Exception as exc:
        log.error(
            "trend_detection_failed",
            window_days=window_days,
            entity_type=entity_type_clean,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to detect trends: {exc}",
        ) from exc

    return success_response(_serialize_detection_result(result))


__all__ = ["router"]
