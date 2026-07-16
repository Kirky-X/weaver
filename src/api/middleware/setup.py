# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Middleware setup — extracted from ``src/main.py``.

Reduces ``create_app()`` responsibility.

Configures CORS, pure ASGI middleware, performance monitoring, rate limiting,
HMAC signature verification, traffic anomaly detection, and audit logging.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.api_response import register_exception_handlers
from api.middleware.asgi import (
    HTTPLoggingMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from api.middleware.rate_limit import RateLimitMiddleware, TokenBucketRateLimiter
from api.middleware.request_context import RequestContextMiddleware
from core.observability import get_logger

if TYPE_CHECKING:
    from config.settings import Settings
    from container import Container

log = get_logger("main")


def setup_middleware(app: FastAPI, settings: Settings, container: Container | None) -> None:
    """Register all middleware on the FastAPI application.

    Args:
        app: The FastAPI application to configure.
        settings: Application settings.
        container: Optional container; created later by caller if None.

    """
    _configure_cors(app, settings)
    _configure_asgi_middleware(app)
    _configure_performance_middleware(app)
    register_exception_handlers(app)
    _configure_rate_limiting(app, container)
    _configure_hmac(app, settings)
    _configure_traffic_anomaly(app, settings, container)
    _configure_audit_logging(app, container)


def _configure_cors(app: FastAPI, settings: Settings) -> None:
    """Configure CORS with security-aware origin handling."""
    environment = settings.environment
    cors_origins_env = os.environ.get("CORS_ORIGINS", "")

    if environment == "production":
        if cors_origins_env:
            cors_origins = [
                origin.strip() for origin in cors_origins_env.split(",") if origin.strip()
            ]
            if len(cors_origins) > 1:
                log.warning(
                    "cors_multiple_origins_production",
                    message="Multiple CORS origins with credentials in production. "
                    "Only first origin will be used for security.",
                    origins_count=len(cors_origins),
                )
                cors_origins = cors_origins[:1]
            allow_credentials = True
        else:
            # No explicit origins in production - warn and disable CORS
            cors_origins = []
            allow_credentials = False
            log.warning(
                "cors_no_origins_production",
                message="CORS_ORIGINS not set in production. CORS will be disabled. "
                "Frontend requests will fail unless served from same origin.",
            )
    else:
        # Development: allow multiple origins with credentials
        cors_origins = [
            origin.strip()
            for origin in (
                cors_origins_env
                or "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000"
            ).split(",")
            if origin.strip()
        ]
        allow_credentials = True

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )


def _configure_asgi_middleware(app: FastAPI) -> None:
    """Add pure ASGI middleware.

    Note: Order matters - last added is first executed (innermost).
    """
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(HTTPLoggingMiddleware)  # HTTP request/response logging
    app.add_middleware(RequestContextMiddleware)  # Request ID for logging (innermost)


def _configure_performance_middleware(app: FastAPI) -> None:
    """Add performance monitoring middleware (BaseHTTPMiddleware)."""
    from api.middleware.performance import PerformanceMonitoringMiddleware

    app.add_middleware(PerformanceMonitoringMiddleware)


def _configure_rate_limiting(app: FastAPI, container: Container | None) -> None:
    """Register Redis-backed token bucket rate limiting middleware."""
    try:
        redis_client = container.cache_client() if container else None
    except RuntimeError:
        redis_client = None
    rate_limiter = TokenBucketRateLimiter(redis=redis_client)
    app.add_middleware(RateLimitMiddleware, rate_limiter=rate_limiter)


def _configure_hmac(app: FastAPI, settings: Settings) -> None:
    """Register HMAC signature middleware if enabled."""
    if not settings.api.hmac_signing_enabled:
        return

    from api.middleware.hmac_auth import HMACSignatureMiddleware

    hmac_secret = settings.api.hmac_secret or settings.api.get_api_key()
    if settings.api.hmac_secret is None:
        log.warning(
            "hmac_secret_not_configured",
            message="HMAC signing key falls back to API key. Set WEAVER_API__HMAC_SECRET for proper key separation.",
        )
    app.add_middleware(
        HMACSignatureMiddleware, secret_key=hmac_secret, api_key=settings.api.get_api_key()
    )


def _configure_traffic_anomaly(
    app: FastAPI, settings: Settings, container: Container | None
) -> None:
    """Register traffic anomaly detection middleware if enabled."""
    if not getattr(getattr(settings, "traffic_anomaly", None), "enabled", False):
        return

    from api.middleware.traffic_anomaly import (
        TrafficAnomalyConfig,
        TrafficAnomalyDetector,
        TrafficAnomalyMiddleware,
    )

    traffic_config = TrafficAnomalyConfig(
        enabled=settings.traffic_anomaly.enabled,
        default_key_rate_limit=getattr(settings.traffic_anomaly, "default_key_rate_limit", 200),
        ip_rate_limit=getattr(settings.traffic_anomaly, "ip_rate_limit", 200),
        burst_threshold=getattr(settings.traffic_anomaly, "burst_threshold", 10),
        ip_ban_duration_seconds=getattr(settings.traffic_anomaly, "ip_ban_duration_seconds", 900),
    )
    redis_client = container.cache_client() if container else None
    if redis_client:
        traffic_detector = TrafficAnomalyDetector(
            redis=redis_client,
            config=traffic_config,
        )
        app.add_middleware(TrafficAnomalyMiddleware, detector=traffic_detector)


def _configure_audit_logging(app: FastAPI, container: Container | None) -> None:
    """Register audit logging middleware (requires initialized container)."""
    from api.middleware.audit import AuditLogMiddleware
    from core.security import AuditLogService

    try:
        audit_service = AuditLogService(pool=container.relational_pool()) if container else None
    except RuntimeError:
        audit_service = None
    app.add_middleware(
        AuditLogMiddleware,
        audit_service=audit_service,
        audited_paths=["/api/v1/admin"],
        write_only_paths=["/api/v1/pipeline", "/api/v1/content", "/api/v1/graph"],
    )
