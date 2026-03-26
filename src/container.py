# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Dependency injection container for the weaver application.

This module provides a centralized dependency injection container for managing
the lifecycle of all core services. The container should be created once at
application startup and stored in FastAPI's app.state.

Usage:
    container = Container().configure(settings)
    await container.startup()
    app.state.container = container

    # Access dependencies via container properties
    redis = container.redis_client()
    llm = container.llm_client()
"""

from __future__ import annotations

from typing import Any

from config.settings import Settings
from core.cache import RedisClient
from core.db import Neo4jPool, PostgresPool
from core.event import EventBus, LLMFailureEvent
from core.llm.client import LLMClient
from core.llm.config_manager import LLMConfigManager
from core.llm.queue_manager import LLMQueueManager
from core.llm.rate_limiter import RedisTokenBucket
from core.llm.token_budget import TokenBudgetManager
from core.observability import get_logger
from core.prompt import PromptLoader
from core.utils.sanitize import sanitize_dsn
from modules.collector import Deduplicator
from modules.collector.crawler import Crawler
from modules.fetcher import PlaywrightContextPool, SmartFetcher
from modules.graph_store import EntityResolver, Neo4jWriter
from modules.graph_store.name_normalizer import name_normalizer
from modules.graph_store.resolution_rules import resolution_rules
from modules.pipeline.graph import Pipeline
from modules.search.engines.global_search import GlobalSearchEngine
from modules.search.engines.hybrid_search import HybridSearchConfig, HybridSearchEngine
from modules.search.engines.local_search import LocalSearchEngine
from modules.search.rerankers.flashrank_reranker import FlashrankReranker
from modules.search.rerankers.mmr_reranker import MMRReranker
from modules.search.retrievers.bm25_index_service import BM25IndexService
from modules.search.retrievers.bm25_retriever import BM25Retriever
from modules.source import SourceConfigRepo, SourceRegistry, SourceScheduler
from modules.storage import ArticleRepo, SourceAuthorityRepo, VectorRepo
from modules.storage.neo4j import Neo4jArticleRepo, Neo4jEntityRepo

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
        self._playwright_pool: PlaywrightContextPool | None = None
        self._crawler: Crawler | None = None
        self._pipeline: Pipeline | None = None
        self._deduplicator: Deduplicator | None = None
        self._event_bus: EventBus | None = None
        self._llm_failure_repo: Any = None
        self._llm_failure_cleanup_thread: Any = None
        self._local_search_engine: LocalSearchEngine | None = None
        self._global_search_engine: GlobalSearchEngine | None = None
        self._bm25_retriever: BM25Retriever | None = None
        self._bm25_index_service: BM25IndexService | None = None
        self._flashrank_reranker: FlashrankReranker | None = None
        self._mmr_reranker: MMRReranker | None = None
        self._hybrid_search_engine: HybridSearchEngine | None = None
        self._ap_scheduler: Any = None
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
            self._postgres_pool = PostgresPool(self._settings.postgres.dsn)
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
            log.info("init_neo4j_start", uri=sanitize_dsn(self._settings.neo4j.uri))
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
            log.info("init_redis_start", url=sanitize_dsn(self._settings.redis.url))
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
            config_manager = LLMConfigManager(self._settings.llm)

            rate_limiter = RedisTokenBucket(self._redis_client.client)

            self._event_bus = EventBus()
            log.info("event_bus_initialized_in_llm", event_bus_id=id(self._event_bus))
            queue_manager = LLMQueueManager(
                config_manager=config_manager,
                rate_limiter=rate_limiter,
                event_bus=self._event_bus,
                circuit_breaker_threshold=self._settings.fetcher.circuit_breaker_threshold,
                circuit_breaker_timeout=self._settings.fetcher.circuit_breaker_timeout,
            )
            await queue_manager.startup()

            prompt_loader = self.prompt_loader()
            token_budget = TokenBudgetManager()

            self._llm_client = LLMClient(
                queue_manager=queue_manager,
                prompt_loader=prompt_loader,
                token_budget=token_budget,
            )
            log.info("llm_client_initialized")

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

    # ── Context Manager Support ─────────────────────────────────────

    async def __aenter__(self) -> Container:
        """Async context manager entry - initializes all services."""
        await self.startup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - gracefully shuts down all services."""
        await self.shutdown()

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

        # Initialize hybrid search first (for injection)
        if self._hybrid_search_engine is None:
            self.init_hybrid_search()

        if self._local_search_engine is None:
            self._local_search_engine = LocalSearchEngine(
                neo4j_pool=self._neo4j_pool,
                llm=self._llm_client,
                hybrid_engine=self._hybrid_search_engine,
            )
        if self._global_search_engine is None:
            self._global_search_engine = GlobalSearchEngine(
                neo4j_pool=self._neo4j_pool,
                llm=self._llm_client,
                hybrid_engine=self._hybrid_search_engine,
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

    # ── Hybrid Search Components ─────────────────────────────────────

    def init_hybrid_search(self) -> HybridSearchEngine | None:
        """Initialize hybrid search components.

        Requires settings with search configuration.
        """
        if self._hybrid_search_engine is not None:
            return self._hybrid_search_engine

        try:
            search_config = getattr(self._settings, "search", None)
            if search_config is None:
                # Use defaults
                search_config = HybridSearchConfig()

            # Initialize BM25 retriever
            self._bm25_retriever = BM25Retriever(
                language="zh",
                index_dir="/tmp/weaver_bm25_index",  # noqa: S108 - configurable index dir
            )

            # Initialize Flashrank reranker
            self._flashrank_reranker = FlashrankReranker(
                model_name=(
                    search_config.rerank_model if hasattr(search_config, "rerank_model") else "tiny"
                ),
                enabled=(
                    search_config.rerank_enabled
                    if hasattr(search_config, "rerank_enabled")
                    else True
                ),
            )

            # Initialize MMR reranker
            mmr_lambda = search_config.mmr_lambda if hasattr(search_config, "mmr_lambda") else 0.7
            self._mmr_reranker = MMRReranker(lambda_param=mmr_lambda)

            # Build hybrid config
            hybrid_config = HybridSearchConfig(
                hybrid_enabled=(
                    search_config.hybrid_enabled
                    if hasattr(search_config, "hybrid_enabled")
                    else True
                ),
                rerank_enabled=(
                    search_config.rerank_enabled
                    if hasattr(search_config, "rerank_enabled")
                    else True
                ),
                rerank_model=(
                    search_config.rerank_model if hasattr(search_config, "rerank_model") else "tiny"
                ),
                mmr_enabled=(
                    search_config.mmr_enabled if hasattr(search_config, "mmr_enabled") else False
                ),
                mmr_lambda=mmr_lambda,
            )

            # Initialize hybrid search engine
            self._hybrid_search_engine = HybridSearchEngine(
                vector_repo=self._vector_repo,
                bm25_retriever=self._bm25_retriever,
                reranker=self._flashrank_reranker,
                mmr_reranker=self._mmr_reranker,
                config=hybrid_config,
            )

            # Initialize BM25 index service
            rebuild_interval = (
                search_config.bm25_rebuild_interval
                if hasattr(search_config, "bm25_rebuild_interval")
                else 300
            )
            self._bm25_index_service = BM25IndexService(
                postgres_pool=self._postgres_pool,
                bm25_retriever=self._bm25_retriever,
                rebuild_interval_seconds=rebuild_interval,
            )

            log.info(
                "hybrid_search_initialized",
                hybrid_enabled=hybrid_config.hybrid_enabled,
                rerank_enabled=hybrid_config.rerank_enabled,
                mmr_enabled=hybrid_config.mmr_enabled,
                bm25_rebuild_interval=rebuild_interval,
            )

        except Exception as exc:
            log.warning("hybrid_search_init_failed", error=str(exc))
            return None

        return self._hybrid_search_engine

    def bm25_retriever(self) -> BM25Retriever | None:
        """Get BM25 retriever (or None if unavailable)."""
        return self._bm25_retriever

    def bm25_index_service(self) -> BM25IndexService | None:
        """Get BM25 index service (or None if unavailable)."""
        return self._bm25_index_service

    async def init_bm25_scheduler(self) -> None:
        """Initialize APScheduler for BM25 index rebuilding.

        This sets up a background task that periodically rebuilds the BM25 index.
        """
        if self._bm25_index_service is None:
            log.warning("bm25_scheduler_no_index_service")
            return

        try:
            from apscheduler.schedulers.asyncio import AsyncScheduler

            self._ap_scheduler = AsyncScheduler()

            # Schedule BM25 rebuild job
            from modules.search.retrievers.bm25_index_service import create_bm25_scheduler_job

            create_bm25_scheduler_job(self._ap_scheduler, self._bm25_index_service)

            # Start the scheduler
            await self._ap_scheduler.start()

            log.info(
                "bm25_scheduler_started",
                rebuild_interval=self._bm25_index_service._rebuild_interval,
            )

            # Build initial index asynchronously
            if self._bm25_index_service.get_stats()["document_count"] == 0:
                log.info("bm25_building_initial_index")
                doc_count = await self._bm25_index_service.build_full_index()
                log.info("bm25_initial_index_built", document_count=doc_count)

        except ImportError:
            log.warning("apscheduler_not_installed_bm25_scheduler_disabled")
        except Exception as exc:
            log.error("bm25_scheduler_init_failed", error=str(exc))

    def hybrid_search_engine(self) -> HybridSearchEngine | None:
        """Get hybrid search engine (or None if unavailable)."""
        if self._hybrid_search_engine is None:
            self.init_hybrid_search()
        return self._hybrid_search_engine

    # ── Fetcher & Crawler ────────────────────────────────────────

    async def init_playwright_pool(self) -> PlaywrightContextPool:
        """Initialize Playwright browser pool with stealth configuration."""
        if self._playwright_pool is None:
            settings = self._settings.fetcher
            self._playwright_pool = PlaywrightContextPool(
                pool_size=settings.playwright_pool_size,
                stealth_enabled=settings.stealth_enabled,
                user_agent=settings.stealth_user_agent,
                viewport_width=settings.stealth_viewport_width,
                viewport_height=settings.stealth_viewport_height,
                locale=settings.stealth_locale,
                timezone=settings.stealth_timezone,
                random_delay_min=settings.stealth_random_delay_min,
                random_delay_max=settings.stealth_random_delay_max,
            )
            await self._playwright_pool.startup()
            log.info(
                "playwright_pool_initialized",
                pool_size=settings.playwright_pool_size,
                stealth_enabled=settings.stealth_enabled,
            )
        return self._playwright_pool

    def playwright_pool(self) -> PlaywrightContextPool:
        """Get Playwright pool."""
        if self._playwright_pool is None:
            raise RuntimeError(
                "Playwright pool not initialized. Call init_playwright_pool() first."
            )
        return self._playwright_pool

    async def init_smart_fetcher(self) -> SmartFetcher:
        """Initialize smart fetcher."""
        if self._smart_fetcher is None:
            from modules.fetcher.httpx_fetcher import HttpxFetcher
            from modules.fetcher.playwright_fetcher import PlaywrightFetcher
            from modules.fetcher.rate_limiter import HostRateLimiter

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
            playwright_fetcher = PlaywrightFetcher(
                pool=self._playwright_pool,
            )
            self._smart_fetcher = SmartFetcher(
                httpx_fetcher=httpx_fetcher,
                playwright_fetcher=playwright_fetcher,
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
            from modules.nlp.spacy_extractor import SpacyExtractor

            if self._event_bus is None:
                self._event_bus = EventBus()
                log.info("event_bus_created_in_pipeline", event_bus_id=id(self._event_bus))
            else:
                log.info("event_bus_reused_in_pipeline", event_bus_id=id(self._event_bus))
            budget = TokenBudgetManager()
            spacy_extractor = SpacyExtractor()

            # Get embedding model from settings
            embedding_model = (
                self._settings.llm.embedding_model if self._settings else "text-embedding-3-large"
            )

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
                embedding_model=embedding_model,
            )
            log.info("pipeline_initialized", embedding_model=embedding_model)
        return self._pipeline

    def pipeline(self) -> Pipeline:
        """Get the processing pipeline."""
        if self._pipeline is None:
            raise RuntimeError("Pipeline not initialized. Call init_pipeline() first.")
        return self._pipeline

    # ── Lifecycle ─────────────────────────────────────────────────

    async def startup(self) -> None:
        """Initialize all services.

        This method performs the following steps:
        1. Pre-startup health checks (if enabled)
        2. Database initialization (PostgreSQL)
        3. Redis initialization
        4. Neo4j initialization (optional)
        5. LLM client initialization
        6. Search engines initialization
        7. Fetcher and crawler initialization
        8. Pipeline initialization
        """
        import os

        log.info("container_starting")

        # ── Pre-startup Health Checks ─────────────────────────────
        if self._settings.health_check.pre_startup_enabled:
            await self._run_pre_startup_health_checks()

        # ── Database Initialization ───────────────────────────────
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        from core.db.initializer import initialize_database, initialize_neo4j

        await initialize_database(
            self._settings.postgres.dsn,
            alembic_ini_path=os.path.join(project_root, "alembic.ini"),
            script_location=os.path.join(project_root, "src", "alembic"),
        )

        await self.init_postgres()
        await self.init_redis()

        # ── Neo4j Initialization (Optional) ───────────────────────
        neo4j_available = await self._initialize_neo4j_safe()

        # ── Core Services Initialization ───────────────────────────
        await self.init_llm()

        # Initialize search engines only if Neo4j is available
        if neo4j_available:
            self.init_search_engines()
            self.init_hybrid_search()

            # Initialize Neo4j constraints
            if self._neo4j_pool is not None:
                neo4j_init_result = await initialize_neo4j(self._neo4j_pool)
                if neo4j_init_result.get("constraints_created"):
                    log.info(
                        "neo4j_constraints_created",
                        constraints=neo4j_init_result.get("constraints_created", []),
                    )

        await self.init_playwright_pool()
        await self.init_smart_fetcher()

        from modules.collector.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=self.crawler(),
            article_repo=self.article_repo(),
            deduplicator=self.deduplicator(),
        )
        await self.init_source_scheduler(processor.on_items_discovered)

        await self.init_pipeline()
        processor.set_pipeline(self.pipeline())

        # Initialize LLM failure logging
        from modules.scheduler.llm_failure_cleanup import LLMFailureCleanupThread
        from modules.storage.llm_failure_repo import LLMFailureRepo

        self._llm_failure_repo = LLMFailureRepo(self._postgres_pool)
        self._event_bus.subscribe(
            LLMFailureEvent,
            lambda e: _handle_llm_failure_async(e, self._llm_failure_repo),
        )
        self._llm_failure_cleanup_thread = LLMFailureCleanupThread(self._llm_failure_repo)
        self._llm_failure_cleanup_thread.start()
        log.info("llm_failure_logging_initialized", event_bus_id=id(self._event_bus))

        # Initialize BM25 index scheduler
        await self.init_bm25_scheduler()

        log.info("container_started")

    async def _run_pre_startup_health_checks(self) -> None:
        """Run pre-startup health checks for required services.

        This method checks the health of required services before
        proceeding with initialization. If any required service fails,
        the startup process is aborted.
        """
        from core.health import PreStartupHealthChecker

        checker = PreStartupHealthChecker(
            self._settings.health_check,
            self._settings,
        )

        results = await checker.check_all()
        summary = checker.get_summary()

        # Log results
        for service, result in results.items():
            if result.healthy:
                log.info(
                    "pre_startup_service_healthy",
                    service=service,
                    latency_ms=result.latency_ms,
                )
            else:
                log.warning(
                    "pre_startup_service_unhealthy",
                    service=service,
                    error=result.error,
                    details=result.details,
                )

        # Check if required services are healthy
        if not summary["required_services_healthy"]:
            failed = summary["failed_required_services"]
            log.error(
                "pre_startup_health_check_failed",
                failed_services=failed,
            )
            raise RuntimeError(
                f"Required services not available: {', '.join(failed)}. "
                "Please ensure all required services are running before starting the application."
            )

        log.info("pre_startup_health_check_passed")

    async def _initialize_neo4j_safe(self) -> bool:
        """Safely initialize Neo4j, handling connection failures.

        Returns:
            True if Neo4j was initialized successfully, False otherwise.
        """
        neo4j_required = "neo4j" in self._settings.health_check.required_services

        try:
            await self.init_neo4j()
            return True
        except ConnectionError as exc:
            if neo4j_required:
                log.error("neo4j_required_but_unavailable", error=str(exc))
                raise RuntimeError(
                    "Neo4j is configured as required but is not available. " f"Error: {exc}"
                ) from exc
            log.warning("neo4j_unavailable_skipping", error=str(exc))
            return False
        except Exception as exc:
            if neo4j_required:
                log.error("neo4j_initialization_failed", error=str(exc))
                raise
            log.warning("neo4j_initialization_skipped", error=str(exc))
            return False

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

        # Stop LLM failure cleanup thread
        if self._llm_failure_cleanup_thread:
            self._llm_failure_cleanup_thread.stop()
            log.info("llm_failure_cleanup_thread_stopped")

        # Stop scheduler first
        if self._source_scheduler:
            self._source_scheduler.stop()
            log.info("source_scheduler_stopped")

        # Stop APScheduler (BM25 index rebuild)
        if self._ap_scheduler:
            try:
                await self._ap_scheduler.stop()
                log.info("ap_scheduler_stopped")
            except Exception as e:
                log.warning("ap_scheduler_shutdown_error", error=str(e))

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
        if self._playwright_pool:
            await self._playwright_pool.shutdown()
            log.info("playwright_pool_shutdown")

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


