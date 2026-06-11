# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Lifecycle management for the container — startup and shutdown orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.constants import DatabaseType, HealthCheckStatus
from core.utils.paths import PROJECT_ROOT
from modules.analytics import LLMUsageBuffer

if TYPE_CHECKING:
    from config.settings import Settings
    from core.llm import LLMClient
    from core.services.pipeline_service import PipelineServiceImpl
    from core.services.task_registry import InMemoryTaskRegistry
    from modules.ingestion import SourceScheduler
    from modules.processing.pipeline.graph import Pipeline


# Module-level event handlers (must be importable by startup())
async def _handle_llm_failure_async(event: Any, repo: Any) -> None:
    """Async handler for LLMFailureEvent."""
    from core.observability import get_logger

    log = get_logger(__name__)
    try:
        await repo.record(event)
    except Exception as exc:
        log.error(
            "llm_failure_handler_error",
            call_point=event.call_point,
            provider=event.provider,
            error=str(exc),
            exc_info=True,
        )


async def _handle_llm_usage_metrics(event: Any) -> None:
    """Async handler for LLMUsageEvent — updates Prometheus token metrics."""
    from core.observability import get_logger

    log = get_logger(__name__)
    try:
        from core.observability.metrics import metrics

        labels = {"provider": event.provider, "model": event.model, "call_point": event.call_point}
        metrics.llm_token_input_total.labels(**labels).inc(event.tokens.input_tokens)
        metrics.llm_token_output_total.labels(**labels).inc(event.tokens.output_tokens)
        metrics.llm_token_total.labels(**labels).inc(event.tokens.total_tokens)
    except Exception as exc:
        log.error(
            "llm_usage_metrics_handler_error",
            label=event.label,
            call_point=event.call_point,
            error=str(exc),
            exc_info=True,
        )


