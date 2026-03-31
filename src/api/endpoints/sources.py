# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Sources API endpoints."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.dependencies import get_source_config_repo, get_source_scheduler
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from modules.ingestion.domain.models import SourceConfig
from modules.ingestion.scheduling.scheduler import SourceScheduler
from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo

router = APIRouter(prefix="/sources", tags=["sources"])


# ── URL Validation Helper ─────────────────────────────────────

# Dangerous hosts that should be blocked for security
_DANGEROUS_HOSTS = {"169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1"}


def _validate_source_url(v: str) -> str:
    """Validate URL format for security (synchronous check only).

    Args:
        v: URL string to validate.

    Returns:
        The validated URL string.

    Raises:
        ValueError: If URL is invalid or points to a blocked host.
    """
    parsed = urlparse(v)
    if not parsed.scheme:
        raise ValueError("URL must include a scheme (http:// or https://)")
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("URL scheme must be http or https")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    if parsed.hostname.lower() in _DANGEROUS_HOSTS:
        raise ValueError("Access to this host is blocked for security reasons")
    return v


# ── Request/Response Models ─────────────────────────────────────


class SourceCreateRequest(BaseModel):
    """Request model for creating a new source."""

    id: str = Field(..., description="Unique source identifier")
    name: str = Field(..., description="Human-readable name")
    url: str = Field(..., description="Feed URL (RSS/Atom)")
    source_type: str = Field(default="rss", description="Type of source")
    enabled: bool = Field(default=True, description="Whether the source is active")
    interval_minutes: int = Field(
        default=30, ge=5, le=1440, description="Crawl interval in minutes"
    )
    per_host_concurrency: int = Field(default=2, ge=1, le=10, description="Max concurrent requests")
    credibility: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Preset credibility score (0.0-1.0)",
    )
    tier: int | None = Field(
        default=None,
        ge=1,
        le=3,
        description="Source tier: 1=authoritative, 2=credible, 3=ordinary",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format for security."""
        return _validate_source_url(v)

    @field_validator("id", "name")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Validate that required string fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()


class SourceUpdateRequest(BaseModel):
    """Request model for updating a source."""

    name: str | None = None
    url: str | None = None
    source_type: str | None = None
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    per_host_concurrency: int | None = Field(default=None, ge=1, le=10)
    credibility: float | None = Field(default=None, ge=0.0, le=1.0)
    tier: int | None = Field(default=None, ge=1, le=3)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        """Validate URL format for security."""
        if v is None:
            return v
        return _validate_source_url(v)


class SourceResponse(BaseModel):
    """Response model for a source."""

    id: str
    name: str
    url: str
    source_type: str
    enabled: bool
    interval_minutes: int
    per_host_concurrency: int
    credibility: float | None = None
    tier: int | None = None
    last_crawl_time: datetime | None = None

    @classmethod
    def from_config(cls, config: SourceConfig) -> SourceResponse:
        return cls(
            id=config.id,
            name=config.name,
            url=config.url,
            source_type=config.source_type,
            enabled=config.enabled,
            interval_minutes=config.interval_minutes,
            per_host_concurrency=config.per_host_concurrency,
            credibility=config.credibility,
            tier=config.tier,
            last_crawl_time=config.last_crawl_time,
        )


# ── Endpoints ───────────────────────────────────────────────────


@router.get("", response_model=APIResponse[list[SourceResponse]])
async def list_sources(
    enabled_only: bool = True,
    _: str = Depends(verify_api_key),
    repo: SourceConfigRepo = Depends(get_source_config_repo),
) -> APIResponse[list[SourceResponse]]:
    """Get all registered sources.

    Args:
        enabled_only: If True, only return enabled sources.
        _: Verified API key.
        repo: Source config repository instance.

    Returns:
        List of source configurations.
    """
    sources = await repo.list_sources(enabled_only=enabled_only)
    return success_response([SourceResponse.from_config(s) for s in sources])


@router.get("/{source_id}", response_model=APIResponse[SourceResponse])
async def get_source(
    source_id: str,
    _: str = Depends(verify_api_key),
    repo: SourceConfigRepo = Depends(get_source_config_repo),
) -> APIResponse[SourceResponse]:
    """Get a single source by ID.

    Args:
        source_id: The unique source identifier.
        _: Verified API key.
        repo: Source config repository instance.

    Returns:
        Source configuration.

    Raises:
        HTTPException: 404 if source not found.
    """
    source = await repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
    return success_response(SourceResponse.from_config(source))


@router.post("", response_model=APIResponse[SourceResponse], status_code=201)
async def create_source(
    request: SourceCreateRequest,
    _: str = Depends(verify_api_key),
    repo: SourceConfigRepo = Depends(get_source_config_repo),
    scheduler: SourceScheduler = Depends(get_source_scheduler),
) -> APIResponse[SourceResponse]:
    """Create a new news source.

    Args:
        request: Source configuration to create.
        _: Verified API key.
        repo: Source config repository instance.

    Returns:
        The created source configuration.

    Raises:
        HTTPException: If source ID already exists.
    """
    existing = await repo.get(request.id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Source with id '{request.id}' already exists",
        )

    config = SourceConfig(
        id=request.id,
        name=request.name,
        url=request.url,
        source_type=request.source_type,
        enabled=request.enabled,
        interval_minutes=request.interval_minutes,
        per_host_concurrency=request.per_host_concurrency,
        credibility=request.credibility,
        tier=request.tier,
    )
    saved = await repo.upsert(config)

    # Add to in-memory registry so scheduler can find it
    scheduler._registry.add_source(saved)

    return success_response(SourceResponse.from_config(saved))


@router.put("/{source_id}", response_model=APIResponse[SourceResponse])
async def update_source(
    source_id: str,
    request: SourceUpdateRequest,
    _: str = Depends(verify_api_key),
    repo: SourceConfigRepo = Depends(get_source_config_repo),
) -> APIResponse[SourceResponse]:
    """Update an existing news source.

    Args:
        source_id: The source ID to update.
        request: Fields to update.
        _: Verified API key.
        repo: Source config repository instance.

    Returns:
        The updated source configuration.

    Raises:
        HTTPException: If source not found.
    """
    existing = await repo.get(source_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_id}' not found",
        )

    # Apply updates
    if request.name is not None:
        existing.name = request.name
    if request.url is not None:
        existing.url = request.url
    if request.source_type is not None:
        existing.source_type = request.source_type
    if request.enabled is not None:
        existing.enabled = request.enabled
    if request.interval_minutes is not None:
        existing.interval_minutes = request.interval_minutes
    if request.per_host_concurrency is not None:
        existing.per_host_concurrency = request.per_host_concurrency
    if request.credibility is not None:
        existing.credibility = request.credibility
    if request.tier is not None:
        existing.tier = request.tier

    saved = await repo.upsert(existing)
    return success_response(SourceResponse.from_config(saved))


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    _: str = Depends(verify_api_key),
    repo: SourceConfigRepo = Depends(get_source_config_repo),
) -> None:
    """Delete a news source.

    Args:
        source_id: The source ID to delete.
        _: Verified API key.
        repo: Source config repository instance.

    Raises:
        HTTPException: If source not found.
    """
    deleted = await repo.delete(source_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_id}' not found",
        )
