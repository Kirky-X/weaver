# Copyright (c) 2026 KirkyX. All Rights Reserved
"""API authentication middleware.

Provides API key authentication with database-backed multi-key support.
Supports key scopes, expiry, revocation, and traffic anomaly detection.
"""

import secrets

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from core.observability import get_logger

log = get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Minimum API key length for security
MIN_API_KEY_LENGTH = 32


async def _get_api_key_manager():
    """Lazy-load ApiKeyManager from container."""
    try:
        from container import get_container

        container = get_container()
        from core.security import ApiKeyManager

        return ApiKeyManager(container.relational_pool())
    except Exception:
        return None


async def _get_traffic_detector():
    """Lazy-load TrafficAnomalyDetector from container."""
    try:
        from container import get_container

        container = get_container()
        from core.security import TrafficAnomalyDetector

        cache = container.cache_client()
        return TrafficAnomalyDetector(cache)
    except Exception:
        return None


async def verify_api_key(
    key: str | None = Security(api_key_header),
    request: Request = None,  # type: ignore[assignment]
) -> str:
    """Verify the API key from the request header.

    Supports two modes:
    1. Database-backed multi-key (api_keys table) with scopes and expiry
    2. Legacy single-key fallback (env variable)

    Args:
        key: API key from the request header.
        request: Optional FastAPI request for traffic detection.

    Returns:
        The validated key_id string or "env-key" for env-var-based fallback.

    Raises:
        HTTPException: If the API key is missing or invalid.

    """
    from container import get_settings

    if key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
        )

    # Try database-backed key validation first
    key_manager = await _get_api_key_manager()
    if key_manager:
        key_info = await key_manager.validate_key(key)
        if key_info:
            # Traffic anomaly check
            detector = await _get_traffic_detector()
            if detector and request:
                client_ip = request.client.host if request.client else "unknown"
                decision = await detector.check_request(
                    key_id=key_info["key_id"],
                    ip=client_ip,
                )
                if decision.action == "block":
                    raise HTTPException(
                        status_code=429,
                        detail=f"Rate limit exceeded: {decision.reason}",
                    )

            return key_info["key_id"]

    # Fallback: env-var-based key
    settings = get_settings()
    expected_key = settings.api.get_api_key()
    admin_key = settings.api.admin_api_key

    # Accept admin key for regular endpoints
    if (
        admin_key
        and len(admin_key) >= MIN_API_KEY_LENGTH
        and secrets.compare_digest(key, admin_key)
    ):
        return "admin"

    if not expected_key or len(expected_key) < MIN_API_KEY_LENGTH:
        environment = getattr(settings, "environment", "development")
        if environment == "production":
            raise HTTPException(
                status_code=500,
                detail="API key not properly configured. "
                "Set WEAVER_API__API_KEY environment variable with at least 32 characters.",
            )
        raise HTTPException(
            status_code=500,
            detail=f"API key too short. Current length: {len(expected_key) if expected_key else 0}, "
            f"minimum required: {MIN_API_KEY_LENGTH} characters.",
        )

    if not secrets.compare_digest(key, expected_key):
        raise HTTPException(status_code=403, detail="Invalid API Key")

    return "env-key"


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

    # Admin key not configured: reject with 503 Service Unavailable
    # (configuration issue, not server internal error)
    if not admin_key:
        log.error("admin_key_not_configured")
        raise HTTPException(
            status_code=503,
            detail="Admin API key not configured. "
            "Set WEAVER_API__ADMIN_API_KEY environment variable.",
        )

    raise HTTPException(
        status_code=403,
        detail="Invalid API Key",
    )


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