class ContainerLifecycleMixin:
    """Lifecycle management mixin — startup/shutdown orchestration."""

    # ── Private attributes (defined in Container.__init__) ─────────
    _settings: Settings | None
    _strategy: Any
    _cache_client: Any
    _llm_client: LLMClient | None
    _prompt_loader: Any
    _source_scheduler: SourceScheduler | None
    _pipeline: Pipeline | None
    _pipeline_service: PipelineServiceImpl | None
    _task_registry: InMemoryTaskRegistry | None
    _event_bus: Any
    _llm_usage_buffer: LLMUsageBuffer | None
    _llm_usage_repo: Any
    _llm_experience: Any
    _live_config: Any
    _smart_router: Any
    _eval_runner: Any
    _eval_compare_buffer: Any
    _scheduler: Any
    _memory_service: Any
    _shutdown: bool
    _graph_writer: Any
    _causal_repo: Any
    _causal_inference_service: Any
    _conflict_detector: Any
    _shift_detector: Any
    _briefing_engine: Any

    # ── LLM Init (used by startup) ─────────────────────────────

    async def init_llm(self) -> LLMClient:
        """Initialize LLM client with smart routing support."""
        from core.event import EventBus
        from core.llm import LLMClient
        from core.observability import get_logger

        log = get_logger(__name__)

        if self._llm_client is None:
            if self._event_bus is None:
                self._event_bus = EventBus()
                log.info("event_bus_created_in_llm", event_bus_id=id(self._event_bus))

            from core.llm.evaluation.experience import ExperienceStore

            self._llm_experience = ExperienceStore(event_bus=self._event_bus)
            log.info("llm_experience_initialized")

            circuit_breakers: dict[str, Any] = {}

            from core.llm.routing.smart_router import SmartRouter

            self._smart_router = SmartRouter(
                settings=self._settings.llm,
                experience=self._llm_experience,
                circuit_breakers=circuit_breakers,
            )
            log.info("llm_smart_router_initialized")

            from core.llm.config.live_config import LiveConfig

            llm_toml_path = PROJECT_ROOT / "config" / "llm.toml"
            self._live_config = LiveConfig(config_path=llm_toml_path)
            log.info("llm_live_config_initialized", path=str(llm_toml_path))

            eval_cfg = self._settings.llm.eval_config
            if eval_cfg and eval_cfg.enabled:
                from core.llm.evaluation.eval_runner import EvalRunner

                self._eval_runner = EvalRunner.from_eval_config(
                    eval_cfg=eval_cfg, llm_client=None, event_bus=self._event_bus
                )
                log.info("llm_eval_runner_initialized")

            self._llm_client = await LLMClient.create_from_settings(
                llm_settings=self._settings.llm,
                prompt_loader=self.prompt_loader(),
                cache_client=self._cache_client,
                event_bus=self._event_bus,
            )
            self._llm_client._smart_router = self._smart_router
            if self._eval_runner:
                self._eval_runner._llm_client = self._llm_client
                self._llm_client._eval_runner = self._eval_runner
            log.info("llm_client_initialized_with_smart_routing")
        return self._llm_client

    def llm_client(self) -> LLMClient:
        """Return the LLM client instance."""
        if self._llm_client is None:
            raise RuntimeError("LLM client not initialized. Call init_llm() first.")
        return self._llm_client

    # ── Knowledge Cache ─────────────────────────────────────────

    async def init_knowledge_cache(self) -> Any:
        """Initialize the knowledge cache."""
        from core.observability import get_logger
        from modules.knowledge.cache import KnowledgeCache

        log = get_logger(__name__)
        if self._knowledge_cache is None:
            if self._llm_client is None:
                await self.init_llm()
            self._knowledge_cache = KnowledgeCache(
                cache_path=self._settings.knowledge_cache.path,
                llm_client=self._llm_client,
                sync_interval=self._settings.knowledge_cache.sync_interval,
                sync_threshold=self._settings.knowledge_cache.sync_threshold,
                max_queries=self._settings.knowledge_cache.max_queries,
            )
            log.info("knowledge_cache_initialized", path=self._settings.knowledge_cache.path)
        return self._knowledge_cache

    def knowledge_cache(self) -> Any:
        """Return the knowledge cache instance."""
        if self._knowledge_cache is None:
            raise RuntimeError(
                "Knowledge cache not initialized. Call init_knowledge_cache() first."
            )
        return self._knowledge_cache

    # ── MC Sampler ─────────────────────────────────────────────

    async def init_mc_sampler(self) -> Any:
        """Initialize the Monte Carlo sampler."""
        from core.evidence import MCSampler
        from core.observability import get_logger

        log = get_logger(__name__)
        if self._mc_sampler is None:
            if self._llm_client is None:
                await self.init_llm()
            mc_config = self._settings.pipeline.monte_carlo
            if mc_config.enabled:
                self._mc_sampler = MCSampler(
                    llm_client=self._llm_client,
                    token_budget_manager=None,
                    threshold=mc_config.threshold,
                    sample_size=mc_config.sample_size,
                    region_size=mc_config.region_size,
                    confidence_threshold=mc_config.confidence_threshold,
                )
                log.info(
                    "mc_sampler_initialized",
                    threshold=mc_config.threshold,
                    sample_size=mc_config.sample_size,
                )
        return self._mc_sampler

    def mc_sampler(self) -> Any:
        """Return the MC sampler instance."""
        if self._mc_sampler is None and self._settings.pipeline.monte_carlo.enabled:
            raise RuntimeError("MC sampler not initialized. Call init_mc_sampler() first.")
        return self._mc_sampler

    # ── Scheduler Setup ────────────────────────────────────────

    def _setup_scheduler(self) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        from core.observability import get_logger

        log = get_logger(__name__)

        settings = self._settings.scheduler
        if not settings.enabled:
            log.info("scheduler_disabled")
            return

        scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": settings.misfire_grace_time_seconds,
                "coalesce": True,
                "max_instances": 1,
            }
        )
        self._scheduler = scheduler
        jobs = self.scheduler_job_runner()

        # Data Sync
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

        # Cleanup
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

        # Archive (weekly, conditional on Neo4j)
        if self._graph_writer is not None:
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

        # Pipeline Retry
        scheduler.add_job(
            jobs.retry_pipeline_processing,
            IntervalTrigger(minutes=settings.pipeline_retry_interval_minutes),
            id="retry_pipeline_processing",
            name="Retry failed pipeline processing",
            max_instances=1,
            coalesce=True,
        )

        # Pipeline B — Enrichment (PG_DONE → NEO4J_DONE)
        scheduler.add_job(
            jobs.process_pending_enrichment,
            IntervalTrigger(minutes=settings.enrichment_interval_minutes),
            id="process_pending_enrichment",
            name="Process pending enrichment (Pipeline B)",
            max_instances=1,
            coalesce=True,
        )

        # Crawl Retry
        scheduler.add_job(
            jobs.flush_retry_queue,
            IntervalTrigger(seconds=settings.retry_flush_interval_seconds),
            id="flush_retry_queue",
            name="Flush expired crawl retry queue",
            max_instances=1,
            coalesce=True,
        )

        # LLM Usage Aggregation
        scheduler.add_job(
            jobs.aggregate_llm_usage,
            IntervalTrigger(minutes=settings.llm_usage_aggregate_interval_minutes),
            id="llm_usage_aggregate",
            name="LLM usage aggregation (Redis to PG)",
            max_instances=1,
            coalesce=True,
        )

        # LLM Comparison Aggregation
        scheduler.add_job(
            jobs.aggregate_llm_compare,
            IntervalTrigger(minutes=settings.llm_usage_aggregate_interval_minutes),
            id="llm_compare_aggregate",
            name="LLM comparison aggregation (Redis to PG)",
            max_instances=1,
            coalesce=True,
        )

        # PhishTank Sync
        scheduler.add_job(
            jobs.sync_phishtank_data,
            IntervalTrigger(hours=settings.sync_phishtank_interval_hours),
            id="sync_phishtank_data",
            name="Sync PhishTank phishing URL data",
            max_instances=1,
            coalesce=True,
        )

        # API Key Rotation Check
        scheduler.add_job(
            jobs.check_expiring_api_keys,
            CronTrigger(hour=2, minute=0),
            id="check_expiring_api_keys",
            name="Check and rotate expiring API keys",
            max_instances=1,
        )

        # Source Scoring
        scheduler.add_job(
            jobs.update_source_auto_scores,
            CronTrigger(hour=settings.source_auto_score_cron_hour),
            id="update_source_auto_scores",
            name="Update source authority scores",
            max_instances=1,
        )

        # Community Detection
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
        else:
            # LadybugDB fallback: use detector directly
            graph_pool = self.graph_pool()
            if graph_pool is not None:
                from core.db.graph_query_builders import GraphDatabaseType
                from modules.knowledge.graph.community.detector import CommunityDetector

                detector = CommunityDetector(
                    pool=graph_pool,
                    max_cluster_size=10,
                    database_type=GraphDatabaseType.LADYBUG,
                    llm_client=self.llm_client(),
                )

                async def _ladybug_community_check() -> dict[str, object]:
                    try:
                        result = await detector.rebuild_communities()
                        log.info(
                            "ladybug_community_detection_complete",
                            communities=result.total_communities,
                            modularity=result.modularity,
                        )
                        return {"communities": result.total_communities}
                    except Exception as exc:
                        log.error("ladybug_community_detection_failed", error=str(exc))
                        return {"error": str(exc)}

                scheduler.add_job(
                    _ladybug_community_check,
                    IntervalTrigger(minutes=settings.community_check_interval_minutes),
                    id="community_auto_check",
                    name="LadybugDB community detection",
                    max_instances=1,
                    coalesce=True,
                )

        # Community Health Check
        if self.graph_pool() is not None:
            scheduler.add_job(
                self._community_health_check,
                IntervalTrigger(hours=6),
                id="community_health_check",
                name="Community health check and auto repair",
                max_instances=1,
                coalesce=True,
            )

        # Metrics
        scheduler.add_job(
            jobs.update_persist_status_metrics,
            IntervalTrigger(minutes=settings.persist_status_metrics_interval_minutes),
            id="update_persist_status_metrics",
            name="Update persist status Prometheus metrics",
            max_instances=1,
            coalesce=True,
        )

        # Memory Consolidation
        if self._memory_service is not None:
            scheduler.add_job(
                self._memory_service.consolidate,
                IntervalTrigger(minutes=self._settings.memory.consolidation_interval_minutes),
                id="memory_consolidation",
                name="Memory slow path consolidation",
                max_instances=1,
                coalesce=True,
            )

        # Analytics - Daily Briefing Generation
        from zoneinfo import ZoneInfo

        scheduler.add_job(
            jobs.generate_daily_briefing,
            CronTrigger(hour=7, minute=0, timezone=ZoneInfo("Asia/Shanghai")),
            id="daily_briefing_generation",
            name="Generate daily intelligence briefing",
            max_instances=1,
            coalesce=True,
        )

        # Analytics - Sentiment Shift Detection
        scheduler.add_job(
            jobs.detect_sentiment_shifts,
            IntervalTrigger(minutes=60),
            id="shift_detection",
            name="Detect sentiment shifts",
            max_instances=1,
            coalesce=True,
        )

        # Startup: run sync once immediately
        scheduler.add_job(
            jobs.sync_pending_to_neo4j,
            DateTrigger(),
            id="startup_sync_pending_to_neo4j",
            replace_existing=True,
        )

        scheduler.start()
        log.info("scheduler_started", jobs=len(scheduler.get_jobs()))

    # ── Community Health Check ─────────────────────────────────

    async def _community_health_check(self) -> dict[str, object]:
        from core.observability import get_logger
        from modules.knowledge.graph.community.health.checker import CommunityHealthChecker
        from modules.knowledge.graph.community.health.models import CommunityHealthStatus
        from modules.knowledge.graph.community.repair_service import CommunityRepairService

        log = get_logger(__name__)
        log.info("community_health_check_start")

        graph_pool = self.graph_pool()
        if graph_pool is None:
            return {"status": "skipped", "reason": "no_graph_pool"}

        try:
            checker = CommunityHealthChecker(graph_pool)
            report = await checker.diagnose_all()

            if report.status in (CommunityHealthStatus.DEGRADED, CommunityHealthStatus.CRITICAL):
                log.warning(
                    "community_health_check_issues_found",
                    status=report.status.value,
                    issues=len(report.issues),
                )
                repair_service = CommunityRepairService(graph_pool)
                repairable = [i for i in report.issues if i.auto_repairable]
                if repairable:
                    repair_result = await repair_service.auto_repair(repairable)
                    log.info(
                        "community_health_check_repair_complete",
                        repaired=repair_result.total_repaired,
                    )
                    return {
                        "status": report.status.value,
                        "score": report.score,
                        "repaired": repair_result.to_dict(),
                    }

            log.info(
                "community_health_check_complete", status=report.status.value, score=report.score
            )
            return {
                "status": report.status.value,
                "score": report.score,
                "issues_count": len(report.issues),
            }
        except Exception as exc:
            log.error("community_health_check_failed", error=str(exc))
            return {"status": HealthCheckStatus.ERROR.value, "error": str(exc)}

    # ── Memory Service ─────────────────────────────────────────

    @property
    def memory_service(self) -> Any | None:
        """Return the memory service."""
        return self._memory_service

    async def init_memory_service(self) -> Any | None:
        """Initialize the memory service."""
        from core.observability import get_logger
        from modules.knowledge.search.intent.classifier import IntentClassifier
        from modules.memory.integration.memory_service import (
            MemoryIntegrationService,
            MemoryServiceConfig,
        )

        log = get_logger(__name__)

        if self._memory_service is not None:
            return self._memory_service

        if self.graph_pool() is None or self._llm_client is None or self._cache_client is None:
            log.info("memory_service_skipped_missing_deps")
            return None

        try:
            memory_settings = self._settings.memory
            temporal_settings = self._settings.temporal_memory
            config = MemoryServiceConfig(
                fast_path_enabled=memory_settings.fast_path_enabled,
                slow_path_enabled=memory_settings.slow_path_enabled,
                causal_confidence_threshold=memory_settings.causal_confidence_threshold,
                consolidation_batch_size=memory_settings.consolidation_batch_size,
                max_traversal_depth=memory_settings.max_traversal_depth,
                beam_width=memory_settings.beam_width,
                token_budget=memory_settings.token_budget,
                why_anchor_limit=temporal_settings.why_anchor_limit,
                when_anchor_limit=temporal_settings.when_anchor_limit,
                default_anchor_limit=temporal_settings.default_anchor_limit,
                event_lookup_limit=temporal_settings.event_lookup_limit,
            )

            intent_classifier = IntentClassifier(self._llm_client)

            class EmbeddingServiceWrapper:
                def __init__(self, llm_client: Any) -> None:
                    self._llm = llm_client

                async def embed(self, text: str) -> list[float]:
                    embeddings = await self._llm.embed_default([text])
                    return embeddings[0]

            embedding_service = EmbeddingServiceWrapper(self._llm_client)

            # Get embedding model ID from configuration
            embedding_model = self._get_embedding_model_id()

            self._memory_service = MemoryIntegrationService(
                graph_pool=self.graph_pool(),
                llm_client=self._llm_client,
                cache=self._cache_client,
                embedding_service=embedding_service,
                intent_classifier=intent_classifier,
                config=config,
                vector_repo=self.vector_repo(),
                entity_repo=self.graph_entity_repo(),
                embedding_model=embedding_model,
            )

            await self._memory_service.initialize()
            self._setup_memory_event_handler()
            log.info("memory_service_initialized")
            return self._memory_service
        except Exception as exc:
            log.error("memory_service_init_failed", error=str(exc))
            return None

    async def init_causal_inference_service(self) -> Any | None:
        """Initialize the causal inference service.

        Requires graph pool, LLM client, and causal repo to be available.

        Returns:
            CausalInferenceService instance or None if dependencies unavailable.

        """
        from core.observability import get_logger
        from modules.memory.causal import CausalInferenceService, InferenceConfig

        log = get_logger(__name__)

        if self._causal_inference_service is not None:
            return self._causal_inference_service

        graph_pool = self.graph_pool()
        if graph_pool is None or self._llm_client is None:
            log.info("causal_inference_service_skipped_missing_deps")
            return None

        try:
            # Get causal repo
            causal_repo = self.causal_repo()
            if causal_repo is None:
                log.info("causal_inference_service_skipped_no_repo")
                return None

            # Create config from settings
            config = InferenceConfig(
                batch_size=self._settings.pipeline_process.worker_batch_size,
                confidence_threshold=self._settings.memory.causal_confidence_threshold,
                max_relations_per_entity=self._settings.memory.max_relations_per_entity,
                llm_timeout_seconds=self._settings.pipeline_process.drain_timeout,
                enable_parallel_inference=True,
            )

            self._causal_inference_service = CausalInferenceService(
                pool=graph_pool,
                llm_client=self._llm_client,
                causal_repo=causal_repo,
                config=config,
            )
            log.info("causal_inference_service_initialized")
            return self._causal_inference_service

        except Exception as exc:
            log.error("causal_inference_service_init_failed", error=str(exc))
            return None

    # ── Conflict Detector ──────────────────────────────────────────

    async def init_conflict_detector(self) -> Any | None:
        """Initialize conflict detector node."""
        from core.observability import get_logger
        from modules.processing.nodes.quality.conflict_detector import ConflictDetectorNode

        log = get_logger(__name__)
        if self._conflict_detector is not None:
            return self._conflict_detector

        try:
            article_repo = self.article_repo()
            self._conflict_detector = ConflictDetectorNode(article_repo=article_repo)
            log.info("conflict_detector_initialized")
            return self._conflict_detector
        except Exception as exc:
            log.warning("conflict_detector_init_failed", error=str(exc))
            return None

    def conflict_detector(self) -> Any | None:
        """Return the conflict detector instance."""
        return self._conflict_detector

    # ── Shift Detector ──────────────────────────────────────────

    async def init_shift_detector(self) -> Any | None:
        """Initialize sentiment shift detector."""
        from core.observability import get_logger
        from modules.analytics.shift_detector import SentimentShiftDetector, ShiftConfig

        log = get_logger(__name__)
        if self._shift_detector is not None:
            return self._shift_detector

        try:
            config = ShiftConfig()
            self._shift_detector = SentimentShiftDetector(config=config)
            log.info("shift_detector_initialized")
            return self._shift_detector
        except Exception as exc:
            log.warning("shift_detector_init_failed", error=str(exc))
            return None

    def shift_detector(self) -> Any | None:
        """Return the shift detector instance."""
        return self._shift_detector

    # ── Briefing Engine ──────────────────────────────────────────

    async def init_briefing_engine(self) -> Any | None:
        """Initialize daily briefing engine."""
        from core.observability import get_logger
        from modules.briefing.engine import DailyBriefingEngine

        log = get_logger(__name__)
        if self._briefing_engine is not None:
            return self._briefing_engine

        try:
            pool = self.relational_pool()
            self._briefing_engine = DailyBriefingEngine(pool=pool)
            log.info("briefing_engine_initialized")
            return self._briefing_engine
        except Exception as exc:
            log.warning("briefing_engine_init_failed", error=str(exc))
            return None

    def briefing_engine(self) -> Any | None:
        """Return the briefing engine instance."""
        return self._briefing_engine

    def _setup_memory_event_handler(self) -> None:
        from core.event.bus import MemoryIngestEvent
        from core.observability import get_logger

        log = get_logger(__name__)

        async def handle_memory_ingest(event: MemoryIngestEvent) -> None:
            if self._memory_service is None:
                log.debug("memory_service_unavailable_skipping_ingest")
                return
            try:
                await self._memory_service.ingest(event.state)
                log.info("memory_ingest_complete", article_id=event.article_id)
            except Exception as e:
                log.warning("memory_ingest_failed", article_id=event.article_id, error=str(e))

        self._event_bus.subscribe(MemoryIngestEvent, handle_memory_ingest)
        log.info("memory_event_handler_registered")

    # ── Startup & Shutdown ──────────────────────────────────────

    async def startup(self) -> None:
        """Initialize all services and start background tasks."""
        from core.event import LLMFailureEvent, LLMUsageEvent
        from core.observability import get_logger
        from modules.analytics.llm_failure.repo import LLMFailureRepo
        from modules.ingestion.domain.processor import DiscoveryProcessor

        log = get_logger(__name__)
        log.info("container_starting")

        await self.init_strategy()

        if self._strategy is not None and self._strategy.relational_type == DatabaseType.POSTGRES:
            from core.db.initializer import initialize_database

            await initialize_database(
                self._settings.postgres.dsn,
                alembic_ini_path=str(PROJECT_ROOT / "alembic.ini"),
                script_location=str(PROJECT_ROOT / "src" / "alembic"),
            )

        await self.init_cache_client()
        await self.init_llm()
        self.init_search_engines()
        await self._init_bm25_index()
        await self.init_smart_fetcher()

        processor = DiscoveryProcessor(
            crawler=self.crawler(),
            article_repo=self.article_repo(),
            deduplicator=self.deduplicator(),
            processing_queue=self.processing_queue(),
        )
        await self.init_source_scheduler(processor.on_items_discovered)

        await self.init_pipeline()
        worker = self.pipeline_worker()
        if worker:
            await worker.start()
            log.info("pipeline_worker_started")

        await self.init_memory_service()

        # LLM failure logging
        self._llm_failure_repo = LLMFailureRepo(self.relational_pool())
        self._event_bus.subscribe(
            LLMFailureEvent, lambda e: _handle_llm_failure_async(e, self._llm_failure_repo)
        )
        log.info("llm_failure_logging_initialized", event_bus_id=id(self._event_bus))

        # LLM usage metrics
        self._event_bus.subscribe(LLMUsageEvent, _handle_llm_usage_metrics)
        log.info("llm_usage_metrics_subscribed", event_bus_id=id(self._event_bus))

        # LLM usage statistics
        self._llm_usage_buffer = LLMUsageBuffer(
            cache=self._cache_client,
            ttl_seconds=self._settings.scheduler.llm_usage_redis_buffer_ttl_seconds,
        )

        async def _handle_llm_usage_buffer(event: LLMUsageEvent) -> None:
            if self._llm_usage_buffer:
                await self._llm_usage_buffer.accumulate(event)

        async def _handle_llm_usage_raw(event: LLMUsageEvent) -> None:
            try:
                from core.db.duckdb_pool import DuckDBPool
                from modules.storage.duckdb import DuckDBLLMUsageRepo

                pool = self.relational_pool()
                if isinstance(pool, DuckDBPool):
                    repo = DuckDBLLMUsageRepo(pool)
                else:
                    # Reuse cached repo instance from container
                    repo = self.llm_usage_repo()
                await repo.insert_raw(event)
            except Exception as e:
                log.error(
                    "llm_usage_raw_insert_failed", error=str(e), label=event.label, exc_info=True
                )

        self._event_bus.subscribe(LLMUsageEvent, _handle_llm_usage_buffer)
        self._event_bus.subscribe(LLMUsageEvent, _handle_llm_usage_raw)
        log.info("llm_usage_handlers_subscribed", event_bus_id=id(self._event_bus))

        # LLM comparison buffer and handlers
        from core.event.bus import LLMCompareEvent
        from modules.analytics.llm_compare.buffer import EvalCompareBuffer
        from modules.analytics.llm_compare.repo import EvalCompareRepo

        self._eval_compare_buffer = EvalCompareBuffer(cache=self._cache_client, ttl_seconds=86400)

        async def _handle_eval_compare_buffer(event: LLMCompareEvent) -> None:
            if self._eval_compare_buffer:
                await self._eval_compare_buffer.accumulate(event)

        async def _handle_eval_compare_raw(event: LLMCompareEvent) -> None:
            repo = EvalCompareRepo(self.relational_pool())
            await repo.insert_raw(event)

        self._event_bus.subscribe(LLMCompareEvent, _handle_eval_compare_buffer)
        self._event_bus.subscribe(LLMCompareEvent, _handle_eval_compare_raw)
        log.info("llm_compare_handlers_subscribed", event_bus_id=id(self._event_bus))

        _ = self.pending_sync_repo()

        # Initialize new modules
        await self.init_conflict_detector()
        await self.init_shift_detector()
        await self.init_briefing_engine()

        self._setup_scheduler()

        # Register endpoints dependencies (required for API endpoints to work)
        from api.endpoints.deps_registry import Endpoints

        Endpoints.initialize(self)
        log.info("endpoints_registered")

        if self._live_config:
            try:
                await self._live_config.start(on_reload=self._on_llm_config_reload)
                log.info("live_config_watcher_started")
            except Exception as e:
                log.error("live_config_watcher_start_failed", error=str(e), exc_info=True)

        log.info("container_started")

    async def shutdown(self) -> None:
        """Clean up resources and stop background tasks."""
        from core.observability import get_logger

        log = get_logger(__name__)

        if self._shutdown:
            log.debug("shutdown_already_called")
            return

        self._shutdown = True
        log.info("container_shutting_down")

        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            log.info("main_scheduler_stopped")

        if self._source_scheduler:
            self._source_scheduler.stop()
            log.info("source_scheduler_stopped")

        worker = self.pipeline_worker()
        if worker:
            await worker.stop()
            log.info("pipeline_worker_stopped")

        if self._llm_client:
            try:
                queue_manager = getattr(self._llm_client, "_queue_manager", None)
                if queue_manager:
                    await queue_manager.shutdown()
                    log.info("llm_queue_manager_stopped")
            except Exception as e:
                log.error("llm_queue_manager_shutdown_error", error=str(e), exc_info=True)

        if self._live_config:
            try:
                await self._live_config.stop()
                log.info("live_config_watcher_stopped")
            except Exception as e:
                log.error("live_config_watcher_stop_error", error=str(e), exc_info=True)

        if self._smart_fetcher:
            await self._smart_fetcher.close()
            log.info("smart_fetcher_shutdown")

        if self._cache_client:
            await self._cache_client.shutdown()
            log.info("cache_client_shutdown")

        if self._strategy is not None:
            await self._strategy.relational_pool.shutdown()
            log.info("relational_pool_shutdown", type=self._strategy.relational_type)
            if self._strategy.graph_pool is not None:
                await self._strategy.graph_pool.shutdown()
                log.info("graph_pool_shutdown", type=self._strategy.graph_type)

        log.info("container_shutdown_complete")

    async def _on_llm_config_reload(self, new_config: Any) -> None:
        from core.llm.routing.smart_router import SmartRouter
        from core.observability import get_logger

        log = get_logger(__name__)

        try:
            log.info("llm_config_reload_starting")
            self._settings.llm = new_config

            if self._smart_router and self._llm_experience:
                circuit_breakers = self._smart_router._circuit_breakers
                self._smart_router = SmartRouter(
                    settings=new_config,
                    experience=self._llm_experience,
                    circuit_breakers=circuit_breakers,
                )
                if self._llm_client:
                    self._llm_client._smart_router = self._smart_router
                log.info("llm_config_reload_complete")
        except Exception as e:
            log.error("llm_config_reload_failed", error=str(e))

    def _get_embedding_model_id(self) -> str:
        """Get embedding model ID from configuration.

        Delegates to core.utils.model_id.extract_embedding_model_id.
        """
        from core.utils.model_id import extract_embedding_model_id

        return extract_embedding_model_id(self._settings.llm)
