# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Weaver - Application Entry Point."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Fix: allow `from api` style imports to resolve correctly regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.endpoints import deps_registry as deps
from api.endpoints.health import health_check
from api.middleware.api_response import register_exception_handlers
from api.middleware.auth import verify_admin_api_key, verify_api_key, verify_api_key_optional
from api.middleware.rate_limit import limiter
from api.middleware.request_context import RequestContextMiddleware
from api.router import api_router
from api.schemas.response import APIResponse, success_response
from config.settings import Settings
from container import Container, set_container, set_settings
from core.nlp.spacy_manager import SpacyModelConfig, SpacyModelManager
from core.observability import get_logger
from core.observability.logging import configure_logging
from core.observability.tracing import configure_tracing, instrument_fastapi

log = get_logger("main")
configure_logging(debug=os.environ.get("DEBUG", "").lower() in ("true", "1", "yes"))


def _ensure_spacy_models(settings: Settings) -> None:
    """Ensure spaCy models are available.

    Checks for missing models and installs them if configured.
    This runs before container initialization for early failure detection.

    Args:
        settings: Application settings containing spacy configuration.

    Raises:
        RuntimeError: If model installation fails in strict mode.
    """
    config = SpacyModelConfig(
        force_install=settings.spacy.force_install,
        strict_mode=settings.spacy.strict_mode,
        models=settings.spacy.models,
        local_paths=settings.spacy.local_paths,
    )
    manager = SpacyModelManager(config)
    manager.check_and_install()


@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """Application lifespan manager for startup and shutdown.

    Args:
        app: The FastAPI application.
    """
    # Startup
    container = app.state.container

    # Re-configure logging with settings (module-level call uses env defaults)
    configure_logging(
        debug=container.settings.environment == "development",
        log_file=container.settings.observability.log_file,
        log_rotation=container.settings.observability.log_rotation,
        log_retention=container.settings.observability.log_retention,
    )

    # Initialize OpenTelemetry tracing
    configure_tracing(
        service_name="weaver", endpoint=container.settings.observability.otlp_endpoint
    )
    log.debug("tracing_initialized", endpoint=container.settings.observability.otlp_endpoint)

    # Instrument FastAPI for OpenTelemetry
    instrument_fastapi(app)
    log.debug("fastapi_instrumented")

    await container.startup()

    # Register services for API endpoints
    set_container(container)
    set_settings(container.settings)

    redis_client = container.cache_client()
    log.debug("cache_client_set", client_id=id(redis_client))

    # Register all pools/clients with the centralized Endpoints registry
    # Use Protocol-compatible attribute names
    deps.Endpoints._relational_pool = container.relational_pool()
    deps.Endpoints._relational_pool_type = container.relational_pool_type
    deps.Endpoints._graph_pool = container.graph_pool()
    deps.Endpoints._graph_pool_type = container.graph_pool_type
    deps.Endpoints._cache = redis_client
    deps.Endpoints._llm = container.llm_client()
    deps.Endpoints._scheduler = container.source_scheduler()
    deps.Endpoints._vector_repo = container.vector_repo()
    deps.Endpoints._graph_repo = container.graph_repo()
    deps.Endpoints._source_config_repo = container.source_config_repo()
    deps.Endpoints._source_authority_repo = container.source_authority_repo()
    deps.Endpoints._llm_failure_repo = container.llm_failure_repo()
    deps.Endpoints._llm_usage_repo = container.llm_usage_repo()
    deps.Endpoints._local_engine = container.local_search_engine()
    deps.Endpoints._global_engine = container.global_search_engine()
    deps.Endpoints._hybrid_engine = container.hybrid_search_engine()
    deps.Endpoints._pipeline_service = container.pipeline_service()
    deps.Endpoints._task_registry = container.task_registry()
    log.debug("endpoints_registry_populated")

    log.info(
        "application_started", host=container.settings.api.host, port=container.settings.api.port
    )

    yield

    # Shutdown - graceful shutdown
    await _graceful_shutdown(app)

    log.info("application_stopped")


