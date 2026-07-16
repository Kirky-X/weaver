# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Sources API endpoints."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.dependencies import get_smart_fetcher, get_source_config_repo, get_source_scheduler
from api.middleware.auth import verify_api_key
from api.schemas.response import APIResponse, success_response
from core.constants import SourceType
from core.observability import get_logger
from core.security.safe_echo import safe_echo
from modules.ingestion import SourceConfig, SourceConfigRepo, SourceScheduler

log = get_logger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])

# ── URL Validation Helper ─────────────────────────────────────

# Dangerous hosts that should be blocked for security
_DANGEROUS_HOSTS = {"169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1"}

# RFC 1035 limits for hostname validation
_MAX_HOSTNAME_LEN = 253
_MAX_LABEL_LEN = 63
# Each label: letter/digit followed by letters/digits/hyphens, ending with letter/digit
_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

# Minimum number of feed entries for a valid feed
_MIN_FEED_ENTRIES = 1

# Feed validation timeout (seconds)
_FEED_VALIDATION_TIMEOUT = 15.0


def _validate_source_url(v: str) -> str:
    """Validate URL format for security (synchronous check only).

    Performs:
    1. Scheme check (http/https only)
    2. Hostname presence
    3. Dangerous host blocklist
    4. Hostname length (RFC 1035: max 253 chars)
    5. Per-label length (RFC 1035: max 63 chars)
    6. Per-label character set (letters, digits, hyphens only)

    Args:
        v: URL string to validate.

    Returns:
        The validated URL string.

    Raises:
        ValueError: If URL is invalid or points to a blocked/abnormal host.

    """
    parsed = urlparse(v)
    if not parsed.scheme:
        raise ValueError("URL must include a scheme (http:// or https://)")
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("URL scheme must be http or https")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    hostname = parsed.hostname.lower()
    if hostname in _DANGEROUS_HOSTS:
        raise ValueError("Access to this host is blocked for security reasons")
    # RFC 1035: total hostname length ≤ 253 characters
    if len(hostname) > _MAX_HOSTNAME_LEN:
        raise ValueError(f"Hostname too long ({len(hostname)} chars, max {_MAX_HOSTNAME_LEN})")
    # RFC 1035: each label ≤ 63 chars, only letters/digits/hyphens
    for label in hostname.split("."):
        if len(label) > _MAX_LABEL_LEN:
            raise ValueError(
                f"Hostname label too long ({len(label)} chars, max {_MAX_LABEL_LEN}): {label[:20]}..."
            )
        if not _LABEL_PATTERN.match(label):
            raise ValueError(f"Hostname label contains invalid characters: {label[:20]}")
    return v


async def _validate_feed_reachable(
    url: str, fetcher: Any, source_type: str = SourceType.RSS.value
) -> None:
    """Validate that a feed URL is reachable and contains valid content.

    Performs the following checks:
    1. HTTP fetch succeeds (network reachable, no DNS errors)
    2. HTTP status code is 200
    3. Response body parses as a valid RSS/Atom feed (for RSS source type)
    4. Feed contains at least one entry

    Args:
        url: Feed URL to validate.
        fetcher: SmartFetcher instance for HTTP requests.
        source_type: Type of source (rss, newsnow). Only RSS feeds are parsed.

    Raises:
        HTTPException: 422 if feed is unreachable, returns non-200 status,
                       or contains no parseable entries.

    """
    import asyncio

    try:
        async with asyncio.timeout(_FEED_VALIDATION_TIMEOUT):
            status_code, content, _ = await fetcher.fetch(url)
    except TimeoutError as exc:
        log.warning("feed_validation_timeout", url=url)
        raise HTTPException(
            status_code=422,
            detail=f"Feed validation timed out after {_FEED_VALIDATION_TIMEOUT}s: {url}",
        ) from exc
    except Exception as exc:
        log.warning("feed_validation_fetch_failed", url=url, error=str(exc))
        raise HTTPException(
            status_code=422,
            detail=f"Feed URL is not reachable: {exc!s}",
        ) from exc

    if status_code != 200:
        log.warning("feed_validation_bad_status", url=url, status=status_code)
        raise HTTPException(
            status_code=422,
            detail=f"Feed URL returned HTTP {status_code}, expected 200",
        )

    # Parse RSS/Atom feeds to validate content
    if source_type == SourceType.RSS.value:
        if not content:
            raise HTTPException(
                status_code=422,
                detail="Feed URL returned empty content",
            )

        feed = feedparser.parse(content)

        # Check for parse errors (feedparser.bozo indicates malformed XML)
        if feed.bozo and not feed.entries:
            bozo_exception = getattr(feed, "bozo_exception", None)
            error_msg = str(bozo_exception) if bozo_exception else "malformed XML"
            log.warning("feed_validation_parse_error", url=url, error=error_msg)
            raise HTTPException(
                status_code=422,
                detail=f"Feed URL does not contain valid RSS/Atom content: {error_msg}",
            )

        if len(feed.entries) < _MIN_FEED_ENTRIES:
            log.warning("feed_validation_no_entries", url=url)
            raise HTTPException(
                status_code=422,
                detail="Feed contains no entries - not a valid news feed",
            )

        log.info(
            "feed_validation_passed",
            url=url,
            entries=len(feed.entries),
        )


# ── Request/Response Models ─────────────────────────────────────


class SourceCreateRequest(BaseModel):
    """Request model for creating a new source."""

    id: str = Field(..., description="Unique source identifier")
    name: str = Field(..., description="Human-readable name")
    url: str = Field(..., description="Feed URL (RSS/Atom)")
    source_type: str = Field(default=SourceType.RSS.value, description="Type of source")
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
        """Create SourceResponse from SourceConfig."""
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
        raise HTTPException(status_code=404, detail=f"Source '{safe_echo(source_id)}' not found")
    return success_response(SourceResponse.from_config(source))


@router.post("", response_model=APIResponse[SourceResponse], status_code=201)
async def create_source(
    request: SourceCreateRequest,
    _: str = Depends(verify_api_key),
    repo: SourceConfigRepo = Depends(get_source_config_repo),
    scheduler: SourceScheduler = Depends(get_source_scheduler),
    fetcher: Any = Depends(get_smart_fetcher),
) -> APIResponse[SourceResponse]:
    """Create a new news source.

    Validates that the feed URL is reachable and contains valid RSS/Atom
    content before persisting the source configuration.

    Args:
        request: Source configuration to create.
        _: Verified API key.
        repo: Source config repository instance.
        scheduler: Source scheduler for registering the source.
        fetcher: Smart fetcher for feed URL validation.

    Returns:
        The created source configuration.

    Raises:
        HTTPException: 409 if source ID already exists.
        HTTPException: 422 if feed URL is unreachable or invalid.

    """
    existing = await repo.get(request.id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Source with id '{request.id}' already exists",
        )

    # Validate feed URL is reachable and contains valid content
    await _validate_feed_reachable(
        url=request.url, fetcher=fetcher, source_type=request.source_type
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
            detail=f"Source '{safe_echo(source_id)}' not found",
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
            detail=f"Source '{safe_echo(source_id)}' not found",
        )
