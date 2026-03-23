# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Weaver - Application Entry Point."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Fix: allow `from api` style imports to resolve correctly regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from api.endpoints import _deps as deps
from api.endpoints.admin import set_source_authority_repo
from api.endpoints.articles import set_postgres_pool as set_articles_postgres_pool
from api.endpoints.graph import set_neo4j_client
from api.endpoints.graph_metrics import set_neo4j_pool as set_graph_neo4j_pool
from api.endpoints.health import (
    health_check as check_health,
    set_neo4j_pool,
    set_postgres_pool as set_health_postgres_pool,
    set_redis_client,
)
from api.endpoints.pipeline import (
    set_postgres_pool as set_pipeline_postgres_pool,
    set_redis_client as set_pipeline_redis,
    set_source_scheduler,
)
from api.endpoints.sources import set_source_config_repo
from api.middleware.rate_limit import limiter
from api.router import api_router
from config.settings import Settings
from container import Container, set_container, set_settings
from core.observability.logging import configure_logging, get_logger
from core.observability.tracing import configure_tracing

log = get_logger("main")
configure_logging(debug=os.environ.get("DEBUG", "").lower() in ("true", "1", "yes"))

_scheduler = None


async def _setup_scheduler(container: Container) -> Any:
    """Setup APScheduler with compensation jobs.

    Args:
        container: The application container.

    Returns:
        The scheduler instance.
    """
    global _scheduler

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler as AsyncScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        log.warning("apscheduler_not_installed")
        return None

    # Import jobs
    from modules.scheduler.jobs import SchedulerJobs

    # Create jobs instance
    jobs = SchedulerJobs(
        postgres_pool=container.postgres_pool(),
        redis_client=container.redis_client(),
        neo4j_writer=container.neo4j_writer(),
        vector_repo=container.vector_repo(),
        article_repo=container.article_repo(),
        source_authority_repo=container.source_authority_repo(),
        pipeline=container.pipeline(),
    )

    # Create scheduler
    scheduler = AsyncScheduler()

    # Add jobs as per dev.md:
    # 1. retry_neo4j_writes: scan persist_status='pg_done' > 10min
    scheduler.add_job(
        jobs.retry_neo4j_writes,
        trigger=IntervalTrigger(minutes=10),
        id="retry_neo4j_writes",
        name="Retry failed Neo4j writes",
        max_instances=1,
        coalesce=True,
    )

    # 2. flush_retry_queue: requeue expired crawl retries
    scheduler.add_job(
        jobs.flush_retry_queue,
        trigger=IntervalTrigger(seconds=30),
        id="flush_retry_queue",
        name="Flush expired crawl retry queue",
        max_instances=1,
        coalesce=True,
    )

    # 3. update_source_auto_scores: auto-calculate source authority
    scheduler.add_job(
        jobs.update_source_auto_scores,
        trigger=CronTrigger(hour=3),
        id="update_source_auto_scores",
        name="Update source authority scores",
        max_instances=1,
    )

    # 4. archive_old_neo4j_nodes: cleanup old articles
    scheduler.add_job(
        jobs.archive_old_neo4j_nodes,
        trigger=CronTrigger(day_of_week=6, hour=2),
        id="archive_old_neo4j_nodes",
        name="Archive old Neo4j nodes",
        max_instances=1,
    )

    # 5. cleanup_orphan_entity_vectors: cleanup orphan vectors
    scheduler.add_job(
        jobs.cleanup_orphan_entity_vectors,
        trigger=CronTrigger(day_of_week=6, hour=3),
        id="cleanup_orphan_entity_vectors",
        name="Clean up orphan entity vectors",
        max_instances=1,
    )

    # 6. retry_pipeline_processing: retry failed/stuck pipeline processing
    scheduler.add_job(
        jobs.retry_pipeline_processing,
        trigger=IntervalTrigger(minutes=15),
        id="retry_pipeline_processing",
        name="Retry failed pipeline processing",
        max_instances=1,
        coalesce=True,
    )

    # 7. sync_neo4j_with_postgres: ensure data consistency
    scheduler.add_job(
        jobs.sync_neo4j_with_postgres,
        trigger=IntervalTrigger(hours=1),
        id="sync_neo4j_with_postgres",
        name="Sync Neo4j with PostgreSQL",
        max_instances=1,
        coalesce=True,
    )

    # 8. update_persist_status_metrics: update persist status gauge for alerting
    scheduler.add_job(
        jobs.update_persist_status_metrics,
        trigger=IntervalTrigger(minutes=5),
        id="update_persist_status_metrics",
        name="Update persist status Prometheus metrics",
        max_instances=1,
        coalesce=True,
    )

    # Start scheduler
    scheduler.start()
    _scheduler = scheduler

    log.info("scheduler_started")
    return scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """Application lifespan manager for startup and shutdown.

    Args:
        app: The FastAPI application.
    """
    global _scheduler

    # Startup
    container = app.state.container

    # Initialize OpenTelemetry tracing
    configure_tracing(
        service_name="weaver", endpoint=container.settings.observability.otlp_endpoint
    )
    log.debug("tracing_initialized", endpoint=container.settings.observability.otlp_endpoint)

    await container.startup()

    # Register services for API endpoints
    set_container(container)
    set_settings(container.settings)
    set_source_config_repo(container.source_config_repo())

    redis_client = container.redis_client()
    set_redis_client(redis_client)
    set_pipeline_redis(redis_client)
    log.debug("redis_client_set", client_id=id(redis_client))

    set_source_scheduler(container.source_scheduler())
    log.debug("source_scheduler_set")

    set_health_postgres_pool(container.postgres_pool())
    set_neo4j_pool(container.neo4j_pool())
    set_graph_neo4j_pool(container.neo4j_pool())
    set_neo4j_client(container.neo4j_pool())
    set_redis_client(redis_client)
    set_source_authority_repo(container.source_authority_repo())

    # Also set postgres pool for pipeline and articles modules
    set_pipeline_postgres_pool(container.postgres_pool())
    set_articles_postgres_pool(container.postgres_pool())

    # Register all pools/clients with the centralized Endpoints registry
    deps.Endpoints._postgres = container.postgres_pool()
    deps.Endpoints._neo4j = container.neo4j_pool()
    deps.Endpoints._redis = redis_client
    deps.Endpoints._llm = container.llm_client()
    deps.Endpoints._scheduler = container.source_scheduler()
    deps.Endpoints._vector_repo = container.vector_repo()
    deps.Endpoints._source_config_repo = container.source_config_repo()
    deps.Endpoints._source_authority_repo = container.source_authority_repo()
    deps.Endpoints._local_engine = container.local_search_engine()
    deps.Endpoints._global_engine = container.global_search_engine()
    log.debug("endpoints_registry_populated")

    # Setup APScheduler
    try:
        scheduler = await _setup_scheduler(container)
        app.state.scheduler = scheduler
    except Exception as exc:
        import traceback

        log.error("scheduler_setup_failed", error=str(exc), traceback=traceback.format_exc())

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

    # 4. Shutdown APScheduler
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown()
            log.info("scheduler_stopped")
        except Exception as exc:
            log.warning("scheduler_shutdown_failed", error=str(exc))

    # 5. Shutdown container (includes browser pool)
    await container.shutdown()

    log.info("graceful_shutdown_complete")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to limit request body size."""

    MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB

    async def dispatch(self, request: Request, call_next):
        if request.method in ["POST", "PUT", "PATCH"]:
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.MAX_REQUEST_SIZE:
                raise HTTPException(status_code=413, detail="Request body too large")
        return await call_next(request)


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

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)

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

    @app.get("/health")
    async def health_check_endpoint() -> dict:
        """Health check endpoint with dependency checks."""
        result = await check_health()
        if result["status"] != "healthy":
            raise HTTPException(status_code=503, detail=result)
        return result

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
    """Main entry point for the application."""
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
