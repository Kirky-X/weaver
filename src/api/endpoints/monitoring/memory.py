# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Memory system monitoring endpoints for diagnostics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies import get_container
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response
from pydantic import BaseModel

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
    from core.observability import get_logger

    log = get_logger(__name__)

    ms = container.memory_service
    service_initialized = ms is not None

    temporal_count = 0
    causal_count = 0
    pending_count = 0
    slow_path_enabled = False
    scheduler_registered = False

    if service_initialized and ms is not None:
        try:
            temporal_count = await ms._temporal_repo.count_events()
            causal_count = await ms._causal_repo.count_causal_links()
            pending_count = await ms._consolidation_queue.length()
            slow_path_enabled = ms._config.slow_path_enabled
        except Exception as exc:
            log.warning("memory_diagnostic_query_failed", error=str(exc))

    try:
        scheduler = container._scheduler
        if scheduler is not None:
            jobs = scheduler.get_jobs()
            scheduler_registered = any(j.id == "memory_consolidation" for j in jobs)
    except Exception:
        pass

    return success_response(
        MemoryDiagnosticResponse(
            memory_service_initialized=service_initialized,
            temporal_event_count=temporal_count,
            causal_link_count=causal_count,
            pending_consolidation=pending_count,
            slow_path_enabled=slow_path_enabled,
            scheduler_job_registered=scheduler_registered,
        )
    )