async def _graceful_shutdown(app: FastAPI) -> None:
    """Perform graceful shutdown.

    According to dev.md:
    1. Stop accepting new Pipeline tasks
    2. Wait for current nodes to complete (max 30s)
    3. Requeue processing status articles
    4. Shutdown browser pool

    Args:
        app: The FastAPI application.
    """
    log.info("graceful_shutdown_start")

    container = app.state.container

    # 1. Stop accepting new Pipeline tasks
    try:
        if hasattr(container, "pipeline"):
            await container.pipeline().stop_accepting()
            log.info("pipeline_stopped_accepting")
    except Exception as exc:
        log.warning("pipeline_stop_failed", error=str(exc))

    # 2. Wait for current tasks to complete (with timeout)
    try:
        if hasattr(container, "pipeline"):
            await asyncio.wait_for(
                container.pipeline().drain(),
                timeout=container.settings.api.shutdown_timeout,
            )
            log.info("pipeline_drained")
    except TimeoutError:
        log.warning("pipeline_drain_timeout")
    except Exception as exc:
        log.warning("pipeline_drain_failed", error=str(exc))

    # 3. Requeue processing status articles
    try:
        if hasattr(container, "article_repo"):
            await container.article_repo().requeue_processing()
            log.info("processing_articles_requeued")
    except Exception as exc:
        log.warning("requeue_failed", error=str(exc))

    # 4. Shutdown container (includes browser pool)
    await container.shutdown()

    log.info("graceful_shutdown_complete")


# ── Pure ASGI Middleware ───────────────────────────────────────────────────
# Using pure ASGI middleware to avoid BaseHTTPMiddleware issues with TestClient.
# See: https://github.com/encode/starlette/issues/1931


class HTTPLoggingMiddleware:
    """Pure ASGI middleware to log all HTTP requests and responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode("utf-8")
        headers = dict(scope.get("headers", []))

        # Extract client info
        client = scope.get("client", ("unknown", 0))
        client_host = client[0] if client else "unknown"

        # Log request
        api_key = headers.get(b"x-api-key", b"").decode("utf-8")
        if api_key:
            api_key_display = api_key[:8] + "..." if len(api_key) > 8 else api_key
        else:
            api_key_display = "none"

        log.info(
            "http_request",
            method=method,
            path=path,
            query=query if query else None,
            client=client_host,
            api_key=api_key_display,
        )

        # Capture response
        response_status = None
        response_headers = {}
        response_body_parts = []

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                nonlocal response_headers, response_status
                response_status = message.get("status", 0)
                response_headers = dict(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    response_body_parts.append(body)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Log response
        response_body = b"".join(response_body_parts)
        content_type = response_headers.get(b"content-type", b"").decode("utf-8")

        # Truncate body for logging (max 500 chars for JSON, 200 for others)
        if "application/json" in content_type:
            max_body_len = 500
        else:
            max_body_len = 200

        body_preview = response_body.decode("utf-8", errors="replace")[:max_body_len]
        if len(response_body) > max_body_len:
            body_preview += "..."

        log.info(
            "http_response",
            status=response_status,
            path=path,
            method=method,
            content_type=content_type,
            body_preview=body_preview,
            body_size=len(response_body),
        )


class SecurityHeadersMiddleware:
    """Pure ASGI middleware to add security headers to all responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-content-type-options"] = b"nosniff"
                headers[b"x-frame-options"] = b"DENY"
                headers[b"x-xss-protection"] = b"1; mode=block"
                headers[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestSizeLimitMiddleware:
    """Pure ASGI middleware to limit request body size."""

    MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method in ("POST", "PUT", "PATCH"):
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length")
            if content_length and int(content_length) > self.MAX_REQUEST_SIZE:
                # Send 413 response
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"detail":"Request body too large"}',
                    }
                )
                return

        await self.app(scope, receive, send)


