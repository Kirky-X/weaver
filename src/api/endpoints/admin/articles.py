# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Admin endpoints for article operations.

Endpoints:
- POST /articles/deduplicate
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.dependencies import get_relational_pool_optional
from api.middleware.auth import verify_admin_api_key
from api.schemas.response import APIResponse, success_response
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger("admin_api")

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Article Management ───────────────────────────────────────────


class DeduplicateResponse(BaseModel):
    """Response model for article deduplication."""

    removed: int
    kept: int


@router.post("/articles/deduplicate", response_model=APIResponse[DeduplicateResponse])
async def deduplicate_articles(
    request: Request,
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
    pool: RelationalPool | None = Depends(get_relational_pool_optional),
) -> APIResponse[DeduplicateResponse]:
    """Remove duplicate articles, keeping the most recent one per source_url.

    This is a cleanup operation for existing data that has duplicates
    due to DuckDB not enforcing unique constraints.

    Args:
        _: Verified API key.
        pool: Relational database pool (optional, None if not initialized).

    Returns:
        Deduplication statistics.

    """
    from modules.storage.postgres.article_repo import ArticleRepo

    if pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    repo = ArticleRepo(pool)
    result = await repo.deduplicate_articles()

    log.info("article_deduplication_complete", removed=result["removed"], kept=result["kept"])

    return success_response(
        DeduplicateResponse(
            removed=result["removed"],
            kept=result["kept"],
        )
    )
