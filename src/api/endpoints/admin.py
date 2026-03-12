"""Admin API endpoints for source authority management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import verify_api_key
from core.db.postgres import PostgresPool
from modules.storage.source_authority_repo import SourceAuthorityRepo
from core.observability.logging import get_logger

log = get_logger("admin_api")

router = APIRouter(prefix="/admin", tags=["admin"])


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


# ── Dependency for Source Authority Repo ───────────────────────

_source_authority_repo: "SourceAuthorityRepo | None" = None


def set_source_authority_repo(repo: SourceAuthorityRepo) -> None:
    """Set the global source authority repo instance."""
    global _source_authority_repo
    _source_authority_repo = repo


def get_source_authority_repo() -> SourceAuthorityRepo:
    """Get the source authority repo instance."""
    if _source_authority_repo is None:
        raise HTTPException(
            status_code=503,
            detail="Source authority repo not initialized",
        )
    return _source_authority_repo


# ── Endpoints ───────────────────────────────────────────────────


@router.get("/sources/authorities", response_model=list[AuthorityResponse])
async def list_authorities(
    needs_review_only: bool = False,
    _: str = Depends(verify_api_key),
    repo: SourceAuthorityRepo = Depends(get_source_authority_repo),
) -> list[AuthorityResponse]:
    """Get source authorities, optionally filtered by those needing review.

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
        # Get all - would need to add a method to repo
        # For now, just return needs_review
        authorities = await repo.get_needs_review()

    return [
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


@router.patch("/sources/{host}/authority", response_model=UpdateAuthorityResponse)
async def update_authority(
    host: str,
    request: UpdateAuthorityRequest,
    _: str = Depends(verify_api_key),
    repo: SourceAuthorityRepo = Depends(get_source_authority_repo),
) -> UpdateAuthorityResponse:
    """Update authority score for a source host.

    Args:
        host: The source hostname.
        request: Authority update data.
        _: Verified API key.
        repo: Source authority repository.

    Returns:
        Updated authority information.

    Raises:
        HTTPException: If no updates provided.
    """
    if request.authority is None and request.tier is None and request.description is None:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be updated",
        )

    # Get current authority to preserve values
    authority = await repo.get_or_create(host)
    new_authority = request.authority if request.authority is not None else float(authority.authority)
    new_tier = request.tier if request.tier is not None else authority.tier

    # Update
    await repo.update_authority(
        host=host,
        authority=new_authority,
        tier=new_tier,
        needs_review=False,  # Mark as reviewed
    )

    log.info(
        "authority_updated",
        host=host,
        authority=new_authority,
        tier=new_tier,
    )

    return UpdateAuthorityResponse(
        host=host,
        authority=request.authority,
        tier=request.tier,
        description=request.description,
    )


@router.get("/sources/{host}/authority", response_model=AuthorityResponse)
async def get_authority(
    host: str,
    _: str = Depends(verify_api_key),
    repo: SourceAuthorityRepo = Depends(get_source_authority_repo),
) -> AuthorityResponse:
    """Get authority for a specific source host.

    Args:
        host: The source hostname.
        _: Verified API key.
        repo: Source authority repository.

    Returns:
        Source authority information.

    Raises:
        HTTPException: If host not found (will auto-create on first access).
    """
    authority = await repo.get_or_create(host)

    return AuthorityResponse(
        id=authority.id,
        host=authority.host,
        authority=float(authority.authority),
        tier=authority.tier,
        description=authority.description,
        needs_review=authority.needs_review,
        auto_score=float(authority.auto_score) if authority.auto_score else None,
        updated_at=authority.updated_at.isoformat(),
    )
