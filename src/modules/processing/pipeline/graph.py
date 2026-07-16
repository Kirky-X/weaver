# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Main pipeline flow definition."""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from core.llm.resilience.pool import AllProvidersFailedError
from core.observability import get_logger
from core.observability.metrics import MetricsCollector
from core.observability.throughput import PipelineThroughputTracker
from modules.ingestion.domain.models import RawArticle
from modules.processing.nlp.spacy_extractor import SpacyExtractor
from modules.processing.nodes.checkpoint_cleanup import CheckpointCleanupNode
from modules.processing.nodes.classification.categorizer import CascadeCategorizerNode
from modules.processing.nodes.classification.classifier import CascadeClassifierNode
from modules.processing.nodes.classification.credibility_checker import (
    RuleBasedCredibilityCheckerNode,
)
from modules.processing.nodes.extraction.analyze import AnalyzeNode
from modules.processing.nodes.extraction.entity_extractor import EntityExtractorNode
from modules.processing.nodes.merging.batch_merger import BatchMergerNode
from modules.processing.nodes.quality.cleaner import CleanerNode
from modules.processing.nodes.quality.conflict_detector import ConflictDetectorNode
from modules.processing.nodes.quality.fake_news_node import FakeNewsDetectorNode
from modules.processing.nodes.quality.quality_scorer import RuleBasedQualityScorerNode
from modules.processing.nodes.vectorization.re_vectorize import ReVectorizeNode
from modules.processing.nodes.vectorization.vectorize import VectorizeNode
from modules.processing.pipeline.community_trigger import CommunityUpdateTrigger
from modules.processing.pipeline.content_hash_cache import ContentHashCacheService
from modules.processing.pipeline.deps import PipelineDeps
from modules.processing.pipeline.memory_publisher import MemoryEventPublisher
from modules.processing.pipeline.persistence import PipelinePersistence
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from config.settings import Settings

log = get_logger(__name__)


def _check_fatal_provider_errors(
    results: list[Any],
    phase_name: str,
) -> None:
    """Raise immediately if any result is AllProvidersFailedError.

    When all providers fail (e.g. 429 rate limit exhausted), continuing
    the batch is pointless — every subsequent LLM call will also fail.
    """
    for result in results:
        if isinstance(result, AllProvidersFailedError):
            log.critical(
                "pipeline_fatal_provider_failure",
                phase=phase_name,
                error=str(result),
            )
            raise result


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
    "fake_news_detector": "phase3_fake_news_detector",
    "conflict_detector": "phase3_conflict_detector",
}


