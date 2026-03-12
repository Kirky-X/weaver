"""LangGraph main pipeline flow definition."""

from __future__ import annotations

import asyncio
from typing import Any

from core.llm.client import LLMClient
from core.llm.token_budget import TokenBudgetManager
from core.prompt.loader import PromptLoader
from core.event.bus import EventBus
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from core.db.models import PersistStatus
from modules.pipeline.state import PipelineState
from modules.pipeline.nodes.classifier import ClassifierNode
from modules.pipeline.nodes.cleaner import CleanerNode
from modules.pipeline.nodes.categorizer import CategorizerNode
from modules.pipeline.nodes.vectorize import VectorizeNode
from modules.pipeline.nodes.batch_merger import BatchMergerNode
from modules.pipeline.nodes.re_vectorize import ReVectorizeNode
from modules.pipeline.nodes.analyze import AnalyzeNode
from modules.pipeline.nodes.credibility_checker import CredibilityCheckerNode
from modules.pipeline.nodes.entity_extractor import EntityExtractorNode
from modules.nlp.spacy_extractor import SpacyExtractor
from modules.collector.models import ArticleRaw

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
    DEFAULT_PHASE1_CONCURRENCY = 1  # Process articles one at a time to avoid Ollama overload
    DEFAULT_PHASE3_CONCURRENCY = 1  # Same for post-merge processing

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        event_bus: EventBus,
        spacy: SpacyExtractor | None = None,
        vector_repo: Any = None,
        article_repo: Any = None,
        neo4j_writer: Any = None,
        source_auth_repo: Any = None,
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
        self._credibility = CredibilityCheckerNode(
            llm, budget, event_bus, source_auth_repo
        )
        self._entity_extractor = EntityExtractorNode(
            llm, budget, prompt_loader, spacy or SpacyExtractor(), vector_repo
        )
        self._article_repo = article_repo
        self._neo4j_writer = neo4j_writer

    async def _update_processing_stage(
        self, state: PipelineState, stage: str
    ) -> None:
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
            await self._article_repo.update_processing_stage(
                uuid.UUID(article_id), stage
            )
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
            await self._article_repo.mark_processing(
                uuid.UUID(article_id), "phase1_start"
            )
        except Exception as e:
            log.warning("failed_to_mark_processing", article_id=article_id, error=str(e))

    async def process_batch(
        self, articles: list[ArticleRaw]
    ) -> list[PipelineState]:
        """Process a batch of articles through the full pipeline.

        Args:
            articles: List of raw articles to process.

        Returns:
            List of completed pipeline states.
        """
        if not self._accepting:
            raise RuntimeError("Pipeline is not accepting new tasks")

        log.info("pipeline_batch_start", batch_size=len(articles))

        # Initialize states
        states: list[PipelineState] = [
            PipelineState(raw=article) for article in articles
        ]

        # Phase 1: Per-article concurrent nodes
        phase1_tasks = [
            self._phase1_per_article(state) for state in states
        ]
        states = await asyncio.gather(*phase1_tasks)

        # Phase 2: Batch merger (serial)
        import time
        start = time.monotonic()
        states = await self._batch_merger.execute_batch(list(states))
        MetricsCollector.pipeline_stage_latency.labels(stage="batch_merger").observe(
            time.monotonic() - start
        )

        # Phase 3: Per-article post-merge nodes (concurrent)
        phase3_tasks = [
            self._phase3_per_article(state) for state in states
        ]
        states = list(await asyncio.gather(*phase3_tasks))

        # Phase 4: Persist
        persist_tasks = [self._persist(state) for state in states]
        await asyncio.gather(*persist_tasks)

        log.info(
            "pipeline_batch_complete",
            batch_size=len(articles),
            processed=sum(1 for s in states if not s.get("terminal")),
        )
        return states

    async def _phase1_per_article(self, state: PipelineState) -> PipelineState:
        """Phase 1: classify → clean → categorize → vectorize."""
        # Use semaphore to limit concurrency
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

            start = time.monotonic()
            state = await self._categorizer.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="categorizer").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE1_STAGES["categorizer"])

            start = time.monotonic()
            state = await self._vectorize.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="vectorize").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE1_STAGES["vectorize"])

            return state

    async def _phase3_per_article(self, state: PipelineState) -> PipelineState:
        """Phase 3: re-vectorize → analyze → credibility → entity extraction."""
        # Use semaphore to limit concurrency
        async with self._phase3_semaphore:
            if state.get("terminal") or state.get("is_merged"):
                return state

            import time

            start = time.monotonic()
            state = await self._re_vectorize.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="re_vectorize").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE3_STAGES["re_vectorize"])

            start = time.monotonic()
            state = await self._analyze.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="analyze").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE3_STAGES["analyze"])

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
            except Exception as exc:
                log.error("persist_pg_failed", url=state["raw"].url, error=str(exc))
                # Mark as failed if we have the article_id
                if state.get("article_id"):
                    try:
                        import uuid
                        await self._article_repo.mark_failed(
                            uuid.UUID(state["article_id"]), f"PG error: {str(exc)}"
                        )
                    except Exception:
                        pass
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
                # Mark as failed if we have the article_id
                if state.get("article_id") and self._article_repo:
                    try:
                        import uuid
                        await self._article_repo.mark_failed(
                            uuid.UUID(state["article_id"]), f"Neo4j error: {str(exc)}"
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