# ── Application-Level Container Access ─────────────────────────────────────────
#
# RECOMMENDED: Access container via FastAPI app.state
#   container = request.app.state.container
#   redis = container.redis_client()
#
# DEPRECATED: Global container access (only for backward compatibility)
#   from container import get_container, set_container
#   container = get_container()
#
# The global pattern is maintained for:
#   1. cache_decorator.py which cannot easily access app.state
#   2. Legacy endpoint modules not yet migrated to app.state pattern
#   3. Scheduled jobs that run outside request context
#
# New code should use app.state.container or pass container explicitly.

_container: Container | None = None


def get_container() -> Container:
    """Get the global container instance (DEPRECATED).

    .. deprecated:: 0.2.0
        Use `api.dependencies.get_container()` or FastAPI dependency injection
        instead. This global accessor will be removed in a future version.

    Returns:
        The global Container instance.

    Raises:
        RuntimeError: If container has not been initialized.
    """
    import warnings

    warnings.warn(
        "get_container() is deprecated. Use api.dependencies.get_container() "
        "or FastAPI dependency injection instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    if _container is None:
        raise RuntimeError(
            "Container not initialized. Create and configure a Container first, "
            "or access via app.state.container in FastAPI request context."
        )
    return _container


def set_container(container: Container) -> None:
    """Set the global container instance (DEPRECATED).

    Args:
        container: Container instance to set as global.

    Note:
        Prefer setting app.state.container in FastAPI lifespan handler.
        This function is maintained for backward compatibility.
    """
    global _container
    _container = container


def clear_container() -> None:
    """Clear the global container instance.

    Useful for testing scenarios where container needs to be reset.
    """
    global _container
    _container = None


# ── Settings Access ────────────────────────────────────────────────────────────
#
# Settings are typically accessed via container.settings
# The global _settings_instance is only used for auth middleware
# which runs before container is fully initialized.

_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Get settings instance (primarily for auth middleware).

    Returns:
        Settings instance.

    Note:
        In normal application flow, settings should be accessed via
        container.settings. This is only needed for middleware that
        runs before container initialization.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def set_settings(settings: Settings) -> None:
    """Set settings instance.

    Args:
        settings: Settings instance to set globally.
    """
    global _settings_instance
    _settings_instance = settings


def clear_settings() -> None:
    """Clear the global settings instance.

    Useful for testing scenarios where settings need to be reset.
    """
    global _settings_instance
    _settings_instance = None
