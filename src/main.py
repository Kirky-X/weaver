# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Weaver - Application Entry Point."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# Fix: allow `from api` style imports to resolve correctly regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI

from api.endpoints.deps_registry import Endpoints as deps  # noqa: N813
from api.endpoints.system import health_endpoint, metrics_endpoint
from api.middleware.setup import setup_middleware
from api.router import api_router
from api.schemas.response import APIResponse
from config.settings import Settings
from container import Container, set_container, set_settings
from core.nlp.spacy_manager import SpacyModelConfig, SpacyModelManager
from core.observability import configure_logging, get_logger
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
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    # Late-init audit service if middleware was registered without pool
    from api.middleware.audit import AuditLogMiddleware
    from core.security import AuditLogService

    for middleware in app.user_middleware:
        if isinstance(middleware.cls, type) and issubclass(middleware.cls, AuditLogMiddleware):
            if middleware.kwargs.get("audit_service") is None:
                middleware.kwargs["audit_service"] = AuditLogService(
                    pool=container.relational_pool()
                )
            break

    redis_client = container.cache_client()
    log.debug("cache_client_set", client_id=id(redis_client))

    # Initialize all endpoint dependencies via centralized registry
    deps.initialize(container)
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

    # Check HMAC secret separation in production
    if settings.api.hmac_signing_enabled and settings.api.hmac_secret is None:
        if settings.environment == "production":
            log.critical(
                "hmac_secret_not_configured_production",
                message="HMAC signing key falls back to API key in production. "
                "Set WEAVER_API__HMAC_SECRET for proper key separation.",
            )
        else:
            log.warning(
                "hmac_secret_not_configured",
                message="HMAC signing key falls back to API key. Set WEAVER_API__HMAC_SECRET for proper key separation.",
            )

    app = FastAPI(
        title="Weaver API",
        description="Weaver - Intelligent news discovery and knowledge graph platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    if container is None:
        container = Container().configure(settings)
    app.state.container = container

    # Register all middleware (CORS, ASGI, performance, rate limiting, HMAC,
    # traffic anomaly, audit logging) via extracted setup module.
    setup_middleware(app, settings, container)

    app.include_router(api_router)

    # Register root-level endpoints (health and metrics are not under /api/v1)
    app.get("/health", response_model=APIResponse[dict])(health_endpoint)
    app.get("/metrics")(metrics_endpoint)

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

        def _signal_handler(s: signal.Signals = sig) -> None:
            asyncio.create_task(graceful_shutdown(s))

        loop.add_signal_handler(sig, _signal_handler)

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
