# Copyright (c) 2026 KirkyX. All Rights Reserved
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
from api.middleware.auth import verify_admin_api_key, verify_api_key
from api.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Memory System Diagnostics ─────────────────────────────────────


class MemoryDiagnosticResponse(BaseModel):
    """Response model for memory system diagnostics."""

    memory_service_initialized: bool
    temporal_event_count: int
    causal_link_count: int
    pending_consolidation: int
    slow_path_enabled: bool
    scheduler_job_registered: bool


@router.get("/memory/diagnostics", response_model=APIResponse[MemoryDiagnosticResponse])
async def memory_diagnostics(
    request: Request,
    _: str = Depends(verify_api_key),
    container: Any = Depends(_get_container),
) -> APIResponse[MemoryDiagnosticResponse]:
    """Diagnostic endpoint for memory system health.

    Returns status of memory service initialization, event counts,
    and scheduler registration for troubleshooting.

    Args:
        _: Verified API key.
        container: Application container.

    Returns:
        Memory system diagnostic data.

    """
    diagnostics = await container.memory_diagnostics()
    scheduler_registered = container.is_job_registered("memory_consolidation")

    return success_response(
        MemoryDiagnosticResponse(
            memory_service_initialized=diagnostics["service_initialized"],
            temporal_event_count=diagnostics["temporal_event_count"],
            causal_link_count=diagnostics["causal_link_count"],
            pending_consolidation=diagnostics["pending_consolidation"],
            slow_path_enabled=diagnostics["slow_path_enabled"],
            scheduler_job_registered=scheduler_registered,
        )
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
