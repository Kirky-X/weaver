"""News Discovery Backend - Application Entry Point."""

from __future__ import annotations

import asyncio
import signal
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import Settings
from container import Container, set_container, set_settings
from api.router import api_router
from api.endpoints.sources import set_source_registry
from api.endpoints.pipeline import set_redis_client, set_source_scheduler
from api.endpoints.articles import set_postgres_pool
from api.endpoints.graph import set_neo4j_client
from api.endpoints.admin import set_source_authority_repo
from core.observability.logging import get_logger

log = get_logger("main")

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
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger
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
    await container.startup()

    # Register services for API endpoints
    set_container(container)
    set_settings(container.settings)
    set_source_registry(container.source_registry())

    redis_client = container.redis_client()
    set_redis_client(redis_client)
    print(f"[DEBUG] set_redis_client called with id={id(redis_client)}")

    # Set source scheduler for API triggers
    set_source_scheduler(container.source_scheduler())
    print(f"[DEBUG] set_source_scheduler called")

    set_postgres_pool(container.postgres_pool())
    set_neo4j_client(container.neo4j_pool())
    set_source_authority_repo(container.source_authority_repo())

    # Setup APScheduler
    try:
        scheduler = await _setup_scheduler(container)
        app.state.scheduler = scheduler
    except Exception as exc:
        log.warning("scheduler_setup_failed", error=str(exc))

    log.info("application_started", host=container.settings.api.host, port=container.settings.api.port)

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
                timeout=30.0
            )
            log.info("pipeline_drained")
    except asyncio.TimeoutError:
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
            await _scheduler.shutdown()
            log.info("scheduler_stopped")
        except Exception as exc:
            log.warning("scheduler_shutdown_failed", error=str(exc))

    # 5. Shutdown container (includes browser pool)
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

    app = FastAPI(
        title="News Discovery API",
        description="Backend API for news discovery, crawling, and analysis",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize container
    if container is None:
        container = Container().configure(settings)
    app.state.container = container

    # Include API router
    app.include_router(api_router)

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict:
        """Health check endpoint."""
        return {"status": "healthy"}

    return app


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
