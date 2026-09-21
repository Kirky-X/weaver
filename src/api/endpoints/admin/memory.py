# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Admin endpoints for memory system diagnostics.

Endpoints:
- GET /memory/diagnostics
- POST /memory/trigger-consolidation
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.endpoints.admin.admin import _get_container
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Memory System Diagnostics ─────────────────────────────────────

# The diagnostics implementation and its response model live once in
# api.endpoints.monitoring.memory; the admin path registers the same
# handler (identical admin-key auth, identical payload).
from api.endpoints.monitoring.memory import (  # noqa: E402
    MemoryDiagnosticResponse,
    memory_diagnostics,
)

router.add_api_route(
    "/memory/diagnostics",
    memory_diagnostics,
    methods=["GET"],
    response_model=APIResponse[MemoryDiagnosticResponse],
    name="admin_memory_diagnostics",
)


class ConsolidationResult(BaseModel):
    """Response model for consolidation trigger."""

    processed: int
    event_ids: list[str]


@router.post(
    "/memory/trigger-consolidation",
    response_model=APIResponse[ConsolidationResult],
)
async def trigger_consolidation(
    request: Request,
    batch_size: int = Query(10, ge=1, le=100),
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
    container: Any = Depends(_get_container),
) -> APIResponse[ConsolidationResult]:
    """Manually trigger memory consolidation (slow path).

    Forces the slow path worker to process pending events for
    causal inference. Useful when scheduler has not run yet.

    Args:
        batch_size: Number of events to process (1-100).
        _: Verified API key.
        container: Application container.

    Returns:
        Consolidation results with processed event IDs.

    """
    ms = container.memory_service
    if ms is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")

    results = await ms.consolidate(batch_size=batch_size)

    return success_response(
        ConsolidationResult(
            processed=len(results),
            event_ids=[r.event_id for r in results if hasattr(r, "event_id")],
        )
    )


# ── Memory Search (MAGMA read path) ───────────────────────────────


class MemorySearchResponse(BaseModel):
    """Response model for memory search."""

    query: str
    intent: str | None = None
    results: list[dict[str, Any]]
    total: int


@router.get(
    "/memory/search",
    response_model=APIResponse[MemorySearchResponse],
)
async def memory_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    intent: str | None = Query(
        None, description="Optional intent (WHY/WHEN/ENTITY/OPEN/MULTI_HOP)"
    ),
    _: str = Depends(verify_admin_api_key),
    container: Any = Depends(_get_container),
) -> APIResponse[MemorySearchResponse]:
    """Search the MAGMA memory graph with intent-aware beam retrieval.

    Exposes the write-only memory system's read path: adaptive beam search
    across temporal/causal/entity graph views, with knowledge-cache reuse.

    Args:
        request: Incoming request.
        q: Natural-language query.
        intent: Optional intent override; classified from the query when omitted.
        _: Verified API key.
        container: Application container.

    Returns:
        Scored memory events. A result with ``cache_hit=true`` carries a
        score of 1.0 that is not comparable to fresh normalized scores.

    """
    ms = container.memory_service
    if ms is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")

    intent_enum = None
    if intent is not None:
        from modules.memory.core.graph_types import IntentType

        try:
            intent_enum = IntentType(intent.upper())
        except ValueError:
            valid = [m.value for m in IntentType]
            raise HTTPException(
                status_code=422, detail=f"Invalid intent {intent!r}. Valid: {valid}"
            ) from None

    try:
        results = await ms.search(q, intent=intent_enum)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Memory search failed: {exc}") from exc

    return success_response(
        MemorySearchResponse(
            query=q,
            intent=intent_enum.value if intent_enum else None,
            results=results,
            total=len(results),
        )
    )
