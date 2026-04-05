# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Dependency injection container for the weaver application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import Settings
from core.cache import RedisClient
from core.db import Neo4jPool, PostgresPool
from core.event import EventBus, LLMFailureEvent, LLMUsageEvent
from core.llm.client import LLMClient
from core.observability import get_logger
from core.prompt import PromptLoader
from modules.analytics.llm_usage.buffer import LLMUsageBuffer
from modules.analytics.llm_usage.repo import LLMUsageRepo
from modules.ingestion import (
    Crawler,
    Deduplicator,
    SmartFetcher,
    SourceConfigRepo,
    SourceRegistry,
    SourceScheduler,
)
from modules.knowledge import EntityResolver, Neo4jWriter
from modules.knowledge.community.incremental_updater import IncrementalCommunityUpdater
from modules.knowledge.graph.name_normalizer import name_normalizer
from modules.knowledge.graph.resolution_rules import resolution_rules
from modules.knowledge.search.engines.global_search import GlobalSearchEngine
from modules.knowledge.search.engines.hybrid_search import HybridSearchConfig, HybridSearchEngine
from modules.knowledge.search.engines.local_search import LocalSearchEngine
from modules.processing.pipeline.graph import Pipeline
from modules.storage.neo4j import Neo4jArticleRepo, Neo4jEntityRepo
from modules.storage.postgres import ArticleRepo, PendingSyncRepo, SourceAuthorityRepo, VectorRepo

log = get_logger("container")


async def _handle_llm_failure_async(event: LLMFailureEvent, repo: Any) -> None:
    """Async handler for LLMFailureEvent — runs in the container's async context."""
    try:
        await repo.record(event)
    except Exception as exc:
        log.error(
            "llm_failure_handler_error",
            call_point=event.call_point,
            provider=event.provider,
            error=str(exc),
        )


async def _handle_llm_usage_metrics(event: LLMUsageEvent) -> None:
    """Async handler for LLMUsageEvent — updates Prometheus token metrics."""
    try:
        from core.observability.metrics import metrics

        labels = {
            "provider": event.provider,
            "model": event.model,
            "call_point": event.call_point,
        }
        metrics.llm_token_input_total.labels(**labels).inc(event.tokens.input_tokens)
        metrics.llm_token_output_total.labels(**labels).inc(event.tokens.output_tokens)
        metrics.llm_token_total.labels(**labels).inc(event.tokens.total_tokens)
    except Exception as exc:
        log.error(
            "llm_usage_metrics_handler_error",
            label=event.label,
            call_point=event.call_point,
            error=str(exc),
        )


