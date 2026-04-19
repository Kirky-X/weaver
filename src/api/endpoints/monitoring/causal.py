# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Causal graph monitoring endpoints for statistics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_container
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/monitoring/causal", tags=["monitoring", "causal"])


# ── Causal Graph Statistics ─────────────────────────────────────


@router.get(
    "/stats",
    response_model=APIResponse[dict],
    summary="Get causal graph statistics",
)
async def get_causal_stats(
    _: str = Depends(verify_admin_api_key),
    container: Any = Depends(get_container),
) -> APIResponse[dict]:
    """Get statistics about the causal graph.

    Returns count of causal edges (CAUSES, ENABLES, PREVENTS).

    Args:
        _: Verified admin API key.
        container: Application container.

    Returns:
        Causal graph statistics.

    """
    causal_repo = container.causal_repo()
    if causal_repo is None:
        raise HTTPException(
            status_code=503,
            detail="Causal graph repository unavailable",
        )

    count = await causal_repo.count_causal_links()

    return success_response(
        {
            "causal_edges": count,
            "edge_types": ["CAUSES", "ENABLES", "PREVENTS"],
        }
    )
