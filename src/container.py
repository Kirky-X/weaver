"""Dependency injection container for the news discovery application."""

from __future__ import annotations

from typing import Any

from config.settings import Settings
from core.db.postgres import PostgresPool
from core.db.neo4j import Neo4jPool
from core.cache.redis import RedisClient
from core.observability.logging import get_logger
from core.llm.client import LLMClient
from core.llm.config_manager import LLMConfigManager
from core.llm.token_budget import TokenBudgetManager
from core.llm.rate_limiter import RedisTokenBucket
from core.llm.queue_manager import LLMQueueManager
from core.event.bus import EventBus
from core.prompt.loader import PromptLoader
from modules.source.registry import SourceRegistry
from modules.source.scheduler import SourceScheduler
from modules.storage.article_repo import ArticleRepo
from modules.storage.vector_repo import VectorRepo
from modules.storage.source_authority_repo import SourceAuthorityRepo
from modules.storage.neo4j.entity_repo import Neo4jEntityRepo
from modules.storage.neo4j.article_repo import Neo4jArticleRepo
from modules.graph_store.neo4j_writer import Neo4jWriter
from modules.graph_store.entity_resolver import EntityResolver
from modules.fetcher.smart_fetcher import SmartFetcher
from core.fetcher.playwright_pool import PlaywrightContextPool
from modules.collector.crawler import Crawler
from modules.collector.deduplicator import Deduplicator
from modules.pipeline.graph import Pipeline

log = get_logger("container")


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

    def configure(self, settings: Settings) -> "Container":
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
            log.info("init_neo4j_start", uri=self._settings.neo4j.uri, password="***")
            self._neo4j_pool = Neo4jPool(
                self._settings.neo4j.uri,
                ("neo4j", self._settings.neo4j.password),
            )
            await self._neo4j_pool.startup()
            log.info("neo4j_initialized")
        return self._neo4j_pool

    def neo4j_pool(self) -> Neo4jPool:
        """Get Neo4j pool."""
        if self._neo4j_pool is None:
            raise RuntimeError("Neo4j pool not initialized. Call init_neo4j() first.")
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
            config_manager = LLMConfigManager(self._settings.llm)

            rate_limiter = RedisTokenBucket(self._redis_client.client)

            event_bus = EventBus()
            queue_manager = LLMQueueManager(
                config_manager=config_manager,
                rate_limiter=rate_limiter,
                event_bus=event_bus,
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
                raise RuntimeError("Smart fetcher not initialized. Call init_smart_fetcher() first.")
            self._source_registry = SourceRegistry(self._smart_fetcher)
        return self._source_registry

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
            raise RuntimeError("Source scheduler not initialized. Call init_source_scheduler() first.")
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

    def neo4j_entity_repo(self) -> Neo4jEntityRepo:
        """Get Neo4j entity repository."""
        if self._neo4j_entity_repo is None:
            self._neo4j_entity_repo = Neo4jEntityRepo(self._neo4j_pool)
        return self._neo4j_entity_repo

    def neo4j_article_repo(self) -> Neo4jArticleRepo:
        """Get Neo4j article repository."""
        if self._neo4j_article_repo is None:
            self._neo4j_article_repo = Neo4jArticleRepo(self._neo4j_pool)
        return self._neo4j_article_repo

    def neo4j_writer(self) -> Neo4jWriter:
        """Get Neo4j writer."""
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
            )
        return self._entity_resolver

    # ── Vector Repository ─────────────────────────────────────────

    def vector_repo(self) -> VectorRepo:
        """Get vector repository."""
        if self._vector_repo is None:
            self._vector_repo = VectorRepo(self._postgres_pool)
        return self._vector_repo

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
            raise RuntimeError("Playwright pool not initialized. Call init_playwright_pool() first.")
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
                rate_limiter=rate_limiter,
            )
            playwright_fetcher = PlaywrightFetcher(
                pool=self._playwright_pool,
            )
            self._smart_fetcher = SmartFetcher(
                httpx_fetcher=httpx_fetcher,
                playwright_fetcher=playwright_fetcher,
                rate_limiter=rate_limiter,
            )
            log.info("smart_fetcher_initialized")
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

    async def init_pipeline(self) -> "Pipeline":
        """Initialize the processing pipeline."""
        if self._pipeline is None:
            from core.llm.token_budget import TokenBudgetManager
            from core.event.bus import EventBus
            from modules.nlp.spacy_extractor import SpacyExtractor

            event_bus = EventBus()
            budget = TokenBudgetManager()
            spacy_extractor = SpacyExtractor()

            self._pipeline = Pipeline(
                llm=self._llm_client,
                budget=budget,
                prompt_loader=self._prompt_loader,
                event_bus=event_bus,
                spacy=spacy_extractor,
                vector_repo=self.vector_repo(),
                article_repo=self.article_repo(),
                neo4j_writer=self.neo4j_writer(),
                source_auth_repo=self.source_authority_repo(),
            )
            log.info("pipeline_initialized")
        return self._pipeline

    def pipeline(self) -> "Pipeline":
        """Get the processing pipeline."""
        if self._pipeline is None:
            raise RuntimeError("Pipeline not initialized. Call init_pipeline() first.")
        return self._pipeline

    # ── Lifecycle ─────────────────────────────────────────────────

    async def startup(self) -> None:
        """Initialize all services."""
        log.info("container_starting")

        await self.init_postgres()
        await self.init_redis()
        await self.init_neo4j()
        await self.init_llm()
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

        log.info("container_started")

    async def shutdown(self) -> None:
        """Shutdown all services in reverse order."""
        log.info("container_shutting_down")

        # Stop scheduler first
        if self._source_scheduler:
            self._source_scheduler.stop()

        # Shutdown pools
        if self._playwright_pool:
            await self._playwright_pool.shutdown()

        if self._redis_client:
            await self._redis_client.shutdown()

        if self._postgres_pool:
            await self._postgres_pool.shutdown()

        if self._neo4j_pool:
            await self._neo4j_pool.shutdown()

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