def create_app(container: Container | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        container: Optional container. If not provided, creates a new one.

    Returns:
        Configured FastAPI application.
    """
    settings = container.settings if container else Settings()

    # Ensure spaCy models are available (early check before container init)
    _ensure_spacy_models(settings)

    security_warnings = settings.validate_security()
    for warning in security_warnings:
        log.warning("security_check", warning=warning)

    app = FastAPI(
        title="Weaver API",
        description="Weaver - Intelligent news discovery and knowledge graph platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration - security fix for credentials + multiple origins
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

    # Add pure ASGI middleware (avoid BaseHTTPMiddleware due to TestClient issues)
    # Note: Order matters - last added is first executed (innermost)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(HTTPLoggingMiddleware)  # HTTP request/response logging
    app.add_middleware(RequestContextMiddleware)  # Request ID for logging (innermost)

    # Performance monitoring middleware (BaseHTTPMiddleware)
    from api.middleware.performance import PerformanceMonitoringMiddleware

    app.add_middleware(PerformanceMonitoringMiddleware)

    # Register centralized exception handlers
    register_exception_handlers(app)

    # Keep RateLimitExceeded handler (from slowapi)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    if container is None:
        container = Container().configure(settings)
    app.state.container = container

    app.include_router(api_router)

    # Register Prometheus metrics endpoint
    from api.middleware.prometheus_metrics import metrics_endpoint

    app.add_route("/metrics", metrics_endpoint, methods=["GET"])

    @app.get("/health", response_model=APIResponse[dict])
    async def health_check_endpoint() -> APIResponse[dict]:
        """Health check endpoint for load balancers.

        Returns health status wrapped in APIResponse format.
        Detailed health info requires authentication via /api/v1/status.
        """
        result = await health_check()
        return success_response({"status": result.status, "checks": result.checks})

    @app.get("/api/v1/status", response_model=APIResponse[dict])
    async def system_status(
        _: str = Depends(verify_api_key),
    ) -> APIResponse[dict]:
        """System status endpoint (requires authentication).

        Returns overall system status including database types and processing stats.
        """
        import tomllib

        version = "unknown"
        try:
            with open("pyproject.toml", "rb") as f:
                pyproject = tomllib.load(f)
            version = pyproject.get("project", {}).get("version", "unknown")
        except Exception:
            log.warning("Failed to read version from pyproject.toml", exc_info=True)
            pass

        from api.endpoints.deps_registry import Endpoints

        relational_type = Endpoints.get_relational_type()
        graph_type = Endpoints.get_graph_type()
        cache_type = Endpoints.get_cache_type()

        return success_response(
            {
                "status": "running",
                "version": version,
                "database": {
                    "relational": relational_type,
                    "graph": graph_type,
                    "cache": cache_type,
                },
            }
        )

    @app.get("/api/v1/config", response_model=APIResponse[dict])
    async def system_config(
        _: str = Depends(verify_admin_api_key),
    ) -> APIResponse[dict]:
        """System configuration endpoint (requires admin authentication).

        Returns current configuration including available features.
        This endpoint contains sensitive information and requires admin API key.
        """
        from api.endpoints.deps_registry import Endpoints

        return success_response(
            {
                "relational_pool_type": Endpoints.get_relational_type(),
                "graph_pool_type": Endpoints.get_graph_type(),
                "llm_enabled": Endpoints._llm is not None,
                "search_enabled": Endpoints._local_engine is not None,
                "graph_available": Endpoints._graph_pool is not None,
            }
        )

    @app.get("/metrics")
    async def metrics_endpoint(
        _: str | None = Depends(verify_api_key_optional),
    ) -> PlainTextResponse:
        """Prometheus metrics endpoint (optional authentication).

        Authentication required if WEAVER__API__REQUIRE_AUTH_FOR_METRICS=true.
        """
        return PlainTextResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app


app = create_app()


async def main() -> None:
    """Provide main entry point for the application."""
    import uvicorn

    settings = Settings()

    # Ensure spaCy models are available (before container initialization)
    _ensure_spacy_models(settings)

    container = Container().configure(settings)
    app = create_app(container)

    # Setup graceful shutdown
    loop = asyncio.get_running_loop()

    async def graceful_shutdown(sig: signal.Signals) -> None:
        """Handle graceful shutdown on SIGTERM/SIGINT."""
        log.info("shutdown_signal_received", signal=str(sig))
        # The lifespan context manager will handle cleanup
        # Just stop the server
        server.force_exit = True
        loop.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(graceful_shutdown(s)),
        )

    # Run server
    config = uvicorn.Config(
        app,
        host=settings.api.host,
        port=settings.api.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