class Pipeline:
    """Main news processing pipeline.

    Orchestrates the full article processing flow:
    1. Classifier → Cleaner → Categorizer → Vectorize (concurrent per article)
    2. Batch Merger (serial across batch)
    3. Re-vectorize → Analyze → Credibility → Entity extraction (concurrent)
    4. Persist → Cleanup
    """

    def __init__(
        self,
        deps: PipelineDeps,
        settings: Settings | None = None,
        debug: bool = False,
    ) -> None:
        self._accepting = True
        self._deps = deps
        self._settings = settings
        self._debug = debug
        self._throughput_tracker = PipelineThroughputTracker()

        # Concurrency limits - read from PipelineSettings, fallback to TOML default (5)
        pipeline_settings = settings.pipeline if settings else None
        self._phase1_concurrency = (
            pipeline_settings.phase1.concurrency if pipeline_settings else None
        ) or 5  # TOML default
        self._phase3_concurrency = (
            pipeline_settings.phase3.concurrency if pipeline_settings else None
        ) or 5  # TOML default

        # Semaphores for concurrency control
        self._phase1_semaphore = asyncio.Semaphore(self._phase1_concurrency)
        self._phase3_semaphore = asyncio.Semaphore(self._phase3_concurrency)

        log.info(
            "pipeline_init",
            phase1_concurrency=self._phase1_concurrency,
            phase3_concurrency=self._phase3_concurrency,
        )

        # Unpack deps for node construction
        llm = deps.llm
        budget = deps.budget
        prompt_loader = deps.prompt_loader
        spacy = deps.nlp.spacy or self._create_spacy_extractor(settings)
        vector_repo = deps.repos.vector_repo
        article_repo = deps.repos.article_repo
        graph_writer = deps.repos.graph_writer
        source_auth_repo = deps.repos.source_auth_repo
        entity_resolver = deps.nlp.entity_resolver
        cache_client = deps.infrastructure.cache_client
        community_updater = deps.infrastructure.community_updater
        saga_orchestrator = deps.infrastructure.saga_orchestrator
        relation_type_normalizer = deps.nlp.relation_type_normalizer
        sentiment_analyzer = deps.analyzers.sentiment_analyzer
        cascade_classifier = deps.analyzers.cascade_classifier
        gliner_extractor = deps.nlp.gliner_extractor
        mc_sampler = deps.analyzers.mc_sampler
        fake_news_detector = deps.analyzers.fake_news_detector

        # Initialize nodes
        self._classifier = CascadeClassifierNode(
            llm, budget, prompt_loader, cascade=cascade_classifier
        )
        self._cleaner = CleanerNode(
            llm,
            budget,
            prompt_loader,
            min_body_chars=pipeline_settings.cleaner_min_body_chars if pipeline_settings else 100,
            min_title_similarity=(
                pipeline_settings.cleaner_min_title_similarity if pipeline_settings else 0.7
            ),
        )
        self._categorizer = CascadeCategorizerNode(llm, prompt_loader, cascade=cascade_classifier)
        self._vectorize = VectorizeNode(llm)
        self._batch_merger = BatchMergerNode(
            llm, prompt_loader, vector_repo, saga_orchestrator=saga_orchestrator
        )

        # Get embedding model from configuration
        embedding_model = self._extract_embedding_model_id(settings)
        self._re_vectorize = ReVectorizeNode(llm, embedding_model)

        self._analyze = AnalyzeNode(
            llm,
            budget,
            prompt_loader,
            mc_sampler=mc_sampler,
            sentiment_analyzer=sentiment_analyzer,
        )
        self._quality_scorer = RuleBasedQualityScorerNode()
        self._credibility = RuleBasedCredibilityCheckerNode(deps.event_bus, source_auth_repo)
        self._entity_extractor = EntityExtractorNode(
            llm,
            budget,
            prompt_loader,
            spacy,
            settings,
            vector_repo,
            relation_type_normalizer=relation_type_normalizer,
            gliner_extractor=gliner_extractor,
        )
        self._conflict_detector = ConflictDetectorNode(
            article_repo=article_repo,
            vector_repo=vector_repo,
            llm_client=llm,
        )
        self._fake_news_node = (
            FakeNewsDetectorNode(detector=fake_news_detector)
            if fake_news_detector is not None
            else None
        )
        self._checkpoint_cleanup = CheckpointCleanupNode(cache_client)

        # Collaborators (composition): each owns a single responsibility that
        # was previously inlined in Pipeline. Pipeline delegates to them.
        self._persistence = PipelinePersistence(
            article_repo=article_repo,
            vector_repo=vector_repo,
            graph_writer=graph_writer,
            phase3_concurrency=self._phase3_concurrency,
        )
        self._content_hash_cache = ContentHashCacheService(cache_client=cache_client)
        self._community_trigger = CommunityUpdateTrigger(community_updater=community_updater)
        self._memory_publisher = MemoryEventPublisher(event_bus=deps.event_bus)

    @staticmethod
    def _create_spacy_extractor(settings: Settings | None) -> SpacyExtractor:
        """Create SpacyExtractor with settings if available."""
        if settings is not None:
            return SpacyExtractor(
                zh_model_path=settings.spacy.zh_model_path,
                en_model_path=settings.spacy.en_model_path,
            )
        return SpacyExtractor()

    async def _update_processing_stage(
        self, state: PipelineState, stage: str, pending_updates: list[tuple[str, str]]
    ) -> None:
        """Collect processing stage update for deferred batch flush.

        Instead of writing to DB immediately (which causes ~1900 individual
        UPDATEs per batch), this method collects updates in memory and flushes
        them in bulk via _flush_stage_updates after each phase completes.

        Args:
            state: Pipeline state containing article_id.
            stage: Current processing stage name.
            pending_updates: Batch-local list to append updates to.
        """
        article_id = state.get("article_id")
        if not article_id:
            return

        pending_updates.append((str(article_id), stage))

    async def _flush_stage_updates(self, pending_updates: list[tuple[str, str]]) -> None:
        """Flush accumulated stage updates to DB in bulk.

        Groups pending updates by stage and issues one UPDATE per group,
        reducing ~1900 individual queries to ~8 per batch.

        Args:
            pending_updates: Batch-local list of (article_id, stage) tuples.
                Will be cleared after flush.
        """
        if not pending_updates or not self._deps.repos.article_repo:
            return

        stage_groups: dict[str, list[uuid.UUID]] = defaultdict(list)
        for article_id_str, stage in pending_updates:
            try:
                stage_groups[stage].append(uuid.UUID(article_id_str))
            except ValueError:
                log.warning("invalid_article_id_in_stage_flush", article_id=article_id_str)

        pending_updates.clear()

        for stage, ids in stage_groups.items():
            try:
                await self._deps.repos.article_repo.bulk_update_processing_stage(ids, stage)
            except Exception as e:
                log.warning("flush_stage_updates_failed", stage=stage, count=len(ids), error=str(e))
                # Re-enqueue failed updates for retry on next flush
                for failed_id in ids:
                    pending_updates.append((str(failed_id), stage))

    async def _publish_memory_events(self, states: list[PipelineState]) -> None:
        """Publish memory ingest events for successfully processed articles.

        Delegates to :class:`MemoryEventPublisher`.

        Args:
            states: List of completed pipeline states.
        """
        await self._memory_publisher.publish(states)

    # ── Content hash cache methods (delegate to ContentHashCacheService) ──

    async def _check_content_hash_cache(
        self, articles: list[RawArticle]
    ) -> list[dict[str, Any] | None]:
        """Check content hash cache for a batch of articles.

        Delegates to :class:`ContentHashCacheService`.

        Args:
            articles: List of raw articles to check.

        Returns:
            List of cached results (None for cache misses).
        """
        return await self._content_hash_cache.check(articles)

    async def _write_content_hash_cache(self, state: PipelineState) -> None:
        """Write processing result to content hash cache.

        Delegates to :class:`ContentHashCacheService`.

        Args:
            state: Completed pipeline state to cache.
        """
        await self._content_hash_cache.write(state)

    async def _write_content_hash_cache_batch(self, states: list[PipelineState]) -> None:
        """Write multiple processing results to content hash cache.

        Delegates to :class:`ContentHashCacheService`.

        Args:
            states: List of completed pipeline states to cache.
        """
        await self._content_hash_cache.write_batch(states)

    async def process_batch(
        self,
        articles: list[RawArticle],
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

        # Batch-local progress counters (not instance variables — safe for concurrent batches)
        batch_total = len(articles)
        batch_completed = 0
        batch_failed = 0
        pending_stage_updates: list[tuple[str, str]] = []

        # ── Section: Initialize states ──────────────────────────────
        states: list[PipelineState] = []
        for i, article in enumerate(articles):
            state = PipelineState(raw=article)
            if article_ids is not None and i < len(article_ids):
                state["article_id"] = str(article_ids[i])
            if task_id is not None:
                state["task_id"] = str(task_id)
            states.append(state)

        # ── Section: Content hash cache check ───────────────────────
        cached_results = await self._content_hash_cache.check(articles)
        cache_hits = 0
        for i, cached in enumerate(cached_results):
            if cached is not None:
                states[i].update(cached)
                states[i]["_cache_hit"] = True
                cache_hits += 1
        if cache_hits > 0:
            log.info("content_hash_cache_hit", hits=cache_hits, total=len(articles))

        # ── Section: Phase 1 — Per-article concurrent nodes (batched) ────────
        batch_size = self._settings.pipeline_process.worker_batch_size if self._settings else 20
        phase1_results: list[Any] = []
        for i in range(0, len(states), batch_size):
            batch = states[i : i + batch_size]
            batch_tasks = [self._phase1_per_article(s, pending_stage_updates) for s in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=not self._debug)
            phase1_results.extend(batch_results)

        # Debug mode: exceptions already raised, skip error handling
        if self._debug:
            states = list(phase1_results)
        else:
            # Fatal provider errors must abort the entire batch immediately
            _check_fatal_provider_errors(phase1_results, "phase1")

            # Flush Phase 1 stage updates in bulk
            await self._flush_stage_updates(pending_stage_updates)

            # Handle errors gracefully - failed articles get error state, others continue
            states = []
            for i, result in enumerate(phase1_results):
                if isinstance(result, Exception):
                    article_id = (
                        str(article_ids[i])
                        if article_ids is not None and i < len(article_ids)
                        else None
                    )
                    log.error(
                        "phase1_task_failed",
                        article_index=i,
                        article_id=article_id,
                        url=articles[i].url,
                        error=str(result),
                        error_type=type(result).__name__,
                    )
                    MetricsCollector.pipeline_failure_count.labels(
                        stage="phase1",
                        error_type=type(result).__name__,
                    ).inc()
                    # Create failed state for the article
                    failed_state = PipelineState(raw=articles[i])
                    if article_id:
                        failed_state["article_id"] = article_id
                    if task_id is not None:
                        failed_state["task_id"] = str(task_id)
                    failed_state["terminal"] = True
                    failed_state["error"] = str(result)
                    states.append(failed_state)
                else:
                    states.append(result)

        # ── Section: Phase 2-6 — Batch merge → Persist → Cleanup ──
        # Phase 2: Batch merger (serial)
        try:
            start = time.monotonic()
            states = await self._batch_merger.execute_batch(list(states))
            MetricsCollector.pipeline_stage_latency.labels(stage="batch_merger").observe(
                time.monotonic() - start
            )

            # Phase 3: Per-article post-merge nodes (concurrent)
            pre_phase3_states = list(states)
            phase3_tasks = [
                self._phase3_per_article(state, pending_stage_updates) for state in states
            ]
            phase3_results = await asyncio.gather(*phase3_tasks, return_exceptions=not self._debug)

            # Debug mode: exceptions already raised, skip error handling
            if self._debug:
                states = list(phase3_results)
            else:
                # Fatal provider errors must abort the entire batch immediately
                _check_fatal_provider_errors(phase3_results, "phase3")
                # Handle errors gracefully - preserve original state for failed articles
                states = []
                for i, result in enumerate(phase3_results):
                    if isinstance(result, Exception):
                        log.error(
                            "phase3_task_failed",
                            article_index=i,
                            error=str(result),
                            error_type=type(result).__name__,
                        )
                        log.debug(
                            "phase3_traceback",
                            trace="".join(
                                traceback.format_exception(
                                    type(result), result, result.__traceback__
                                )
                            ),
                        )
                        MetricsCollector.pipeline_failure_count.labels(
                            stage="phase3",
                            error_type=type(result).__name__,
                        ).inc()
                        # Preserve pre-phase3 state so Phase 1/2 results are not lost
                        # Keep terminal=True from Phase1 if set, otherwise mark non-terminal
                        original = pre_phase3_states[i]
                        original.setdefault("terminal", False)
                        original["phase3_error"] = str(result)
                        states.append(original)
                    else:
                        states.append(result)

            # Flush Phase 3 stage updates in bulk
            await self._flush_stage_updates(pending_stage_updates)

            # Phase 4: Persist (批量持久化)
            batch_completed, batch_failed = await self._persistence.persist_batch(
                states, batch_total, batch_completed, batch_failed
            )

            # Incremental community update check (non-blocking)
            await self._community_trigger.maybe_trigger(states)

            # Phase 5: Checkpoint cleanup
            cleanup_tasks = [self._checkpoint_cleanup.execute(state) for state in states]
            cleanup_results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            # Log cleanup failures but don't fail the pipeline
            for i, result in enumerate(cleanup_results):
                if isinstance(result, Exception):
                    log.warning(
                        "checkpoint_cleanup_failed",
                        article_index=i,
                        error=str(result),
                    )

            # Phase 6: Publish memory ingest events for successful states
            await self._memory_publisher.publish(states)

            # Phase 7: Write content hash cache for successful states
            successful_states = [
                s for s in states if not s.get("terminal") and not s.get("_cache_hit")
            ]
            if successful_states:
                await self._content_hash_cache.write_batch(successful_states)

            log.info(
                "pipeline_batch_complete",
                batch_size=len(articles),
                processed=sum(1 for s in states if not s.get("terminal")),
            )

            # Record throughput for monitoring
            processed_count = sum(1 for s in states if not s.get("terminal"))
            if processed_count > 0:
                worker_id = f"worker-{task_id or 'default'}"
                self._throughput_tracker.record_completion(worker_id, count=processed_count)
                self._throughput_tracker.update_gauge(worker_id)
                if self._throughput_tracker.is_low_throughput(worker_id):
                    log.warning(
                        "pipeline_throughput_low",
                        worker_id=worker_id,
                        throughput=self._throughput_tracker.calculate_throughput(worker_id),
                        threshold=self._throughput_tracker._low_threshold,
                    )

            return states
        except Exception as exc:
            log.error(
                "process_batch_internal_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
                traceback=traceback.format_exc(),
            )
            raise

    async def process_batch_fast(
        self,
        articles: list[RawArticle],
        article_ids: list[Any] | None = None,
        task_id: Any | None = None,
    ) -> list[PipelineState]:
        """Process a batch of articles through Phase 1 only (fast mode).

        Fast mode skips Phase 2 (batch merger), Phase 3 (deep analysis),
        entity extraction, and graph writing. Only runs:
        - Classifier → Cleaner → Categorizer → Vectorize

        This is useful for quick ingestion where full analysis is not required.

        Args:
            articles: List of raw articles to process.
            article_ids: Optional list of article UUIDs aligned with articles list.
            task_id: Optional pipeline task UUID for failure correlation.

        Returns:
            List of completed pipeline states (Phase 1 only).
        """
        if not self._accepting:
            raise RuntimeError("Pipeline is not accepting new tasks")

        log.info("pipeline_batch_fast_start", batch_size=len(articles))

        # Batch-local progress counters (not instance variables — safe for concurrent batches)
        batch_total = len(articles)
        batch_completed = 0
        batch_failed = 0
        pending_stage_updates: list[tuple[str, str]] = []

        # Initialize states with optional article_id and task_id
        states: list[PipelineState] = []
        for i, article in enumerate(articles):
            state = PipelineState(raw=article)
            if article_ids is not None and i < len(article_ids):
                state["article_id"] = str(article_ids[i])
            if task_id is not None:
                state["task_id"] = str(task_id)
            states.append(state)

        # Phase 1: Per-article concurrent nodes only (batched)
        batch_size = self._settings.pipeline_process.worker_batch_size if self._settings else 20
        phase1_results: list[Any] = []
        for i in range(0, len(states), batch_size):
            batch = states[i : i + batch_size]
            batch_tasks = [self._phase1_per_article(s, pending_stage_updates) for s in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=not self._debug)
            phase1_results.extend(batch_results)

        # Debug mode: exceptions already raised, skip error handling
        if self._debug:
            states = list(phase1_results)
        else:
            # Fatal provider errors must abort the entire batch immediately
            _check_fatal_provider_errors(phase1_results, "phase1_fast")

            # Flush Phase 1 stage updates in bulk
            await self._flush_stage_updates(pending_stage_updates)

            # Handle errors gracefully
            states = []
            for i, result in enumerate(phase1_results):
                if isinstance(result, Exception):
                    log.error(
                        "phase1_task_failed_fast_mode",
                        article_index=i,
                        error=str(result),
                        error_type=type(result).__name__,
                    )
                    MetricsCollector.pipeline_failure_count.labels(
                        stage="phase1_fast",
                        error_type=type(result).__name__,
                    ).inc()
                    failed_state = PipelineState(raw=articles[i])
                    article_id = (
                        str(article_ids[i])
                        if article_ids is not None and i < len(article_ids)
                        else None
                    )
                    if article_id:
                        failed_state["article_id"] = article_id
                    if task_id is not None:
                        failed_state["task_id"] = str(task_id)
                    failed_state["terminal"] = True
                    failed_state["error"] = str(result)
                    states.append(failed_state)
                else:
                    states.append(result)

        # Fast mode: persist directly without Phase 2/3
        batch_completed, batch_failed = await self._persistence.persist_batch(
            states, batch_total, batch_completed, batch_failed
        )

        # Checkpoint cleanup
        cleanup_tasks = [self._checkpoint_cleanup.execute(state) for state in states]
        cleanup_results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        for i, result in enumerate(cleanup_results):
            if isinstance(result, Exception):
                log.warning(
                    "checkpoint_cleanup_failed_fast_mode",
                    article_index=i,
                    error=str(result),
                )

        # Publish memory ingest events for successful states
        await self._memory_publisher.publish(states)

        log.info(
            "pipeline_batch_fast_complete",
            batch_size=len(articles),
            processed=sum(1 for s in states if not s.get("terminal")),
        )

        # Record throughput for monitoring
        processed_count = sum(1 for s in states if not s.get("terminal"))
        if processed_count > 0:
            worker_id = f"worker-fast-{task_id or 'default'}"
            self._throughput_tracker.record_completion(worker_id, count=processed_count)
            self._throughput_tracker.update_gauge(worker_id)
            if self._throughput_tracker.is_low_throughput(worker_id):
                log.warning(
                    "pipeline_throughput_low",
                    worker_id=worker_id,
                    throughput=self._throughput_tracker.calculate_throughput(worker_id),
                    threshold=self._throughput_tracker._low_threshold,
                )

        return states

    async def _phase1_per_article(
        self, state: PipelineState, pending_updates: list[tuple[str, str]]
    ) -> PipelineState:
        """Phase 1: classify → clean → (categorize || vectorize).

        DAG execution:
        - classifier must run first (determines if news)
        - cleaner runs after classifier
        - categorizer and vectorize can run in parallel after cleaner
        """
        article_start = time.monotonic()
        async with self._phase1_semaphore:
            start = time.monotonic()
            state = await self._classifier.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="classifier").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE1_STAGES["classifier"], pending_updates)

            if state.get("terminal"):
                log.info(
                    "phase1_terminal_skip",
                    url=state["raw"].url if state.get("raw") else "unknown",
                    stage="cleaner,categorizer,vectorize",
                )
                MetricsCollector.pipeline_article_latency.labels(
                    category=state.get("category", "unknown")
                ).observe(time.monotonic() - article_start)
                return state

            start = time.monotonic()
            state = await self._cleaner.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="cleaner").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(state, PHASE1_STAGES["cleaner"], pending_updates)

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

            gather_results = await asyncio.gather(
                categorizer_task, vectorize_task, return_exceptions=not self._debug
            )
            categorizer_result, vectorize_result = gather_results[0], gather_results[1]

            # Debug mode: exceptions already raised, use results directly
            if self._debug:
                state.update(categorizer_result)
                state.update(vectorize_result)
            else:
                # Fatal provider errors must propagate immediately
                _check_fatal_provider_errors(
                    [categorizer_result, vectorize_result],
                    "phase1_categorize_vectorize",
                )

                # Handle categorizer result
                if isinstance(categorizer_result, Exception):
                    log.warning(
                        "categorizer_failed",
                        error=str(categorizer_result),
                        url=getattr(state.get("raw"), "url", "unknown"),
                    )
                    categorizer_state: dict[str, Any] = {}
                else:
                    categorizer_state = categorizer_result

                # Handle vectorize result
                if isinstance(vectorize_result, Exception):
                    log.warning(
                        "vectorize_failed",
                        error=str(vectorize_result),
                        url=getattr(state.get("raw"), "url", "unknown"),
                    )
                    vectorize_state: dict[str, Any] = {}
                else:
                    vectorize_state = vectorize_result

                state.update(categorizer_state)
                state.update(vectorize_state)

            await self._update_processing_stage(
                state, PHASE1_STAGES["categorizer"], pending_updates
            )
            await self._update_processing_stage(state, PHASE1_STAGES["vectorize"], pending_updates)

            MetricsCollector.pipeline_article_latency.labels(
                category=state.get("category", "unknown")
            ).observe(time.monotonic() - article_start)
            return state

    async def _phase3_per_article(
        self, state: PipelineState, pending_updates: list[tuple[str, str]]
    ) -> PipelineState:
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

            # re_vectorize requires article vectors — skip for terminal (non-news) articles
            if not state.get("terminal"):
                start = time.monotonic()
                state = await self._re_vectorize.execute(state)
                MetricsCollector.pipeline_stage_latency.labels(stage="re_vectorize").observe(
                    time.monotonic() - start
                )
                await self._update_processing_stage(
                    state, PHASE3_STAGES["re_vectorize"], pending_updates
                )

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

            gather_results = await asyncio.gather(
                analyze_task, quality_task, return_exceptions=not self._debug
            )
            analyze_result, quality_result = gather_results[0], gather_results[1]

            # Debug mode: exceptions already raised, use results directly
            if self._debug:
                state.update(analyze_result)
                state.update(quality_result)
            else:
                # Fatal provider errors must propagate immediately
                _check_fatal_provider_errors(
                    [analyze_result, quality_result],
                    "phase3_analyze_quality",
                )

                # Handle analyze result
                if isinstance(analyze_result, Exception):
                    log.warning(
                        "analyze_failed",
                        error=str(analyze_result),
                        url=getattr(state.get("raw"), "url", "unknown"),
                    )
                    analyze_state: dict[str, Any] = {}
                else:
                    analyze_state = analyze_result

                # Handle quality scorer result
                if isinstance(quality_result, Exception):
                    log.warning(
                        "quality_scorer_failed",
                        error=str(quality_result),
                        url=getattr(state.get("raw"), "url", "unknown"),
                    )
                    quality_state: dict[str, Any] = {}
                else:
                    quality_state = quality_result

                state.update(analyze_state)
                state.update(quality_state)

            await self._update_processing_stage(state, PHASE3_STAGES["analyze"], pending_updates)
            await self._update_processing_stage(
                state, PHASE3_STAGES["quality_scorer"], pending_updates
            )

            start = time.monotonic()
            state = await self._credibility.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="credibility").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(
                state, PHASE3_STAGES["credibility"], pending_updates
            )

            start = time.monotonic()
            state = await self._entity_extractor.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="entity_extractor").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(
                state, PHASE3_STAGES["entity_extractor"], pending_updates
            )

            # === Fake News Detector 阶段 ===
            if self._fake_news_node is not None:
                start = time.monotonic()
                state = await self._fake_news_node.execute(state)
                MetricsCollector.pipeline_stage_latency.labels(stage="fake_news_detector").observe(
                    time.monotonic() - start
                )
                await self._update_processing_stage(
                    state, PHASE3_STAGES["fake_news_detector"], pending_updates
                )

            # === Conflict Detector 阶段 ===
            start = time.monotonic()
            state = await self._conflict_detector.execute(state)
            MetricsCollector.pipeline_stage_latency.labels(stage="conflict_detector").observe(
                time.monotonic() - start
            )
            await self._update_processing_stage(
                state, PHASE3_STAGES["conflict_detector"], pending_updates
            )

            # === Entity Resolver 阶段 ===
            if state.get("entities") and self._deps.nlp.entity_resolver:
                resolved_entities = await self._deps.nlp.entity_resolver.resolve_entities_batch(
                    entities=state["entities"]
                )
                state["resolved_entities"] = resolved_entities
                log.debug(
                    "entity_resolver_complete",
                    url=state["raw"].url,
                    resolved_count=len(resolved_entities),
                )

            return state

    async def _persist_batch(
        self,
        states: list[PipelineState],
        batch_total: int,
        batch_completed: int,
        batch_failed: int,
    ) -> tuple[int, int]:
        """Persist batch of articles to Postgres and Neo4j.

        Delegates to :class:`PipelinePersistence`.

        Args:
            states: List of pipeline states to persist.
            batch_total: Total articles in batch.
            batch_completed: Number of completed articles so far.
            batch_failed: Number of failed articles so far.

        Returns:
            Tuple of (batch_completed, batch_failed) with updated counts.
        """
        return await self._persistence.persist_batch(
            states, batch_total, batch_completed, batch_failed
        )

    async def stop_accepting(self) -> None:
        """Stop accepting new pipeline tasks."""
        self._accepting = False
        log.info("pipeline_stop_accepting")

    async def drain(self) -> None:
        """Wait for all in-progress tasks to complete."""
        # In a production implementation, this would track in-flight tasks.
        log.info("pipeline_drained")

    async def process_article_phase3(
        self,
        article_id: str,
        state: PipelineState | None = None,
        *,
        force_reprocess: bool = False,
    ) -> PipelineState:
        """Process a single article through phase 3 enrichment.

        This is a public interface for re-running enrichment on existing articles
        without going through the full pipeline. Used by repair operations.

        Args:
            article_id: The article ID to process.
            state: Optional pre-built pipeline state. If not provided, a minimal
                   state will be created from the article_id.
            force_reprocess: Force reprocessing even if article appears complete.

        Returns:
            The enriched pipeline state.

        Raises:
            ArticleNotFoundError: If article does not exist.
        """
        log.info("process_article_phase3", article_id=article_id, force_reprocess=force_reprocess)

        if state is None:
            # Build minimal state from article_id
            if self._deps.repos.article_repo is None:
                raise RuntimeError("article_repo required for process_article_phase3")

            article = await self._deps.repos.article_repo.get_by_id(article_id)
            if article is None:
                raise ValueError(f"Article not found: {article_id}")

            from modules.ingestion.domain.models import RawArticle

            raw = RawArticle(
                url=article.source_url,
                title=article.title or "",
                body=article.body or "",
                source=article.source_host or "",
                source_host=article.source_host or "",
                publish_time=article.publish_time,
            )
            state = PipelineState(raw=raw)
            state["article_id"] = str(article.id)
            state["is_news"] = article.is_news
            state["terminal"] = not article.is_news
            state["cleaned"] = {
                "title": article.title or "",
                "body": article.body or "",
            }

        # Run phase 3 enrichment (no batch context — stage updates are not tracked)
        return await self._phase3_per_article(state, [])

    async def get_article_status(self, article_id: str) -> dict[str, Any]:
        """Get the processing status for an article.

        Args:
            article_id: The article ID to check.

        Returns:
            Status dict with phase completion flags.
        """
        if self._deps.repos.article_repo is None:
            return {"error": "article_repo not configured"}

        article = await self._deps.repos.article_repo.get_by_id(article_id)
        if article is None:
            return {"status": "not_found", "article_id": article_id}

        return {
            "article_id": article_id,
            "persist_status": str(article.persist_status) if article.persist_status else None,
            "has_summary": article.summary is not None,
            "has_category": article.category is not None,
            "has_score": article.score is not None,
            "has_credibility": article.credibility_score is not None,
        }

    async def _maybe_trigger_community_update(self, states: list[PipelineState]) -> None:
        """Check and trigger incremental community update after Phase 4 persist.

        Delegates to :class:`CommunityUpdateTrigger`.

        This is non-blocking and logs the update status without affecting
        pipeline completion.

        Args:
            states: Pipeline states after persist.
        """
        await self._community_trigger.maybe_trigger(states)

    @staticmethod
    def _extract_embedding_model_id(settings: Any) -> str:
        """Extract embedding model ID from settings.

        Parses defaults.embedding.primary from LLM config.
        Format: "embedding.aiping.Qwen3-Embedding-0.6B" -> "Qwen3-Embedding-0.6B"

        The label format is "<type>.<provider>.<model_id>" where model_id may
        contain dots (e.g., Qwen3-Embedding-0.6B). We split on first 2 dots only.
        """
        try:
            if settings and hasattr(settings, "llm"):
                embedding_config = settings.llm.defaults.get("embedding")
                if embedding_config and embedding_config.primary:
                    # Split only on first 2 dots to preserve model_id with dots
                    parts = embedding_config.primary.split(".", 2)
                    if len(parts) >= 3:
                        return parts[2]  # Return model_id (third part)
        except (AttributeError, KeyError, IndexError) as exc:
            log.debug("extract_embedding_model_id_failed", error=str(exc))
        return "Qwen3-Embedding-0.6B"
