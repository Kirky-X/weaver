# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LangGraph main pipeline flow definition.

This module provides the main processing pipeline with support for both
hardcoded nodes and configuration-driven initialization.

Usage:
    # Hardcoded (backward compatible)
    pipeline = Pipeline(llm, budget, prompt_loader, event_bus)

    # Configuration-driven (new)
    from modules.pipeline.config import PipelineConfigLoader
    config = PipelineConfigLoader().load_with_env_override()
    pipeline = Pipeline.from_config(llm, config, ...)
"""

from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Any

from core.db.models import PersistStatus
from core.event.bus import EventBus
from core.llm.client import LLMClient
from core.llm.token_budget import TokenBudgetManager
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from core.prompt.loader import PromptLoader
from modules.collector.models import ArticleRaw
from modules.graph_store.entity_resolver import EntityResolver
from modules.nlp.spacy_extractor import SpacyExtractor
from modules.pipeline.nodes.analyze import AnalyzeNode
from modules.pipeline.nodes.batch_merger import BatchMergerNode
from modules.pipeline.nodes.categorizer import CategorizerNode
from modules.pipeline.nodes.checkpoint_cleanup import CheckpointCleanupNode
from modules.pipeline.nodes.classifier import ClassifierNode
from modules.pipeline.nodes.cleaner import CleanerNode
from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode
from modules.pipeline.nodes.entity_extractor import EntityExtractorNode
from modules.pipeline.nodes.quality_scorer import QualityScorerNode
from modules.pipeline.nodes.re_vectorize import ReVectorizeNode
from modules.pipeline.nodes.vectorize import VectorizeNode
from modules.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.protocols import ArticleRepository, VectorRepository
    from modules.graph_store.neo4j_writer import Neo4jWriter
    from modules.pipeline.config import PipelineConfig
    from modules.source.source_authority_repo import SourceAuthorityRepo

log = get_logger("pipeline")

# Processing stages
PHASE1_STAGES = {
    "classifier": "phase1_classifier",
    "cleaner": "phase1_cleaner",
    "categorizer": "phase1_categorizer",
    "vectorize": "phase1_vectorize",
}
PHASE3_STAGES = {
    "re_vectorize": "phase3_re_vectorize",
    "analyze": "phase3_analyze",
    "quality_scorer": "phase3_quality_scorer",
    "credibility": "phase3_credibility",
    "entity_extractor": "phase3_entity_extractor",
}


class Pipeline:
    """Main news processing pipeline.

    Orchestrates the full article processing flow:
    1. Classifier → Cleaner → Categorizer → Vectorize (concurrent per article)
    2. Batch Merger (serial across batch)
    3. Re-vectorize → Analyze → Credibility → Entity extraction (concurrent)
    4. Persist → Cleanup
    """

    # Default concurrency limits for LLM processing
    DEFAULT_PHASE1_CONCURRENCY = 5  # Concurrent processing for cloud LLM APIs
    DEFAULT_PHASE3_CONCURRENCY = 5  # Same for post-merge processing

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        event_bus: EventBus,
        spacy: SpacyExtractor | None = None,
        vector_repo: VectorRepository | None = None,
        article_repo: ArticleRepository | None = None,
        neo4j_writer: Neo4jWriter | None = None,
        source_auth_repo: SourceAuthorityRepo | None = None,
        entity_resolver: EntityResolver | None = None,
        redis_client: Any = None,
        phase1_concurrency: int | None = None,
        phase3_concurrency: int | None = None,
    ) -> None:
        self._accepting = True

        # Concurrency limits - default to 1 for Ollama compatibility
        self._phase1_concurrency = phase1_concurrency or self.DEFAULT_PHASE1_CONCURRENCY
        self._phase3_concurrency = phase3_concurrency or self.DEFAULT_PHASE3_CONCURRENCY

        # Semaphores for concurrency control
        self._phase1_semaphore = asyncio.Semaphore(self._phase1_concurrency)
        self._phase3_semaphore = asyncio.Semaphore(self._phase3_concurrency)

        log.info(
            "pipeline_init",
            phase1_concurrency=self._phase1_concurrency,
            phase3_concurrency=self._phase3_concurrency,
        )

        # Initialize nodes
        self._classifier = ClassifierNode(llm, budget, prompt_loader)
        self._cleaner = CleanerNode(llm, budget, prompt_loader)
        self._categorizer = CategorizerNode(llm, prompt_loader)
        self._vectorize = VectorizeNode(llm)
        self._batch_merger = BatchMergerNode(llm, prompt_loader, vector_repo)
        self._re_vectorize = ReVectorizeNode(llm)
        self._analyze = AnalyzeNode(llm, budget, prompt_loader)
        self._quality_scorer = QualityScorerNode(llm, budget, prompt_loader)
        self._credibility = CredibilityCheckerNode(llm, budget, event_bus, source_auth_repo)
        self._entity_extractor = EntityExtractorNode(
            llm, budget, prompt_loader, spacy or SpacyExtractor(), vector_repo
        )
        self._entity_resolver = entity_resolver
        self._checkpoint_cleanup = CheckpointCleanupNode(redis_client)
        self._article_repo = article_repo
        self._neo4j_writer = neo4j_writer
        self._vector_repo = vector_repo

    @classmethod
    def from_config(
        cls,
        llm: LLMClient,
        config: PipelineConfig,
        budget: TokenBudgetManager | None = None,
        prompt_loader: PromptLoader | None = None,
        event_bus: EventBus | None = None,
        spacy: SpacyExtractor | None = None,
        vector_repo: VectorRepository | None = None,
        article_repo: ArticleRepository | None = None,
        neo4j_writer: Neo4jWriter | None = None,
        source_auth_repo: SourceAuthorityRepo | None = None,
        entity_resolver: EntityResolver | None = None,
        redis_client: Any = None,
    ) -> Pipeline:
        """Create a Pipeline instance from configuration.

        This factory method allows the pipeline to be configured via external
        YAML/JSON files, enabling runtime adjustments without code changes.

        Args:
            llm: LLM client instance.
            config: Pipeline configuration object.
            budget: Token budget manager. Created if not provided.
            prompt_loader: Prompt loader. Created if not provided.
            event_bus: Event bus. Created if not provided.
            spacy: spaCy extractor. Created if not provided.
            vector_repo: Vector repository.
            article_repo: Article repository.
            neo4j_writer: Neo4j writer.
            source_auth_repo: Source authority repository.
            entity_resolver: Entity resolver.
            redis_client: Redis client for checkpoint cleanup.

        Returns:
            Configured Pipeline instance.

        Example:
            from modules.pipeline.config import PipelineConfigLoader

            loader = PipelineConfigLoader()
            config = loader.load_with_env_override()
            pipeline = Pipeline.from_config(
                llm=container.llm_client(),
                config=config,
                vector_repo=container.vector_repo(),
                article_repo=container.article_repo(),
            )
        """
        # Initialize default dependencies if not provided
        from core.llm.token_budget import TokenBudgetManager

        budget = budget or TokenBudgetManager()

        from config.settings import Settings
        from core.prompt.loader import PromptLoader

        settings = Settings()
        prompt_loader = prompt_loader or PromptLoader(settings.prompt.dir)

        event_bus = event_bus or EventBus()
        spacy = spacy or SpacyExtractor()

        log.info(
            "pipeline_init_from_config",
            version=config.version,
            phase1_concurrency=config.phase1.concurrency,
            phase3_concurrency=config.phase3.concurrency,
            phase1_stages=len(config.phase1.enabled_stages),
            phase3_stages=len(config.phase3.enabled_stages),
        )

        # Create instance with configuration values
        return cls(
            llm=llm,
            budget=budget,
            prompt_loader=prompt_loader,
            event_bus=event_bus,
            spacy=spacy,
            vector_repo=vector_repo,
            article_repo=article_repo,
            neo4j_writer=neo4j_writer,
            source_auth_repo=source_auth_repo,
            entity_resolver=entity_resolver,
            redis_client=redis_client,
            phase1_concurrency=config.phase1.concurrency,
            phase3_concurrency=config.phase3.concurrency,
        )

    @property
    def config_version(self) -> str | None:
        """Get the pipeline configuration version if available."""
        return getattr(self, "_config_version", None)

    async def _update_processing_stage(self, state: PipelineState, stage: str) -> None:
        """Update the processing stage in the database.

        Args:
            state: Pipeline state containing article_id.
            stage: Current processing stage name.
        """
        if not self._article_repo:
            return

        article_id = state.get("article_id")
        if not article_id:
            return

        try:
            import uuid

            await self._article_repo.update_processing_stage(uuid.UUID(article_id), stage)
        except Exception as e:
            log.warning("failed_to_update_stage", article_id=article_id, error=str(e))

    async def _mark_processing(self, state: PipelineState) -> None:
        """Mark article as processing in the database.

        Args:
            state: Pipeline state.
        """
        if not self._article_repo:
            return

        article_id = state.get("article_id")
        if not article_id:
            return

        try:
            import uuid

            await self._article_repo.mark_processing(uuid.UUID(article_id), "phase1_start")
        except Exception as e:
            log.warning("failed_to_mark_processing", article_id=article_id, error=str(e))

    async def process_batch(
        self,
        articles: list[ArticleRaw],
        article_ids: list[Any] | None = None,
        task_id: Any | None = None,
    ) -> list[PipelineState]:
        """Process a batch of articles through the full pipeline.

        Args:
            articles: List of raw articles to process.
            article_ids: Optional list of article UUIDs aligned with articles list.
            task_id: Optional pipeline task UUID for failure correlation.

        Returns:
            List of completed pipeline states.
        """
        if not self._accepting:
            raise RuntimeError("Pipeline is not accepting new tasks")

        log.info("pipeline_batch_start", batch_size=len(articles))

        # Initialize states with optional article_id and task_id
        states: list[PipelineState] = []
        for i, article in enumerate(articles):
            state = PipelineState(raw=article)
            if article_ids is not None and i < len(article_ids):
                state["article_id"] = str(article_ids[i])
            if task_id is not None:
                state["task_id"] = str(task_id)
            states.append(state)

        # Phase 1: Per-article concurrent nodes
        phase1_tasks = [self._phase1_per_article(state) for state in states]
        states = await asyncio.gather(*phase1_tasks)

        # Phase 2: Batch merger (serial)
        try:
            import time

            start = time.monotonic()
            states = await self._batch_merger.execute_batch(list(states))
            MetricsCollector.pipeline_stage_latency.labels(stage="batch_merger").observe(
                time.monotonic() - start
            )

            # Phase 3: Per-article post-merge nodes (concurrent)
            phase3_tasks = [self._phase3_per_article(state) for state in states]
            states = list(await asyncio.gather(*phase3_tasks))

            # Phase 4: Persist (批量持久化)
            await self._persist_batch(states)

            # Phase 5: Checkpoint cleanup
            cleanup_tasks = [self._checkpoint_cleanup.execute(state) for state in states]
            await asyncio.gather(*cleanup_tasks)

            log.info(
                "pipeline_batch_complete",
                batch_size=len(articles),
                processed=sum(1 for s in states if not s.get("terminal")),
            )
            return states
        except Exception as exc:
            import traceback as tb

            log.error(
                "process_batch_internal_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
                traceback=tb.format_exc(),
            )
            raise

    async def _phase1_per_article(self, state: PipelineState) -> PipelineState:
        """Phase 1: classify → clean → (categorize || vectorize).

        DAG execution:
        - classifier must run first (determines if news)
        - cleaner runs after classifier
        - categorizer and vectorize can run in parallel after cleaner
        """
        async with self._phase1_semaphore:
            import time

            start = time.monotonic()
            state = await self._classifier.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="classifier").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE1_STAGES["classifier"])

            if state.get("terminal"):
                return state

            start = time.monotonic()
            state = await self._cleaner.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="cleaner").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE1_STAGES["cleaner"])

            async def run_categorizer(s: PipelineState) -> PipelineState:
                st = time.monotonic()
                result = await self._categorizer.execute(s)
                MetricsCollector.pipeline_stage_latency.labels(stage="categorizer").observe(
                    time.monotonic() - st
                )
                return result

            async def run_vectorize(s: PipelineState) -> PipelineState:
                st = time.monotonic()
                result = await self._vectorize.execute(s)
                MetricsCollector.pipeline_stage_latency.labels(stage="vectorize").observe(
                    time.monotonic() - st
                )
                return result

            categorizer_task = asyncio.create_task(run_categorizer(state))
            vectorize_task = asyncio.create_task(run_vectorize(state))

            categorizer_state, vectorize_state = await asyncio.gather(
                categorizer_task, vectorize_task
            )

            state.update(categorizer_state)
            state.update(vectorize_state)

            await self._update_processing_stage(state, PHASE1_STAGES["categorizer"])
            await self._update_processing_stage(state, PHASE1_STAGES["vectorize"])

            return state

    async def _phase3_per_article(self, state: PipelineState) -> PipelineState:
        """Phase 3: re-vectorize → (analyze || quality_scorer) → credibility → entity_extraction.

        DAG execution:
        - re_vectorize runs first (updates vectors); skipped for terminal articles
        - analyze and quality_scorer can run in parallel (both only depend on cleaned)
        - credibility depends on analyze.summary_info
        - entity_extractor runs last
        """
        async with self._phase3_semaphore:
            if state.get("is_merged"):
                return state

            import time

            # re_vectorize requires article vectors — skip for terminal (non-news) articles
            if not state.get("terminal"):
                start = time.monotonic()
                state = await self._re_vectorize.execute(state)
                MetricsCollector.pipeline_stage_latency.labels(stage="re_vectorize").observe(
                    time.monotonic() - start
                )
                await self._update_processing_stage(state, PHASE3_STAGES["re_vectorize"])

            async def run_analyze(s: PipelineState) -> PipelineState:
                st = time.monotonic()
                result = await self._analyze.execute(s)
                MetricsCollector.pipeline_stage_latency.labels(stage="analyze").observe(
                    time.monotonic() - st
                )
                return result

            async def run_quality_scorer(s: PipelineState) -> PipelineState:
                st = time.monotonic()
                result = await self._quality_scorer.execute(s)
                MetricsCollector.pipeline_stage_latency.labels(stage="quality_scorer").observe(
                    time.monotonic() - st
                )
                return result

            analyze_task = asyncio.create_task(run_analyze(state))
            quality_task = asyncio.create_task(run_quality_scorer(state))

            analyze_state, quality_state = await asyncio.gather(analyze_task, quality_task)

            state.update(analyze_state)
            state.update(quality_state)

            await self._update_processing_stage(state, PHASE3_STAGES["analyze"])
            await self._update_processing_stage(state, PHASE3_STAGES["quality_scorer"])

            start = time.monotonic()
            state = await self._credibility.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="credibility").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE3_STAGES["credibility"])

            start = time.monotonic()
            state = await self._entity_extractor.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="entity_extractor").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE3_STAGES["entity_extractor"])

            # === 新增: Entity Resolver 阶段 ===
            if state.get("entities") and self._entity_resolver:
                resolved_entities = await self._entity_resolver.resolve_entities_batch(
                    entities=state["entities"]
                )
                state["resolved_entities"] = resolved_entities
                log.debug(
                    "entity_resolver_complete",
                    url=state["raw"].url,
                    resolved_count=len(resolved_entities),
                )

            return state

    async def _persist(self, state: PipelineState) -> None:
        """Persist article to Postgres and Neo4j."""
        if state.get("terminal"):
            return

        if self._article_repo:
            try:
                article_id = await self._article_repo.upsert(state)
                state["article_id"] = str(article_id)
                await self._article_repo.update_persist_status(article_id, PersistStatus.PG_DONE)

                if self._vector_repo and "vectors" in state:
                    vectors = state["vectors"]
                    if isinstance(vectors, dict) and "title" in vectors and "content" in vectors:
                        import uuid

                        await self._vector_repo.upsert_article_vectors(
                            article_id=article_id,
                            title_embedding=vectors.get("title"),
                            content_embedding=vectors.get("content"),
                            model_id=vectors.get("model_id", "unknown"),
                        )
                        log.debug("vectors_persisted", article_id=str(article_id))
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                log.error(
                    "persist_pg_failed",
                    url=state.get("raw", {}).url if "raw" in state else "unknown",
                    error=error_msg,
                    error_type=type(exc).__name__,
                    has_article_id=state.get("article_id") is not None,
                    traceback=traceback.format_exc(),
                )
                if state.get("article_id"):
                    try:
                        import uuid

                        await self._article_repo.mark_failed(
                            uuid.UUID(state["article_id"]), f"PG error: {exc!s}"
                        )
                    except Exception as mark_err:
                        log.warning(
                            "mark_failed_pg_error_failed",
                            article_id=state.get("article_id"),
                            error=str(mark_err),
                        )
                return

        if self._neo4j_writer:
            try:
                neo4j_ids = await self._neo4j_writer.write(state)
                state["neo4j_ids"] = neo4j_ids
                if self._article_repo:
                    await self._article_repo.update_persist_status(
                        state["article_id"], PersistStatus.NEO4J_DONE
                    )
            except Exception as exc:
                log.error(
                    "persist_neo4j_failed",
                    article_id=state.get("article_id"),
                    error=str(exc),
                )
                if state.get("article_id") and self._article_repo:
                    try:
                        import uuid

                        await self._article_repo.mark_failed(
                            uuid.UUID(state["article_id"]), f"Neo4j error: {exc!s}"
                        )
                    except Exception as mark_err:
                        log.warning(
                            "mark_failed_neo4j_error_failed",
                            article_id=state.get("article_id"),
                            error=str(mark_err),
                        )

    async def _persist_batch(self, states: list[PipelineState]) -> None:
        """Persist batch of articles to Postgres and Neo4j.

        Uses bulk operations for better performance.

        Args:
            states: List of pipeline states to persist.
        """
        log.info("persist_batch_called", count=len(states))
        valid_states = [s for s in states if not s.get("terminal")]
        terminal_states = [s for s in states if s.get("terminal")]

        # Handle terminal articles: update persist_status so they don't stay stuck in PENDING
        if terminal_states and self._article_repo:
            for state in terminal_states:
                try:
                    from sqlalchemy import select

                    async with self._article_repo._pool.session() as session:
                        from core.db.models import Article

                        result = await session.execute(
                            select(Article).where(Article.source_url == state["raw"].url)
                        )
                        article = result.scalar_one_or_none()
                        if article and article.persist_status == PersistStatus.PENDING:
                            article.persist_status = PersistStatus.PG_DONE
                            await session.commit()
                            log.info(
                                "terminal_article_status_updated",
                                url=state["raw"].url[:50],
                            )
                except Exception as exc:
                    log.warning(
                        "terminal_article_status_update_failed",
                        url=state["raw"].url[:50],
                        error=str(exc),
                    )

        if not valid_states:
            return

        if self._article_repo:
            try:
                article_ids = await self._article_repo.bulk_upsert(valid_states)
                log.info(
                    "persist_articles_committed",
                    article_ids=[str(aid) for aid in article_ids],
                    count=len(article_ids),
                )
                for state, aid in zip(valid_states, article_ids):
                    state["article_id"] = str(aid)
                    # persist_status is set to PG_DONE in bulk_upsert._upsert_single

                if self._vector_repo:
                    vector_data = []
                    for state in valid_states:
                        if "vectors" in state:
                            vectors = state["vectors"]
                            if (
                                isinstance(vectors, dict)
                                and "title" in vectors
                                and "content" in vectors
                            ):
                                import uuid

                                vector_data.append(
                                    (
                                        uuid.UUID(state["article_id"]),
                                        vectors.get("title"),
                                        vectors.get("content"),
                                        vectors.get("model_id", "unknown"),
                                    )
                                )
                    if vector_data:
                        log.info(
                            "persist_vectors_about_to_insert",
                            article_ids=[str(v[0]) for v in vector_data],
                            count=len(vector_data),
                        )
                        count = await self._vector_repo.bulk_upsert_article_vectors(vector_data)
                        log.debug("vectors_bulk_persisted", count=count)

                log.info("batch_pg_persisted", count=len(article_ids))
            except Exception as exc:
                import traceback as tb

                log.error(
                    "persist_batch_pg_failed",
                    error=str(exc),
                    exc_type=type(exc).__name__,
                    traceback=tb.format_exc(),
                )
                # Log article IDs for debugging
                for state in valid_states:
                    if state.get("article_id"):
                        log.warning(
                            "persist_debug_article_exists",
                            article_id=state["article_id"],
                        )
                for state in valid_states:
                    if state.get("article_id"):
                        try:
                            import uuid

                            await self._article_repo.mark_failed(
                                uuid.UUID(state["article_id"]), f"PG error: {exc!s}"
                            )
                        except Exception:
                            pass
                return

        if self._neo4j_writer:
            for state in valid_states:
                try:
                    neo4j_ids = await self._neo4j_writer.write(state)
                    state["neo4j_ids"] = neo4j_ids
                    if self._article_repo and state.get("article_id"):
                        import uuid

                        await self._article_repo.update_persist_status(
                            uuid.UUID(state["article_id"]), PersistStatus.NEO4J_DONE
                        )
                except Exception as exc:
                    log.error(
                        "persist_neo4j_failed",
                        article_id=state.get("article_id"),
                        error=str(exc),
                    )
                    if state.get("article_id") and self._article_repo:
                        try:
                            import uuid

                            await self._article_repo.mark_failed(
                                uuid.UUID(state["article_id"]), f"Neo4j error: {exc!s}"
                            )
                        except Exception:
                            pass

    async def stop_accepting(self) -> None:
        """Stop accepting new pipeline tasks."""
        self._accepting = False
        log.info("pipeline_stop_accepting")

    async def drain(self) -> None:
        """Wait for all in-progress tasks to complete."""
        # In a production implementation, this would track in-flight tasks.
        log.info("pipeline_drained")
