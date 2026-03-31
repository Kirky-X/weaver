# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API authentication middleware."""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

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

    expected_key = settings.api.api_key

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
        from core.observability.logging import get_logger

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
