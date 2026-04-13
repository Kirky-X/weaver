# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API authentication middleware.

Provides API key authentication with optional admin role support.
Admin API keys are configured via WEAVER_API__ADMIN_API_KEY environment variable
and grant access to sensitive endpoints like /config.
"""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from core.observability import get_logger

log = get_logger("auth_middleware")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Minimum API key length for security
MIN_API_KEY_LENGTH = 32


async def verify_api_key(
    key: str | None = Security(api_key_header),
) -> str:
    """Verify the API key from the request header.

    Uses constant-time comparison to prevent timing attacks.
    Validates that the expected key is properly configured.

    Args:
        key: API key from the request header.

    Returns:
        The validated API key.

    Raises:
        HTTPException: If the API key is missing, invalid, or not configured.

    """
    from container import get_settings

    settings = get_settings()

    if key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
        )

    expected_key = settings.api.get_api_key()

    # Security check: ensure expected_key is properly configured
    if not expected_key or len(expected_key) < MIN_API_KEY_LENGTH:
        environment = os.environ.get("ENVIRONMENT", "development")
        if environment == "production":
            raise HTTPException(
                status_code=500,
                detail="API key not properly configured. "
                "Set WEAVER_API__API_KEY environment variable with at least 32 characters.",
            )
        # Development mode: warn but allow weak keys
        log = get_logger("api.auth")
        log.warning(
            "weak_api_key_detected",
            key_length=len(expected_key) if expected_key else 0,
            recommended_length=MIN_API_KEY_LENGTH,
        )

    if not secrets.compare_digest(key, expected_key):
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key",
        )

    return key


async def verify_admin_api_key(
    key: str | None = Security(api_key_header),
) -> str:
    """Verify admin API key for sensitive endpoints.

    Admin endpoints require a dedicated admin API key configured via
    WEAVER_API__ADMIN_API_KEY environment variable.

    If admin key is not configured, the regular API key is used as fallback
    (development mode behavior).

    Args:
        key: API key from the request header.

    Returns:
        The validated admin API key.

    Raises:
        HTTPException: If the key is missing, invalid, or not an admin key.

    """
    from container import get_settings

    settings = get_settings()

    if key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Admin endpoints require X-API-Key header.",
        )

    # Check admin key if configured
    admin_key = settings.api.admin_api_key

    if admin_key and len(admin_key) >= MIN_API_KEY_LENGTH:
        # Admin key configured: require exact match
        if secrets.compare_digest(key, admin_key):
            log.debug("admin_api_key_verified", key_prefix=key[:8] + "...")
            return key
        # Not admin key, check if it's regular key
        expected_key = settings.api.get_api_key()
        if secrets.compare_digest(key, expected_key):
            raise HTTPException(
                status_code=403,
                detail="Admin access required. Regular API key not authorized for this endpoint.",
            )
        # Invalid key
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key",
        )

    # Admin key not configured: fallback to regular key (development mode)
    environment = os.environ.get("ENVIRONMENT", "development")
    if environment == "production":
        raise HTTPException(
            status_code=500,
            detail="Admin API key not configured. "
            "Set WEAVER_API__ADMIN_API_KEY environment variable for production.",
        )

    # Development: regular key grants admin access
    log.warning("admin_key_not_configured_using_regular_key")
    return await verify_api_key(key)


async def verify_api_key_optional(
    key: str | None = Security(api_key_header),
) -> str | None:
    """Verify API key optionally based on configuration.

    For endpoints like /metrics where authentication may be optional.
    If WEAVER__API__REQUIRE_AUTH_FOR_METRICS=true, key is required.
    Otherwise, key validation is optional (returns None if missing).

    Args:
        key: API key from the request header (optional).

    Returns:
        The validated API key if provided and valid, None if not required.

    Raises:
        HTTPException: If key is required but missing, or if key is invalid.

    """
    from container import get_settings

    settings = get_settings()

    # Check if authentication is required for this endpoint
    if settings.api.require_auth_for_metrics:
        # Auth required: use standard verification
        return await verify_api_key(key)

    # Auth not required: optional verification
    if key is None:
        return None

    # If key provided, validate it (but don't require it)
    expected_key = settings.api.get_api_key()
    if expected_key and secrets.compare_digest(key, expected_key):
        return key

    # Invalid key provided - still reject even if optional
    raise HTTPException(
        status_code=403,
        detail="Invalid API Key",
    )
