# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Sources API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import verify_api_key
from modules.source.models import SourceConfig
from modules.source.registry import SourceRegistry

router = APIRouter(prefix="/sources", tags=["sources"])


# ── Request/Response Models ─────────────────────────────────────


class SourceCreateRequest(BaseModel):
    """Request model for creating a new source."""

    id: str = Field(..., description="Unique source identifier")
    name: str = Field(..., description="Human-readable name")
    url: str = Field(..., description="Feed URL (RSS/Atom)")
    source_type: str = Field(default="rss", description="Type of source")
    enabled: bool = Field(default=True, description="Whether the source is active")
    interval_minutes: int = Field(default=30, description="Crawl interval in minutes")
    per_host_concurrency: int = Field(default=2, description="Max concurrent requests")


class SourceUpdateRequest(BaseModel):
    """Request model for updating a source."""

    name: str | None = None
    url: str | None = None
    source_type: str | None = None
    enabled: bool | None = None
    interval_minutes: int | None = None
    per_host_concurrency: int | None = None


class SourceResponse(BaseModel):
    """Response model for a source."""

    id: str
    name: str
    url: str
    source_type: str
    enabled: bool
    interval_minutes: int
    per_host_concurrency: int
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
            last_crawl_time=config.last_crawl_time,
        )


# ── Dependency for Source Registry ───────────────────────────────

# This will be injected via container
_source_registry: SourceRegistry | None = None


def set_source_registry(registry: Any) -> None:
    """Set the global source registry instance."""
    global _source_registry
    _source_registry = registry


def get_source_registry() -> Any:
    """Get the source registry instance."""
    if _source_registry is None:
        raise HTTPException(
            status_code=503,
            detail="Source registry not initialized",
        )
    return _source_registry


# ── Endpoints ───────────────────────────────────────────────────


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    enabled_only: bool = True,
    _: str = Depends(verify_api_key),
    registry: Any = Depends(get_source_registry),
) -> list[SourceResponse]:
    """Get all registered sources.

    Args:
        enabled_only: If True, only return enabled sources.
        _: Verified API key.
        registry: Source registry instance.

    Returns:
        List of source configurations.
    """
    sources = registry.list_sources(enabled_only=enabled_only)
    return [SourceResponse.from_config(s) for s in sources]


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    request: SourceCreateRequest,
    _: str = Depends(verify_api_key),
    registry: Any = Depends(get_source_registry),
) -> SourceResponse:
    """Create a new news source.

    Args:
        request: Source configuration to create.
        _: Verified API key.
        registry: Source registry instance.

    Returns:
        The created source configuration.

    Raises:
        HTTPException: If source ID already exists.
    """
    existing = registry.get_source(request.id)
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
    )
    registry.add_source(config)
    return SourceResponse.from_config(config)


@router.put("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str,
    request: SourceUpdateRequest,
    _: str = Depends(verify_api_key),
    registry: Any = Depends(get_source_registry),
) -> SourceResponse:
    """Update an existing news source.

    Args:
        source_id: The source ID to update.
        request: Fields to update.
        _: Verified API key.
        registry: Source registry instance.

    Returns:
        The updated source configuration.

    Raises:
        HTTPException: If source not found.
    """
    existing = registry.get_source(source_id)
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

    registry.add_source(existing)
    return SourceResponse.from_config(existing)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    _: str = Depends(verify_api_key),
    registry: Any = Depends(get_source_registry),
) -> None:
    """Delete a news source.

    Args:
        source_id: The source ID to delete.
        _: Verified API key.
        registry: Source registry instance.

    Raises:
        HTTPException: If source not found.
    """
    existing = registry.get_source(source_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Source '{source_id}' not found",
        )

    registry.remove_source(source_id)