class Container:
    """Dependency injection container for the application.

    Manages lifecycle of all core services and provides them to
    the API layer and background workers.
    """

    def __init__(self) -> None:
        self._settings: Settings | None = None
        self._postgres_pool: PostgresPool | None = None
        self._neo4j_pool: Neo4jPool | None = None
        self._redis_client: RedisClient | None = None
        self._llm_client: LLMClient | None = None
        self._prompt_loader: PromptLoader | None = None
        self._source_registry: SourceRegistry | None = None
        self._source_config_repo: SourceConfigRepo | None = None
        self._source_scheduler: SourceScheduler | None = None
        self._article_repo: ArticleRepo | None = None
        self._vector_repo: VectorRepo | None = None
        self._source_authority_repo: SourceAuthorityRepo | None = None
        self._neo4j_entity_repo: Neo4jEntityRepo | None = None
        self._neo4j_article_repo: Neo4jArticleRepo | None = None
        self._neo4j_writer: Neo4jWriter | None = None
        self._entity_resolver: EntityResolver | None = None
        self._smart_fetcher: SmartFetcher | None = None
        self._crawl4ai_fetcher: Any = None  # Crawl4AIFetcher
        self._crawler: Crawler | None = None
        self._pipeline: Pipeline | None = None
        self._deduplicator: Deduplicator | None = None
        self._event_bus: EventBus | None = None
        self._llm_failure_repo: Any = None
        self._llm_usage_buffer: LLMUsageBuffer | None = None
        self._pending_sync_repo: PendingSyncRepo | None = None
        self._scheduler_jobs: Any = None
        self._scheduler: Any = None  # AsyncIOScheduler instance
        self._community_updater: IncrementalCommunityUpdater | None = None
        self._local_search_engine: LocalSearchEngine | None = None
        self._global_search_engine: GlobalSearchEngine | None = None
        self._hybrid_engine: HybridSearchEngine | None = None
        self._shutdown: bool = False  # Idempotency protection

    def configure(self, settings: Settings) -> Container:
        """Configure the container with settings.

        Args:
            settings: Application settings.

        Returns:
            Self for chaining.
        """
        self._settings = settings
        return self

    @property
    def settings(self) -> Settings:
        """Get settings."""
        if self._settings is None:
            raise RuntimeError("Container not configured. Call configure() first.")
        return self._settings

    # ── Database Pools ──────────────────────────────────────────

    async def init_postgres(self) -> PostgresPool:
        """Initialize PostgreSQL connection pool."""
        if self._postgres_pool is None:
            pg_settings = self._settings.postgres
            self._postgres_pool = PostgresPool(
                dsn=pg_settings.dsn,
                pool_size=pg_settings.pool_size,
                max_overflow=pg_settings.max_overflow,
                pool_timeout=pg_settings.pool_timeout,
            )
            await self._postgres_pool.startup()
            log.info("postgres_initialized")
        return self._postgres_pool

    def postgres_pool(self) -> PostgresPool:
        """Get PostgreSQL pool."""
        if self._postgres_pool is None:
            raise RuntimeError("PostgreSQL pool not initialized. Call init_postgres() first.")
        return self._postgres_pool

    async def init_neo4j(self) -> Neo4jPool:
        """Initialize Neo4j connection pool."""
        if self._neo4j_pool is None:
            log.info("init_neo4j_start", uri=self._settings.neo4j.uri, password="***")
            self._neo4j_pool = Neo4jPool(
                self._settings.neo4j.uri,
                (self._settings.neo4j.user, self._settings.neo4j.password),
            )
            await self._neo4j_pool.startup()
            log.info("neo4j_initialized")
        return self._neo4j_pool

    def neo4j_pool(self) -> Neo4jPool | None:
        """Get Neo4j pool (or None if unavailable)."""
        return self._neo4j_pool

    async def init_redis(self) -> RedisClient:
        """Initialize Redis client."""
        if self._redis_client is None:
            self._redis_client = RedisClient(self._settings.redis.url)
            await self._redis_client.startup()
            log.info("redis_initialized")
        return self._redis_client

    def redis_client(self) -> RedisClient:
        """Get Redis client."""
        if self._redis_client is None:
            raise RuntimeError("Redis client not initialized. Call init_redis() first.")
        return self._redis_client

    # ── LLM & Prompt ─────────────────────────────────────────────

    async def init_llm(self) -> LLMClient:
        """Initialize LLM client."""
        if self._llm_client is None:
            # Load LLM config from llm.toml
            project_root = Path(__file__).parent.parent
            config_path = project_root / "config" / "llm.toml"
            self._llm_client = await LLMClient.create_from_config(
                config_path=str(config_path),
                prompt_loader=self.prompt_loader(),
                redis_client=self._redis_client,  # Pass RedisClient wrapper, it will be unwrapped in rate_limiter
            )
            log.info("llm_client_initialized_from_config")

        return self._llm_client

    def llm_client(self) -> LLMClient:
        """Get LLM client."""
        if self._llm_client is None:
            raise RuntimeError("LLM client not initialized. Call init_llm() first.")
        return self._llm_client

    def prompt_loader(self) -> PromptLoader:
        """Get prompt loader."""
        if self._prompt_loader is None:
            self._prompt_loader = PromptLoader(self._settings.prompt.dir)
        return self._prompt_loader

    # ── Source Management ─────────────────────────────────────────

    def source_registry(self) -> SourceRegistry:
        """Get source registry."""
        if self._source_registry is None:
            if self._smart_fetcher is None:
                raise RuntimeError(
                    "Smart fetcher not initialized. Call init_smart_fetcher() first."
                )
            self._source_registry = SourceRegistry(self._smart_fetcher)
        return self._source_registry

    def source_config_repo(self) -> SourceConfigRepo:
        """Get source config repository (database-backed)."""
        if self._source_config_repo is None:
            if self._postgres_pool is None:
                raise RuntimeError("PostgreSQL pool not initialized. Call init_postgres() first.")
            self._source_config_repo = SourceConfigRepo(self._postgres_pool)
        return self._source_config_repo

    async def init_source_scheduler(
        self,
        on_items_discovered: Any = None,
    ) -> SourceScheduler:
        """Initialize source scheduler."""
        if self._source_scheduler is None:
            # Default callback - can be overridden
            async def default_callback(items: Any, source: Any) -> None:
                log.info("items_discovered", count=len(items), source=source.id)

            registry = self.source_registry()
            # Bridge DB sources into the in-memory registry so the scheduler
            # discovers and crawls all DB-persisted sources on startup.
            db_sources = await self.source_config_repo().list_sources(enabled_only=True)
            for cfg in db_sources:
                registry.add_source(cfg)
            self._source_scheduler = SourceScheduler(
                registry=registry,
                on_items_discovered=on_items_discovered or default_callback,
            )
            self._source_scheduler.start()
            log.info("source_scheduler_initialized")
        return self._source_scheduler

    def source_scheduler(self) -> SourceScheduler:
        """Get source scheduler."""
        if self._source_scheduler is None:
            raise RuntimeError(
                "Source scheduler not initialized. Call init_source_scheduler() first."
            )
        return self._source_scheduler

    # ── Repositories ──────────────────────────────────────────────

    def article_repo(self) -> ArticleRepo:
        """Get article repository."""
        if self._article_repo is None:
            self._article_repo = ArticleRepo(self._postgres_pool)
        return self._article_repo

    def source_authority_repo(self) -> SourceAuthorityRepo:
        """Get source authority repository."""
        if self._source_authority_repo is None:
            self._source_authority_repo = SourceAuthorityRepo(self._postgres_pool)
        return self._source_authority_repo

    def pending_sync_repo(self) -> PendingSyncRepo:
        """Get pending sync repository."""
        if self._pending_sync_repo is None:
            self._pending_sync_repo = PendingSyncRepo(self._postgres_pool)
        return self._pending_sync_repo

    def llm_failure_repo(self) -> Any:
        """Get LLM failure repository."""
        if self._llm_failure_repo is None:
            from modules.analytics.llm_failure.repo import LLMFailureRepo

            self._llm_failure_repo = LLMFailureRepo(self._postgres_pool)
        return self._llm_failure_repo

    def llm_usage_buffer(self) -> LLMUsageBuffer | None:
        """Get LLM usage buffer (or None if not initialized)."""
        return self._llm_usage_buffer

    def llm_usage_repo(self) -> LLMUsageRepo:
        """Get LLM usage repository."""
        if self._postgres_pool is None:
            raise RuntimeError("PostgreSQL pool not initialized. Call init_postgres() first.")
        return LLMUsageRepo(self._postgres_pool)

    def scheduler_jobs(self) -> Any:
        """Get scheduler jobs instance."""
        if self._scheduler_jobs is None:
            from modules.scheduler.jobs import SchedulerJobs

            self._scheduler_jobs = SchedulerJobs(
                postgres_pool=self._postgres_pool,
                redis_client=self._redis_client,
                neo4j_writer=self._neo4j_writer,
                vector_repo=self._vector_repo,
                article_repo=self._article_repo,
                source_authority_repo=self._source_authority_repo,
                pending_sync_repo=self._pending_sync_repo,
                pipeline=self._pipeline,
                settings=self._settings.scheduler,
                llm_failure_repo=self._llm_failure_repo,
            )
        return self._scheduler_jobs

    def _setup_scheduler(self) -> None:
        """Register all APScheduler jobs (single entry point)."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        settings = self._settings.scheduler
        if not settings.enabled:
            log.info("scheduler_disabled")
            return

        scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": settings.misfire_grace_time_seconds,
                "coalesce": True,
                "max_instances": 1,
            },
        )
        self._scheduler = scheduler

        jobs = self.scheduler_jobs()

        # ── Data Sync ──
        scheduler.add_job(
            jobs.sync_pending_to_neo4j,
            IntervalTrigger(minutes=settings.sync_pending_to_neo4j_interval_minutes),
            id="sync_pending_to_neo4j",
            name="Sync pending to Neo4j",
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            jobs.retry_neo4j_writes,
            IntervalTrigger(minutes=settings.retry_neo4j_writes_interval_minutes),
            id="retry_neo4j_writes",
            name="Retry failed Neo4j writes",
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            jobs.sync_neo4j_with_postgres,
            IntervalTrigger(hours=settings.sync_neo4j_with_postgres_interval_hours),
            id="sync_neo4j_with_postgres",
            name="Sync Neo4j with PostgreSQL",
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            jobs.consistency_check,
            CronTrigger(
                hour=settings.consistency_check_cron_hour,
                minute=settings.consistency_check_cron_minute,
            ),
            id="consistency_check",
            name="Consistency check",
            max_instances=1,
        )

        # ── Cleanup ──
        scheduler.add_job(
            jobs.cleanup_old_synced,
            CronTrigger(
                hour=settings.cleanup_old_synced_cron_hour,
                minute=settings.cleanup_old_synced_cron_minute,
            ),
            id="cleanup_old_synced",
            name="Cleanup old synced records",
            max_instances=1,
        )
        scheduler.add_job(
            jobs.llm_failure_cleanup,
            IntervalTrigger(hours=settings.llm_failure_cleanup_interval_hours),
            id="llm_failure_cleanup",
            name="LLM failure record cleanup",
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            jobs.llm_usage_raw_cleanup,
            IntervalTrigger(hours=settings.llm_usage_raw_cleanup_interval_hours),
            id="llm_usage_raw_cleanup",
            name="LLM usage raw record cleanup",
            max_instances=1,
            coalesce=True,
        )

        # ── Archive (weekly, conditional on Neo4j) ──
        if self._neo4j_writer is not None:
            scheduler.add_job(
                jobs.archive_old_neo4j_nodes,
                CronTrigger(
                    day_of_week=settings.archive_old_neo4j_nodes_cron_day_of_week,
                    hour=settings.archive_old_neo4j_nodes_cron_hour,
                ),
                id="archive_old_neo4j_nodes",
                name="Archive old Neo4j nodes",
                max_instances=1,
            )
            scheduler.add_job(
                jobs.cleanup_orphan_entity_vectors,
                CronTrigger(
                    day_of_week=settings.cleanup_orphan_vectors_cron_day_of_week,
                    hour=settings.cleanup_orphan_vectors_cron_hour,
                ),
                id="cleanup_orphan_entity_vectors",
                name="Cleanup orphan entity vectors",
                max_instances=1,
            )

        # ── Pipeline Retry ──
        scheduler.add_job(
            jobs.retry_pipeline_processing,
            IntervalTrigger(minutes=settings.pipeline_retry_interval_minutes),
            id="retry_pipeline_processing",
            name="Retry failed pipeline processing",
            max_instances=1,
            coalesce=True,
        )

        # ── Crawl Retry ──
        scheduler.add_job(
            jobs.flush_retry_queue,
            IntervalTrigger(seconds=settings.retry_flush_interval_seconds),
            id="flush_retry_queue",
            name="Flush expired crawl retry queue",
            max_instances=1,
            coalesce=True,
        )

        # ── LLM Usage Aggregation ──
        scheduler.add_job(
            jobs.aggregate_llm_usage,
            IntervalTrigger(minutes=settings.llm_usage_aggregate_interval_minutes),
            id="llm_usage_aggregate",
            name="LLM usage aggregation (Redis to PG)",
            max_instances=1,
            coalesce=True,
        )

        # ── Source Scoring ──
        scheduler.add_job(
            jobs.update_source_auto_scores,
            CronTrigger(hour=settings.source_auto_score_cron_hour),
            id="update_source_auto_scores",
            name="Update source authority scores",
            max_instances=1,
        )

        # ── Community Detection ──
        community_updater = self.community_updater()
        if community_updater is not None:
            scheduler.add_job(
                community_updater.check_and_run,
                IntervalTrigger(minutes=settings.community_check_interval_minutes),
                id="community_auto_check",
                name="Community auto detection check",
                max_instances=1,
                coalesce=True,
            )

        # ── Metrics ──
        scheduler.add_job(
            jobs.update_persist_status_metrics,
            IntervalTrigger(minutes=settings.persist_status_metrics_interval_minutes),
            id="update_persist_status_metrics",
            name="Update persist status Prometheus metrics",
            max_instances=1,
            coalesce=True,
        )

        # ── Startup: run sync once immediately ──
        scheduler.add_job(
            jobs.sync_pending_to_neo4j,
            DateTrigger(),
            id="startup_sync_pending_to_neo4j",
            replace_existing=True,
        )

        scheduler.start()
        log.info("scheduler_started", jobs=len(scheduler.get_jobs()))

    # ── Neo4j Repositories ─────────────────────────────────────────

    def neo4j_entity_repo(self) -> Neo4jEntityRepo | None:
        """Get Neo4j entity repository (or None if unavailable)."""
        if self._neo4j_pool is None:
            return None
        if self._neo4j_entity_repo is None:
            self._neo4j_entity_repo = Neo4jEntityRepo(self._neo4j_pool)
        return self._neo4j_entity_repo

    def neo4j_article_repo(self) -> Neo4jArticleRepo | None:
        """Get Neo4j article repository (or None if unavailable)."""
        if self._neo4j_pool is None:
            return None
        if self._neo4j_article_repo is None:
            self._neo4j_article_repo = Neo4jArticleRepo(self._neo4j_pool)
        return self._neo4j_article_repo

    def neo4j_writer(self) -> Neo4jWriter | None:
        """Get Neo4j writer (or None if unavailable)."""
        if self._neo4j_pool is None:
            return None
        if self._neo4j_writer is None:
            self._neo4j_writer = Neo4jWriter(self._neo4j_pool)
        return self._neo4j_writer

    def entity_resolver(self) -> EntityResolver:
        """Get entity resolver."""
        if self._entity_resolver is None:
            self._entity_resolver = EntityResolver(
                entity_repo=self.neo4j_entity_repo(),
                vector_repo=self.vector_repo(),
                llm=self._llm_client,
                resolution_rules=resolution_rules,
                name_normalizer=name_normalizer,
            )
        return self._entity_resolver

    def community_updater(self) -> IncrementalCommunityUpdater | None:
        """Get community updater (or None if Neo4j unavailable)."""
        if self._neo4j_pool is None:
            return None
        if self._community_updater is None:
            self._community_updater = IncrementalCommunityUpdater(pool=self._neo4j_pool)
        return self._community_updater

    # ── Vector Repository ─────────────────────────────────────────

    def vector_repo(self) -> VectorRepo:
        """Get vector repository."""
        if self._vector_repo is None:
            self._vector_repo = VectorRepo(self._postgres_pool)
        return self._vector_repo

    # ── Search Engines ───────────────────────────────────────────────

    def init_search_engines(self) -> tuple[LocalSearchEngine, GlobalSearchEngine] | None:
        """Initialize search engines (requires neo4j pool to be available)."""
        if self._neo4j_pool is None or self._llm_client is None:
            return None
        if self._local_search_engine is None:
            self._local_search_engine = LocalSearchEngine(
                neo4j_pool=self._neo4j_pool,
                llm=self._llm_client,
            )
        if self._global_search_engine is None:
            self._global_search_engine = GlobalSearchEngine(
                neo4j_pool=self._neo4j_pool,
                llm=self._llm_client,
            )
        return (self._local_search_engine, self._global_search_engine)

    def local_search_engine(self) -> LocalSearchEngine | None:
        """Get local search engine (or None if unavailable)."""
        if self._local_search_engine is None and self._neo4j_pool is not None:
            self.init_search_engines()
        return self._local_search_engine

    def global_search_engine(self) -> GlobalSearchEngine | None:
        """Get global search engine (or None if unavailable)."""
        if self._global_search_engine is None and self._neo4j_pool is not None:
            self.init_search_engines()
        return self._global_search_engine

    def hybrid_search_engine(self) -> HybridSearchEngine | None:
        """Get hybrid search engine (or None if unavailable)."""
        if self._hybrid_engine is None and self._vector_repo is not None:
            from modules.knowledge.search.retrievers.bm25_retriever import BM25Retriever

            bm25_retriever = BM25Retriever(self._postgres_pool)
            self._hybrid_engine = HybridSearchEngine(
                vector_repo=self._vector_repo,
                bm25_retriever=bm25_retriever,
                config=HybridSearchConfig(),
            )
        return self._hybrid_engine

    # ── Fetcher & Crawler ────────────────────────────────────────

    async def init_crawl4ai_fetcher(self) -> Any:
        """Initialize Crawl4AIFetcher for JS-rendered pages."""
        from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher

        if self._crawl4ai_fetcher is None:
            settings = self._settings.fetcher
            self._crawl4ai_fetcher = Crawl4AIFetcher(
                headless=settings.crawl4ai_headless,
                stealth_enabled=settings.crawl4ai_stealth_enabled,
                user_agent=settings.crawl4ai_user_agent,
                timeout=settings.crawl4ai_timeout,
            )
            log.info(
                "crawl4ai_fetcher_initialized",
                headless=settings.crawl4ai_headless,
                stealth=settings.crawl4ai_stealth_enabled,
            )
        return self._crawl4ai_fetcher

    async def init_smart_fetcher(self) -> SmartFetcher:
        """Initialize smart fetcher."""
        if self._smart_fetcher is None:
            from modules.ingestion.fetching import HostRateLimiter, HttpxFetcher
            from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher

            settings = self._settings.fetcher

            rate_limiter = None
            if settings.rate_limit_enabled:
                rate_limiter = HostRateLimiter(
                    delay_min=settings.rate_limit_delay_min,
                    delay_max=settings.rate_limit_delay_max,
                )
                log.info(
                    "rate_limiter_initialized",
                    delay_min=settings.rate_limit_delay_min,
                    delay_max=settings.rate_limit_delay_max,
                )

            httpx_fetcher = HttpxFetcher(
                timeout=settings.httpx_timeout,
                user_agent=settings.user_agent,
            )
            crawl4ai_fetcher = Crawl4AIFetcher(
                headless=settings.crawl4ai_headless,
                stealth_enabled=settings.crawl4ai_stealth_enabled,
                user_agent=settings.crawl4ai_user_agent,
                timeout=settings.crawl4ai_timeout,
            )
            self._smart_fetcher = SmartFetcher(
                httpx_fetcher=httpx_fetcher,
                crawl4ai_fetcher=crawl4ai_fetcher,
                rate_limiter=rate_limiter,
                circuit_breaker_enabled=settings.circuit_breaker_enabled,
                circuit_breaker_threshold=settings.circuit_breaker_threshold,
                circuit_breaker_timeout=settings.circuit_breaker_timeout,
            )
            log.info(
                "smart_fetcher_initialized",
                circuit_breaker_enabled=settings.circuit_breaker_enabled,
            )
        return self._smart_fetcher

    def smart_fetcher(self) -> SmartFetcher:
        """Get smart fetcher."""
        if self._smart_fetcher is None:
            raise RuntimeError("Smart fetcher not initialized. Call init_smart_fetcher() first.")
        return self._smart_fetcher

    def crawler(self) -> Crawler:
        """Get crawler."""
        if self._crawler is None:
            self._crawler = Crawler(
                smart_fetcher=self._smart_fetcher,
                default_per_host=self._settings.fetcher.default_per_host_concurrency,
            )
        return self._crawler

    def deduplicator(self) -> Deduplicator:
        """Get deduplicator."""
        if self._deduplicator is None:
            self._deduplicator = Deduplicator(
                redis=self._redis_client,
                article_repo=self._article_repo,
            )
        return self._deduplicator

    # ── Pipeline ─────────────────────────────────────────────────

    async def init_pipeline(self) -> Pipeline:
        """Initialize the processing pipeline."""
        if self._pipeline is None:
            from core.llm.token_budget import TokenBudgetManager
            from modules.processing.nlp.spacy_extractor import SpacyExtractor

            if self._event_bus is None:
                self._event_bus = EventBus()
                log.info("event_bus_created_in_pipeline", event_bus_id=id(self._event_bus))
            else:
                log.info("event_bus_reused_in_pipeline", event_bus_id=id(self._event_bus))
            budget = TokenBudgetManager()
            spacy_extractor = SpacyExtractor()

            self._pipeline = Pipeline(
                llm=self._llm_client,
                budget=budget,
                prompt_loader=self._prompt_loader,
                event_bus=self._event_bus,
                spacy=spacy_extractor,
                vector_repo=self.vector_repo(),
                article_repo=self.article_repo(),
                neo4j_writer=self.neo4j_writer(),
                source_auth_repo=self.source_authority_repo(),
                entity_resolver=self.entity_resolver(),
                redis_client=self._redis_client,
                community_updater=self.community_updater(),
            )
            log.info("pipeline_initialized")
        return self._pipeline

    def pipeline(self) -> Pipeline:
        """Get the processing pipeline."""
        if self._pipeline is None:
            raise RuntimeError("Pipeline not initialized. Call init_pipeline() first.")
        return self._pipeline

    # ── Lifecycle ─────────────────────────────────────────────────

    async def startup(self) -> None:
        """Initialize all services."""
        import os

        log.info("container_starting")

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        from core.db.initializer import initialize_database

        await initialize_database(
            self._settings.postgres.dsn,
            alembic_ini_path=os.path.join(project_root, "alembic.ini"),
            script_location=os.path.join(project_root, "src", "alembic"),
        )

        await self.init_postgres()
        await self.init_redis()
        if self._settings.neo4j.enabled:
            try:
                await self.init_neo4j()
            except ConnectionError as exc:
                log.warning("neo4j_unavailable_skipping", error=str(exc))
        else:
            log.info("neo4j_disabled_skipping")
        await self.init_llm()
        self.init_search_engines()
        await self.init_smart_fetcher()

        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=self.crawler(),
            article_repo=self.article_repo(),
            deduplicator=self.deduplicator(),
        )
        await self.init_source_scheduler(processor.on_items_discovered)

        await self.init_pipeline()
        processor.set_pipeline(self.pipeline())

        # Initialize LLM failure logging
        from modules.analytics.llm_failure.repo import LLMFailureRepo

        self._llm_failure_repo = LLMFailureRepo(self._postgres_pool)
        self._event_bus.subscribe(
            LLMFailureEvent,
            lambda e: _handle_llm_failure_async(e, self._llm_failure_repo),
        )
        log.info("llm_failure_logging_initialized", event_bus_id=id(self._event_bus))

        # Subscribe LLMUsageEvent handler for Prometheus metrics
        self._event_bus.subscribe(LLMUsageEvent, _handle_llm_usage_metrics)
        log.info("llm_usage_metrics_subscribed", event_bus_id=id(self._event_bus))

        # Initialize LLM usage statistics: buffer + raw record handler + aggregator thread
        self._llm_usage_buffer = LLMUsageBuffer(
            redis_client=self._redis_client,
            ttl_seconds=self._settings.scheduler.llm_usage_redis_buffer_ttl_seconds,
        )

        # Handler: accumulate to Redis buffer
        async def _handle_llm_usage_buffer(event: LLMUsageEvent) -> None:
            if self._llm_usage_buffer:
                await self._llm_usage_buffer.accumulate(event)

        # Handler: insert raw record to PostgreSQL
        async def _handle_llm_usage_raw(event: LLMUsageEvent) -> None:
            repo = LLMUsageRepo(self._postgres_pool)
            await repo.insert_raw(event)

        self._event_bus.subscribe(LLMUsageEvent, _handle_llm_usage_buffer)
        self._event_bus.subscribe(LLMUsageEvent, _handle_llm_usage_raw)
        log.info("llm_usage_handlers_subscribed", event_bus_id=id(self._event_bus))

        # Initialize pending sync repo
        self._pending_sync_repo = PendingSyncRepo(self._postgres_pool)

        # Setup unified scheduler (replaces all threads + duplicate scheduler)
        self._setup_scheduler()

        log.info("container_started")

    async def shutdown(self) -> None:
        """Shutdown all services in reverse order.

        This method is idempotent - calling it multiple times has no effect
        after the first call.
        """
        # Idempotency protection
        if self._shutdown:
            log.debug("shutdown_already_called")
            return

        self._shutdown = True
        log.info("container_shutting_down")

        # Stop main scheduler (replaces all thread stop calls)
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            log.info("main_scheduler_stopped")

        # Stop source scheduler
        if self._source_scheduler:
            self._source_scheduler.stop()
            log.info("source_scheduler_stopped")

        # Shutdown LLM queue manager (cancel worker tasks)
        if self._llm_client:
            try:
                queue_manager = self._llm_client._queue_manager
                if queue_manager:
                    await queue_manager.shutdown()
                    log.info("llm_queue_manager_stopped")
            except Exception as e:
                log.warning("llm_queue_manager_shutdown_error", error=str(e))

        # Shutdown pools
        if self._smart_fetcher:
            await self._smart_fetcher.close()
            log.info("smart_fetcher_shutdown")

        if self._redis_client:
            await self._redis_client.shutdown()
            log.info("redis_client_shutdown")

        if self._postgres_pool:
            await self._postgres_pool.shutdown()
            log.info("postgres_pool_shutdown")

        if self._neo4j_pool:
            await self._neo4j_pool.shutdown()
            log.info("neo4j_pool_shutdown")

        log.info("container_shutdown_complete")


# Global container instance
_container: Container | None = None


def get_container() -> Container:
    """Get the global container instance."""
    if _container is None:
        raise RuntimeError("Container not initialized. Create it in main.py first.")
    return _container


def set_container(container: Container) -> None:
    """Set the global container instance."""
    global _container
    _container = container


# Convenience function for settings access in auth middleware
_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Get settings instance (for auth middleware)."""
    global _settings_instance
    if _settings_instance is None:
        from config.settings import Settings

        _settings_instance = Settings()
    return _settings_instance


def set_settings(settings: Settings) -> None:
    """Set settings instance."""
    global _settings_instance
    _settings_instance = settings
