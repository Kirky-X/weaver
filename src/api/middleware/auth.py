# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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

    # Admin key not configured: return generic 403 to avoid disclosing
    # configuration state to attackers (CWE-200). Server-side log only.
    if not admin_key:
        log.error("admin_key_not_configured")
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    raise HTTPException(
        status_code=403,
        detail="Access denied.",
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


def verify_api_key_with_scopes(*required_scopes: str):
    """Dependency factory: verify API key AND enforce required scopes.

    Closes CWE-862 (Missing Authorization): previously ApiKeyManager stored
    scopes but verify_api_key() never enforced them. Use this dependency on
    endpoints requiring specific scopes (e.g. ``verify_api_key_with_scopes(
    "pipeline:write")``).

    Falls back to verify_api_key() for env-var-based keys (which have no
    scopes stored). Admin keys implicitly pass all scope checks.

    Args:
        *required_scopes: Scopes that the caller's API key must hold.

    Returns:
        FastAPI dependency callable returning the validated key_id.

    Raises:
        HTTPException: 401 if key missing, 403 if scopes insufficient.

    """

    async def _verify(
        key: str | None = Security(api_key_header),
        request: Request = None,  # type: ignore[assignment]
    ) -> str:
        # Single bcrypt verification path: validate the key once via the DB-backed
        # manager. verify_api_key() internally calls key_manager.validate_key(),
        # so calling it here AND re-validating would run bcrypt twice (~200ms
        # extra per request). Instead, validate once and reuse the result.
        if key is None:
            raise HTTPException(
                status_code=401,
                detail="Missing API key. Provide X-API-Key header.",
            )

        key_manager = await _get_api_key_manager()

        # If DB pool is unavailable, fall back to env/admin key verification.
        if key_manager is None:
            return await verify_api_key(key, request)  # Admin/env keys have no scopes.

        # Validate the key once via DB; key_info carries scopes for inspection.
        key_info = await key_manager.validate_key(key)
        if key_info is None:
            # Key not in DB: fall through to env/admin key check (no bcrypt there).
            return await verify_api_key(
                key, request
            )  # Admin/env keys implicitly pass scope checks.

        # DB-backed key validated. Run traffic anomaly check (mirror verify_api_key).
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

        key_id = key_info["key_id"]

        granted = set(key_info.get("scopes", []) or [])
        required = set(required_scopes)
        missing = required - granted

        if missing:
            log.warning(
                "api_key_scope_denied",
                key_id=key_id,
                required=sorted(required),
                granted=sorted(granted),
                missing=sorted(missing),
            )
            raise HTTPException(
                status_code=403,
                detail="Insufficient scopes for this endpoint.",
            )

        # Inject granted scopes onto request.state for downstream use.
        if request is not None:
            request.state.api_key_scopes = sorted(granted)

        return key_id

    return _verify
