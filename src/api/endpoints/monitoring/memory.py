# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Memory system monitoring endpoints for diagnostics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import get_container
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/monitoring/memory", tags=["monitoring", "memory"])


# ── Response Models ─────────────────────────────────────────────


class MemoryDiagnosticResponse(BaseModel):
    """Response model for memory system diagnostics."""

    memory_service_initialized: bool
    temporal_event_count: int
    causal_link_count: int
    pending_consolidation: int
    slow_path_enabled: bool
    scheduler_job_registered: bool


# ── Memory Diagnostics Endpoint ─────────────────────────────────


@router.get("/diagnostics", response_model=APIResponse[MemoryDiagnosticResponse])
async def memory_diagnostics(
    _: str = Depends(verify_admin_api_key),
    container: Any = Depends(get_container),
) -> APIResponse[MemoryDiagnosticResponse]:
    """Diagnostic endpoint for memory system health.

    Returns status of memory service initialization, event counts,
    and scheduler registration for troubleshooting.

    Args:
        _: Verified admin API key.
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
