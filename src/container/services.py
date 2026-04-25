# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Service and repository instantiation for the container."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.constants import DatabaseType

if TYPE_CHECKING:
    from config.settings import Settings
    from core.llm import LLMClient
    from core.protocols import (
        EntityRepository,
        VectorRepository,
    )
    from core.protocols.repositories import (
        ArticleRepository,
        GraphArticleRepository,
        GraphWriter,
    )
    from core.services.pipeline_service import PipelineServiceImpl
    from core.services.task_registry import InMemoryTaskRegistry
    from modules.analytics import LLMUsageBuffer, LLMUsageRepo
    from modules.analytics.llm_failure.repo import LLMFailureRepo
    from modules.ingestion import (
        Crawler,
        Deduplicator,
        SmartFetcher,
        SourceConfigRepo,
        SourceRegistry,
        SourceScheduler,
    )
    from modules.knowledge.graph import EntityResolver
    from modules.knowledge.graph.community.updater import IncrementalCommunityUpdater
    from modules.processing.pipeline.graph import Pipeline
    from modules.storage.postgres import PendingSyncRepo, SourceAuthorityRepo


class ContainerServicesMixin:
    """Service and repository management mixin.

    Provides lazy initialization and access to all application services,
    repositories, crawlers, fetchers, and pipeline components.
    """

    # ── Private attributes (defined in Container.__init__) ─────────
    _settings: Settings | None
    _strategy: Any
    _cache_client: Any
    _llm_client: LLMClient | None
    _prompt_loader: Any
    _source_registry: SourceRegistry | None
    _source_config_repo: SourceConfigRepo | None
    _source_scheduler: SourceScheduler | None
    _article_repo: ArticleRepository | None
    _vector_repo: VectorRepository | None
    _source_authority_repo: SourceAuthorityRepo | None
    _graph_entity_repo: Any
    _graph_article_repo: GraphArticleRepository | None
    _graph_writer: GraphWriter | None
    _graph_repo: Any
    _entity_resolver: EntityResolver | None
    _smart_fetcher: SmartFetcher | None
    _crawl4ai_fetcher: Any
    _crawler: Crawler | None
    _pipeline: Pipeline | None
    _pipeline_service: PipelineServiceImpl | None
    _task_registry: InMemoryTaskRegistry | None
    _deduplicator: Deduplicator | None
    _event_bus: Any
    _llm_failure_repo: LLMFailureRepo | None
    _llm_usage_buffer: LLMUsageBuffer | None
    _llm_experience: Any
    _live_config: Any
    _smart_router: Any
    _eval_runner: Any
    _eval_compare_buffer: Any
    _pending_sync_repo: PendingSyncRepo | None
    _scheduler_jobs_service: Any
    _scheduler: Any
    _community_updater: IncrementalCommunityUpdater | None
    _relation_type_normalizer: Any
    _memory_service: Any
    _shutdown: bool
    _knowledge_cache: Any
    _mc_sampler: Any
    _causal_repo: Any
    _causal_inference_service: Any
    _processing_queue: Any
    _pipeline_worker: Any

    # ── Prompt Loader ─────────────────────────────────────────────

    def prompt_loader(self) -> Any:
        """Get prompt loader."""
        if self._prompt_loader is None:
            from core.prompt import PromptLoader

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
            from modules.ingestion import SourceRegistry

            self._source_registry = SourceRegistry(self._smart_fetcher)
        return self._source_registry

    def source_config_repo(self) -> SourceConfigRepo:
        """Get source config repository (database-backed)."""
        if self._source_config_repo is None:
            if self._strategy is None:
                raise RuntimeError("Database strategy not initialized. Call init_strategy() first.")
            from modules.ingestion import SourceConfigRepo

            self._source_config_repo = SourceConfigRepo(self._strategy.relational_pool)
        return self._source_config_repo

    async def init_source_scheduler(self, on_items_discovered: Any = None) -> SourceScheduler:
        """Initialize source scheduler."""
        from core.observability import get_logger
        from modules.ingestion import SourceScheduler

        log = get_logger(__name__)

        if self._source_scheduler is None:
            # Default callback - can be overridden
            async def default_callback(
                items: Any,
                source: Any,
                max_items: int | None = None,
                task_id: Any = None,
                force: bool = False,
            ) -> None:
                log.info("items_discovered", count=len(items), source=source.id, force=force)

            registry = self.source_registry()
            # Bridge DB sources into the in-memory registry so the scheduler
            # discovers and crawls all DB-persisted sources on startup.
            db_sources = await self.source_config_repo().list_sources(enabled_only=True)
            for cfg in db_sources:
                registry.add_source(cfg)
            self._source_scheduler = SourceScheduler(
                registry=registry,
                on_items_discovered=on_items_discovered or default_callback,
                repo=self.source_config_repo(),
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

    def article_repo(self) -> ArticleRepository:
        """Get article repository (PostgreSQL or DuckDB implementation)."""
        if self._article_repo is None:
            if self._strategy is None:
                raise RuntimeError("Database strategy not initialized. Call init_strategy() first.")
            if self._strategy.relational_type == DatabaseType.DUCKDB:
                from modules.storage.duckdb import DuckDBArticleRepo

                self._article_repo = DuckDBArticleRepo(self._strategy.relational_pool)
            else:
                from modules.storage.postgres import ArticleRepo

                self._article_repo = ArticleRepo(self._strategy.relational_pool)
        return self._article_repo

    def source_authority_repo(self) -> SourceAuthorityRepo:
        """Get source authority repository (PostgreSQL or DuckDB implementation)."""
        if self._source_authority_repo is None:
            if self._strategy is None:
                raise RuntimeError("Database strategy not initialized. Call init_strategy() first.")
            if self._strategy.relational_type == DatabaseType.DUCKDB:
                from modules.storage.duckdb import DuckDBSourceAuthorityRepo

                self._source_authority_repo = DuckDBSourceAuthorityRepo(
                    self._strategy.relational_pool
                )
            else:
                from modules.storage.postgres import SourceAuthorityRepo

                self._source_authority_repo = SourceAuthorityRepo(self._strategy.relational_pool)
        return self._source_authority_repo

    def pending_sync_repo(self) -> PendingSyncRepo:
        """Get pending sync repository (PostgreSQL or DuckDB implementation)."""
        if self._pending_sync_repo is None:
            if self._strategy is None:
                raise RuntimeError("Database strategy not initialized. Call init_strategy() first.")
            if self._strategy.relational_type == DatabaseType.DUCKDB:
                from modules.storage.duckdb import DuckDBPendingSyncRepo

                self._pending_sync_repo = DuckDBPendingSyncRepo(self._strategy.relational_pool)
            else:
                from modules.storage.postgres import PendingSyncRepo

                self._pending_sync_repo = PendingSyncRepo(self._strategy.relational_pool)
        return self._pending_sync_repo

    def llm_failure_repo(self) -> LLMFailureRepo:
        """Get LLM failure repository."""
        if self._llm_failure_repo is None:
            from modules.analytics.llm_failure.repo import LLMFailureRepo

            self._llm_failure_repo = LLMFailureRepo(self.relational_pool())
        return self._llm_failure_repo

    def llm_usage_buffer(self) -> LLMUsageBuffer | None:
        """Get LLM usage buffer (or None if not initialized)."""
        return self._llm_usage_buffer

    def llm_usage_repo(self) -> LLMUsageRepo:
        """Get LLM usage repository."""
        if self._llm_usage_repo is None:
            from modules.analytics import LLMUsageRepo

            self._llm_usage_repo = LLMUsageRepo(self.relational_pool())
        return self._llm_usage_repo

    def scheduler_job_runner(self) -> Any:
        """Get scheduler job runner instance."""
        if self._scheduler_jobs_service is None:
            from modules.scheduler.jobs import SchedulerJobs

            self._scheduler_jobs_service = SchedulerJobs(
                relational_pool=self.relational_pool(),
                cache=self.cache_client(),
                graph_writer=self.graph_writer(),
                vector_repo=self.vector_repo(),
                article_repo=self.article_repo(),
                source_authority_repo=self.source_authority_repo(),
                pending_sync_repo=self.pending_sync_repo(),
                pipeline=self.pipeline(),
                settings=self._settings.scheduler if self._settings else None,
                llm_failure_repo=self.llm_failure_repo(),
                url_validator=None,
            )
        return self._scheduler_jobs_service

    # ── Graph Repositories ─────────────────────────────────────────

    def graph_entity_repo(self) -> EntityRepository | None:
        """Get graph entity repository (Neo4j or LadybugDB implementation)."""
        graph_pool = self.graph_pool()
        if graph_pool is None:
            return None
        if self._strategy is None:
            return None
        if self._graph_entity_repo is None:
            if self._strategy.graph_type == "ladybug":
                from modules.storage.ladybug import LadybugEntityRepo

                self._graph_entity_repo = LadybugEntityRepo(graph_pool)
            else:
                from modules.storage.neo4j import Neo4jEntityRepo

                self._graph_entity_repo = Neo4jEntityRepo(graph_pool)
        return self._graph_entity_repo

    def graph_article_repo(self) -> GraphArticleRepository | None:
        """Get graph article repository (Neo4j or LadybugDB implementation)."""
        graph_pool = self.graph_pool()
        if graph_pool is None:
            return None
        if self._strategy is None:
            return None
        if self._graph_article_repo is None:
            if self._strategy.graph_type == "ladybug":
                from modules.storage.ladybug import LadybugArticleRepo

                self._graph_article_repo = LadybugArticleRepo(graph_pool)
            else:
                from modules.storage.neo4j import Neo4jArticleRepo

                self._graph_article_repo = Neo4jArticleRepo(graph_pool)
        return self._graph_article_repo

    def causal_repo(self) -> Any | None:
        """Get causal graph repository (Neo4j or LadybugDB implementation).

        Returns:
            CausalGraphRepo implementation or None if graph database unavailable.

        """
        graph_pool = self.graph_pool()
        if graph_pool is None:
            return None
        if self._strategy is None:
            return None
        if self._causal_repo is None:
            from modules.memory.graphs.causal import CausalGraphRepo

            self._causal_repo = CausalGraphRepo(graph_pool)
        return self._causal_repo

    def graph_writer(self) -> GraphWriter | None:
        """Get graph writer (Neo4j or LadybugDB implementation)."""
        graph_pool = self.graph_pool()
        if graph_pool is None:
            return None
        if self._strategy is None:
            return None
        if self._graph_writer is None:
            rt_normalizer = self.relation_normalizer()
            if self._strategy.graph_type == "ladybug":
                from modules.storage.ladybug import LadybugWriter

                self._graph_writer = LadybugWriter(graph_pool, rt_normalizer)
            else:
                from modules.knowledge.graph import Neo4jWriter

                self._graph_writer = Neo4jWriter(graph_pool, rt_normalizer)
        return self._graph_writer

    def graph_repo(self) -> Any:
        """Get database-agnostic graph repository."""
        if self._graph_repo is None:
            graph_pool = self.graph_pool()
            if graph_pool is None or self._strategy is None:
                raise RuntimeError("Graph database not available")

            from core.db.graph_query_builders import create_graph_query_builder
            from modules.storage.graph_repo import GraphRepository

            query_builder = create_graph_query_builder(self._strategy.graph_type)

            # When Neo4j is primary, configure LadybugDB as lazy fallback
            fallback_pool_factory = None
            fallback_query_builder = None
            if self._strategy.graph_type == "neo4j":
                from core.db.ladybug_pool import LadybugPool

                def _create_ladybug_fallback() -> LadybugPool:
                    return LadybugPool(db_path=self._settings.ladybug.db_path)

                fallback_pool_factory = _create_ladybug_fallback
                fallback_query_builder = create_graph_query_builder("ladybug")

            self._graph_repo = GraphRepository(
                graph_pool, query_builder, fallback_pool_factory, fallback_query_builder
            )
        return self._graph_repo

    def relation_normalizer(self) -> Any | None:
        """Get cached RelationTypeNormalizer instance."""
        if self._relation_type_normalizer is None and self._strategy is not None:
            from modules.knowledge.core.relation_types import RelationTypeNormalizer

            self._relation_type_normalizer = RelationTypeNormalizer(self._strategy.relational_pool)
        return self._relation_type_normalizer

    def entity_resolver(self) -> EntityResolver:
        """Get entity resolver."""
        from modules.knowledge.graph import EntityResolver, name_normalizer, resolution_rules

        if self._entity_resolver is None:
            disable_data_metrics = (
                self._settings.entity.disable_data_metrics_nodes if self._settings else False
            )
            self._entity_resolver = EntityResolver(
                entity_repo=self.graph_entity_repo(),
                vector_repo=self.vector_repo(),
                llm=self._llm_client,
                resolution_rules=resolution_rules,
                name_normalizer=name_normalizer,
                disable_data_metrics=disable_data_metrics,
                embedding_model=self._get_embedding_model_id(),
            )
        return self._entity_resolver

    def community_updater(self) -> IncrementalCommunityUpdater | None:
        """Get community updater (works with Neo4j or LadybugDB)."""
        if self._strategy is None:
            return None
        # Community detection works with both Neo4j and LadybugDB
        if self._community_updater is None:
            from modules.knowledge.graph.community.updater import IncrementalCommunityUpdater

            self._community_updater = IncrementalCommunityUpdater(
                pool=self.graph_pool(), llm_client=self.llm_client()
            )
        return self._community_updater

    # ── Vector Repository ─────────────────────────────────────────

    def vector_repo(self) -> VectorRepository:
        """Get vector repository with database-specific query builder."""
        if self._vector_repo is None:
            if self._strategy is None:
                raise RuntimeError("Database strategy not initialized. Call init_strategy() first.")
            from core.db.query_builders import create_vector_query_builder
            from modules.storage.postgres import VectorRepo

            query_builder = create_vector_query_builder(self._strategy.relational_type)
            self._vector_repo = VectorRepo(
                pool=self._strategy.relational_pool,
                query_builder=query_builder,
            )
        return self._vector_repo

    # ── Fetcher & Crawler ────────────────────────────────────────

    async def init_crawl4ai_fetcher(self) -> Any:
        """Initialize Crawl4AIFetcher for JS-rendered pages."""
        from core.observability import get_logger
        from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher

        log = get_logger(__name__)

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
        from core.observability import get_logger
        from modules.ingestion import SmartFetcher
        from modules.ingestion.fetching import HostRateLimiter, HttpxFetcher
        from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher

        log = get_logger(__name__)

        if self._smart_fetcher is None:
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
        from modules.ingestion import Crawler

        if self._crawler is None:
            self._crawler = Crawler(
                smart_fetcher=self._smart_fetcher,
                default_per_host=self._settings.fetcher.default_per_host_concurrency,
            )
        return self._crawler

    def deduplicator(self) -> Deduplicator:
        """Get deduplicator."""
        from modules.ingestion import Deduplicator

        if self._deduplicator is None:
            self._deduplicator = Deduplicator(
                cache=self._cache_client,
                article_repo=self._article_repo,
            )
        return self._deduplicator

    # ── Pipeline ─────────────────────────────────────────────────

    async def init_pipeline(self) -> Pipeline:
        """Initialize the processing pipeline."""
        from core.event import EventBus
        from core.llm.config.token_budget import TokenBudgetManager
        from core.observability import get_logger
        from modules.processing.nlp.spacy_extractor import SpacyExtractor
        from modules.processing.pipeline.graph import Pipeline

        log = get_logger(__name__)

        if self._pipeline is None:
            if self._event_bus is None:
                self._event_bus = EventBus()
                log.info("event_bus_created_in_pipeline", event_bus_id=id(self._event_bus))
            else:
                log.info("event_bus_reused_in_pipeline", event_bus_id=id(self._event_bus))
            budget = TokenBudgetManager()
            spacy_extractor = SpacyExtractor(
                zh_model_path=self._settings.spacy.zh_model_path,
                en_model_path=self._settings.spacy.en_model_path,
            )

            self._pipeline = Pipeline(
                llm=self._llm_client,
                budget=budget,
                prompt_loader=self._prompt_loader,
                event_bus=self._event_bus,
                settings=self._settings,
                spacy=spacy_extractor,
                vector_repo=self.vector_repo(),
                article_repo=self.article_repo(),
                graph_writer=self.graph_writer(),
                source_auth_repo=self.source_authority_repo(),
                entity_resolver=self.entity_resolver(),
                cache_client=self._cache_client,
                community_updater=(
                    self.community_updater() if self.graph_pool() is not None else None
                ),
                relation_type_normalizer=self.relation_normalizer(),
            )
            log.info("pipeline_initialized")
        return self._pipeline

    def pipeline(self) -> Pipeline:
        """Get the processing pipeline."""
        if self._pipeline is None:
            raise RuntimeError("Pipeline not initialized. Call init_pipeline() first.")
        return self._pipeline

    def processing_queue(self) -> Any:
        """Get the processing queue (Redis-backed FIFO with soft backpressure)."""
        if self._processing_queue is None:
            from modules.processing.queue import ProcessingQueue

            self._processing_queue = ProcessingQueue(self._cache_client)
        return self._processing_queue

    def pipeline_worker(self) -> Any | None:
        """Get the pipeline worker (background consumer)."""
        if self._pipeline_worker is None and self._pipeline is not None:
            from modules.processing.worker import PipelineWorker

            self._pipeline_worker = PipelineWorker(
                queue=self.processing_queue(),
                pipeline=self._pipeline,
                article_repo=self.article_repo(),
                pipeline_settings=self._settings.pipeline_process,
            )
        return self._pipeline_worker

    def pipeline_service(self) -> PipelineServiceImpl:
        """Get the pipeline service with stable public interface."""
        from core.services.pipeline_service import PipelineServiceImpl

        if self._pipeline_service is None:
            if self._pipeline is None:
                raise RuntimeError("Pipeline not initialized. Call init_pipeline() first.")
            self._pipeline_service = PipelineServiceImpl(self._pipeline)
        return self._pipeline_service

    def task_registry(self) -> InMemoryTaskRegistry:
        """Get the task registry."""
        from core.services.task_registry import InMemoryTaskRegistry

        if self._task_registry is None:
            self._task_registry = InMemoryTaskRegistry()
        return self._task_registry

    def _get_embedding_model_id(self) -> str:
        """Get embedding model ID from configuration.

        Delegates to core.utils.model_id.extract_embedding_model_id.
        """
        from core.utils.model_id import extract_embedding_model_id

        return extract_embedding_model_id(self._settings.llm)
