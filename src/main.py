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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.endpoints import _deps as deps
from api.endpoints.graph import set_postgres_pool as set_graph_postgres_pool
from api.endpoints.health import health_check
from api.middleware.rate_limit import limiter
from api.router import api_router
from api.schemas.response import APIResponse, success_response
from config.settings import Settings
from container import Container, set_container, set_settings
from core.observability.logging import configure_logging, get_logger
from core.observability.tracing import configure_tracing, instrument_fastapi

log = get_logger("main")
configure_logging(debug=os.environ.get("DEBUG", "").lower() in ("true", "1", "yes"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """Application lifespan manager for startup and shutdown.

    Args:
        app: The FastAPI application.
    """
    # Startup
    container = app.state.container

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

    redis_client = container.redis_client()
    log.debug("redis_client_set", client_id=id(redis_client))

    # Set Neo4j client for graph module
    set_graph_postgres_pool(container.postgres_pool())

    # Register all pools/clients with the centralized Endpoints registry
    deps.Endpoints._postgres = container.postgres_pool()
    deps.Endpoints._neo4j = container.neo4j_pool()
    deps.Endpoints._redis = redis_client
    deps.Endpoints._llm = container.llm_client()
    deps.Endpoints._scheduler = container.source_scheduler()
    deps.Endpoints._vector_repo = container.vector_repo()
    deps.Endpoints._source_config_repo = container.source_config_repo()
    deps.Endpoints._source_authority_repo = container.source_authority_repo()
    deps.Endpoints._llm_failure_repo = container.llm_failure_repo()
    deps.Endpoints._llm_usage_repo = container.llm_usage_repo()
    deps.Endpoints._local_engine = container.local_search_engine()
    deps.Endpoints._global_engine = container.global_search_engine()
    deps.Endpoints._hybrid_engine = container.hybrid_search_engine()
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
            await asyncio.wait_for(container.pipeline().drain(), timeout=30.0)
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


class BusinessException(Exception):
    """Custom business exception for API errors."""

    def __init__(self, code: int, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status


def create_app(container: Container | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        container: Optional container. If not provided, creates a new one.

    Returns:
        Configured FastAPI application.
    """
    settings = container.settings if container else Settings()

    security_warnings = settings.validate_security()
    for warning in security_warnings:
        log.warning("security_check", warning=warning)

    app = FastAPI(
        title="Weaver API",
        description="Weaver - Intelligent news discovery and knowledge graph platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    cors_origins = os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000"
    ).split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )

    # Add pure ASGI middleware (avoid BaseHTTPMiddleware due to TestClient issues)
    # Note: Order matters - last added is first executed
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(HTTPLoggingMiddleware)  # HTTP request/response logging

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=exc.http_status, content={"code": exc.code, "message": exc.message}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.error("unhandled_exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=500, content={"code": 500, "message": "Internal server error"}
        )

    if container is None:
        container = Container().configure(settings)
    app.state.container = container

    app.include_router(api_router)

    @app.get("/health", response_model=APIResponse[dict])
    async def health_check_endpoint() -> APIResponse[dict]:
        """Health check endpoint with dependency checks."""
        result = await health_check()
        if result.status != "healthy":
            raise HTTPException(status_code=503, detail=result.model_dump())
        return success_response(result.model_dump())

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        """Prometheus metrics endpoint."""
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
