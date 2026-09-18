# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
