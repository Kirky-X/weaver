# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Admin endpoints for source authority management.

Endpoints:
- GET /authorities
- PATCH /authorities/{host}
- POST /authorities/refresh-auto-scores
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import get_relational_pool_optional
from api.endpoints.admin.admin import _get_container, _get_source_authority_repo
from api.middleware.auth import verify_admin_api_key, verify_api_key
from api.schemas.response import APIResponse, success_response
from core.observability import get_logger
from modules.storage import SourceAuthorityRepo

log = get_logger("admin_api")

router = APIRouter(prefix="/admin", tags=["admin"])

# RFC 1035 limits for hostname validation (mirrors sources.py)
_MAX_HOSTNAME_LEN = 253
_MAX_LABEL_LEN = 63
_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def _validate_hostname(host: str) -> str:
    """Validate hostname per RFC 1035 to prevent SQLi/overlong/invalid hosts.

    Args:
        host: Hostname string from path parameter.

    Returns:
        Lowercased hostname if valid.

    Raises:
        HTTPException: 422 if hostname violates RFC 1035.

    """
    if not host:
        raise HTTPException(status_code=422, detail="Hostname cannot be empty")
    hostname = host.lower()
    if len(hostname) > _MAX_HOSTNAME_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"Hostname too long ({len(hostname)} chars, max {_MAX_HOSTNAME_LEN})",
        )
    for label in hostname.split("."):
        if len(label) > _MAX_LABEL_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"Hostname label too long ({len(label)} chars, max {_MAX_LABEL_LEN})",
            )
        if not _LABEL_PATTERN.match(label):
            raise HTTPException(
                status_code=422,
                detail=f"Hostname label contains invalid characters: {label[:20]}",
            )
    return hostname


# ── Request/Response Models ─────────────────────────────────────


class AuthorityResponse(BaseModel):
    """Response model for source authority."""

    id: int
    host: str
    authority: float
    tier: int
    description: str | None
    needs_review: bool
    auto_score: float | None
    updated_at: str


class UpdateAuthorityRequest(BaseModel):
    """Request model for updating authority."""

    authority: float | None = Field(None, ge=0, le=1)
    tier: int | None = Field(None, ge=1, le=5)
    description: str | None = None


class UpdateAuthorityResponse(BaseModel):
    """Response for authority update."""

    host: str
    authority: float | None
    tier: int | None
    description: str | None


# ── Authority Endpoints ─────────────────────────────────────────


@router.get("/authorities", response_model=APIResponse[list[AuthorityResponse]])
async def list_authorities(
    request: Request,
    needs_review_only: bool = False,
    _: str = Depends(verify_api_key),
    repo: SourceAuthorityRepo = Depends(_get_source_authority_repo),
) -> APIResponse[list[AuthorityResponse]]:
    """Get source authorities, optionally filtered by those needing review.

    **Migration:** `/admin/sources/authorities` → `/admin/authorities`

    Args:
        needs_review_only: If True, only return authorities that need review.
        _: Verified API key.
        repo: Source authority repository.

    Returns:
        List of source authorities.

    """
    if needs_review_only:
        authorities = await repo.get_needs_review()
    else:
        authorities = await repo.list_all()

    return success_response(
        [
            AuthorityResponse(
                id=a.id,
                host=a.host,
                authority=float(a.authority),
                tier=a.tier,
                description=a.description,
                needs_review=a.needs_review,
                auto_score=float(a.auto_score) if a.auto_score else None,
                updated_at=a.updated_at.isoformat(),
            )
            for a in authorities
        ]
    )


@router.patch("/authorities/{host}", response_model=APIResponse[UpdateAuthorityResponse])
async def update_authority(
    request: Request,
    host: str,
    body: UpdateAuthorityRequest,
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
    repo: SourceAuthorityRepo = Depends(_get_source_authority_repo),
) -> APIResponse[UpdateAuthorityResponse]:
    """Update authority score for a source host.

    **Migration:** `PATCH /admin/sources/{host}/authority` → `PATCH /admin/authorities/{host}`

    Args:
        host: The source hostname.
        body: Authority update data.
        _: Verified API key.
        repo: Source authority repository.

    Returns:
        Updated authority information.

    Raises:
        HTTPException: If no updates provided.

    """
    if body.authority is None and body.tier is None and body.description is None:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be updated",
        )

    # Validate hostname per RFC 1035 before any DB operation
    host = _validate_hostname(host)

    # Get current authority to preserve values
    authority = await repo.get_or_create(host)
    new_authority = body.authority if body.authority is not None else float(authority.authority)
    new_tier = body.tier if body.tier is not None else authority.tier

    # Update
    await repo.update_authority(
        host=host,
        authority=new_authority,
        tier=new_tier,
        needs_review=False,  # Mark as reviewed
        description=body.description,
    )

    log.info(
        "authority_updated",
        host=host,
        authority=new_authority,
        tier=new_tier,
    )

    return success_response(
        UpdateAuthorityResponse(
            host=host,
            authority=body.authority,
            tier=body.tier,
            description=body.description,
        )
    )


# ── Authority Auto Score Refresh ─────────────────────────────────


class AutoScoreRefreshResponse(BaseModel):
    """Response model for auto_score refresh."""

    sources_updated: int
    triggered_at: str


@router.post(
    "/authorities/refresh-auto-scores",
    response_model=APIResponse[AutoScoreRefreshResponse],
)
async def refresh_auto_scores(
    request: Request,
    _: str = Depends(verify_admin_api_key),  # Security: write operation requires admin
    container: Any = Depends(_get_container),
    pool: Any = Depends(get_relational_pool_optional),
) -> APIResponse[AutoScoreRefreshResponse]:
    """Manually trigger source auto_score recalculation.

    Computes auto_score from historical article credibility scores
    for all sources. Updates needs_review=False for auto-scored sources.

    Args:
        _: Verified API key.
        container: Application container.
        pool: Relational database pool (optional, None if not initialized).

    Returns:
        Number of sources updated.

    """
    from sqlalchemy import func, select

    from core.db import Article

    if pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    repo = container.source_authority_repo()
    update_count = 0

    async with pool.session() as session:
        # Get all sources with articles
        stmt = select(Article.source_host).distinct()
        result = await session.execute(stmt)
        hosts = [row[0] for row in result if row[0]]

        if not hosts:
            return success_response(
                AutoScoreRefreshResponse(
                    sources_updated=0,
                    triggered_at=datetime.now(UTC).isoformat(),
                )
            )

        # Performance fix: Use single aggregate query instead of N+1 queries
        # Before: N queries (one per host)
        # After: 1 query with GROUP BY
        avg_stmt = (
            select(
                Article.source_host,
                func.avg(Article.credibility_score).label("avg_credibility"),
            )
            .where(
                Article.source_host.in_(hosts),
                Article.credibility_score.isnot(None),
            )
            .group_by(Article.source_host)
        )

        avg_result = await session.execute(avg_stmt)
        # Filter out NULL hosts to avoid issues with dirty data
        credibility_by_host = {row[0]: float(row[1]) for row in avg_result if row[0] is not None}

        # Update all sources in batch
        for host, avg_score in credibility_by_host.items():
            try:
                await repo.update_auto_score(host, avg_score)
                update_count += 1
            except Exception as exc:
                log.warning("auto_score_update_failed", host=host, error=str(exc))

    return success_response(
        AutoScoreRefreshResponse(
            sources_updated=update_count,
            triggered_at=datetime.now(UTC).isoformat(),
        )
    )
