# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Main pipeline flow definition."""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from core.constants import EmbeddingModel
from core.llm.resilience.pool import AllProvidersFailedError
from core.observability import get_logger
from core.observability.metrics import MetricsCollector
from core.observability.throughput import PipelineThroughputTracker
from core.types.ingestion_models import RawArticle
from modules.processing.nlp.spacy_extractor import SpacyExtractor
from modules.processing.nodes.checkpoint_cleanup import CheckpointCleanupNode
from modules.processing.nodes.classification.categorizer import CascadeCategorizerNode
from modules.processing.nodes.classification.classifier import CascadeClassifierNode
from modules.processing.nodes.classification.credibility_checker import (
    RuleBasedCredibilityCheckerNode,
)
from modules.processing.nodes.extraction.analyze import AnalyzeNode
from modules.processing.nodes.extraction.entity_extractor import EntityExtractorNode
from modules.processing.nodes.extraction.narrative_schema_extractor import (
    NarrativeSchemaExtractorNode,
)
from modules.processing.nodes.extraction.sentiment_tracker import (
    SentimentTrackerNode,
)
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
    "narrative_schema": "phase3_narrative_schema",
    "sentiment_tracker": "phase3_sentiment_tracker",
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
        # In-flight batch tracking for graceful shutdown: drain() waits on
        # this counter reaching zero before the container tears down pools.
        self._active_batches = 0
        self._batch_slot_lock = asyncio.Condition()
        self._deps = deps
        self._settings = settings
        # Debug mode: asyncio.gather uses return_exceptions=False so exceptions
        # propagate immediately — all `if self._debug:` branches below skip
        # error handling / fatal-error checks accordingly.
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

        # Read independent stage enabled flags from TOML config.
        # Only independent stages (no downstream dependents) respect the
        # disabled flag; dependency stages always execute to preserve DAG
        # integrity. Empty set when TOML doesn't configure stages —
        # backward-compatible default (all independent stages enabled).
        self._disabled_phase3_stage_names: set[str] = set()
        if pipeline_settings and pipeline_settings.phase3:
            for stage in pipeline_settings.phase3.stages:
                if not stage.enabled and stage.name:
                    self._disabled_phase3_stage_names.add(stage.name)

        log.info(
            "pipeline_init",
            phase1_concurrency=self._phase1_concurrency,
            phase3_concurrency=self._phase3_concurrency,
            disabled_phase3_stages=sorted(self._disabled_phase3_stage_names),
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

        # Get embedding model from configuration
        embedding_model = self._extract_embedding_model_id(settings)
        text_limit = (
            settings.pipeline_process.embedding_text_limit
            if settings and hasattr(settings, "pipeline_process")
            else 2000
        )
        self._vectorize = VectorizeNode(llm, embedding_model, text_limit=text_limit)
        self._batch_merger = BatchMergerNode(
            llm,
            prompt_loader,
            vector_repo,
            saga_orchestrator=saga_orchestrator,
            similarity_threshold=(
                pipeline_settings.merge_similarity_threshold if pipeline_settings else 0.80
            ),
        )

        self._re_vectorize = ReVectorizeNode(llm, embedding_model, text_limit=text_limit)

        self._analyze = AnalyzeNode(
            llm,
            budget,
            prompt_loader,
            mc_sampler=mc_sampler,
            sentiment_analyzer=sentiment_analyzer,
            merge_narrative=(
                pipeline_settings.phase3.merge_analyze_narrative if pipeline_settings else False
            ),
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
            similarity_threshold=(
                pipeline_settings.conflict_similarity_threshold if pipeline_settings else 0.7
            ),
        )
        self._fake_news_node = (
            FakeNewsDetectorNode(detector=fake_news_detector)
            if fake_news_detector is not None
            else None
        )
        # Narrative+schema extractor node — single LLM call yielding both
        # framing dimensions (NarrativeNode) and event schema (SchemaNode).
        # Replaces the former separate NarrativeGeneratorNode +
        # SchemaExtractorNode (token optimization: 2 calls → 1). Each graph
        # write degrades independently per Rule 12.
        merge_narrative = (
            pipeline_settings.phase3.merge_analyze_narrative if pipeline_settings else False
        )
        if merge_narrative and "narrative_schema" in self._disabled_phase3_stage_names:
            # 误配置防护：stage 被禁用时合并调用的 narrative 半截白算
            # （与 TOML 注释约定一致，把人为纪律变成机器约束）。
            log.warning(
                "merge_narrative_with_stage_disabled",
                hint="disable [phase3] merge_analyze_narrative or re-enable narrative_schema stage",
            )
        self._narrative_schema = (
            NarrativeSchemaExtractorNode(
                llm, budget, prompt_loader, graph_writer, merge_narrative=merge_narrative
            )
            if graph_writer is not None
            else None
        )
        # Sentiment tracker node — pure computation (no LLM). Computes
        # per-entity article-level sentiment shifts against the previous
        # article mentioning the same entity, persists to sentiment_shifts
        # (article_id/entity_name/shift_value fields from migration 30).
        # Skipped when sentiment_shift_repo is unavailable.
        sentiment_shift_repo = deps.infrastructure.sentiment_shift_repo
        self._sentiment_tracker = (
            SentimentTrackerNode(shift_repo=sentiment_shift_repo)
            if sentiment_shift_repo is not None
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
            pending_sync_repo=deps.infrastructure.pending_sync_repo,
        )
        self._content_hash_cache = ContentHashCacheService(
            cache_client=cache_client,
            schema_version=(pipeline_settings.content_hash_version if pipeline_settings else 2),
            ttl_seconds=(
                pipeline_settings.content_hash_cache_ttl_seconds if pipeline_settings else 604800
            ),
        )
        self._community_trigger = CommunityUpdateTrigger(community_updater=community_updater)
        self._memory_publisher = MemoryEventPublisher(
            event_bus=deps.event_bus, outbox_repo=deps.infrastructure.outbox_repo
        )

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

    async def process_batch(
        self,
        articles: list[RawArticle],
        article_ids: list[Any] | None = None,
        task_id: Any | None = None,
    ) -> list[PipelineState]:
        """Process a batch of articles through the full pipeline.

        Tracks the batch as in-flight so ``drain()`` (graceful shutdown)
        waits for it; refuses new batches after ``stop_accepting()``.

        Args:
            articles: List of raw articles to process.
            article_ids: Optional list of article UUIDs aligned with articles list.
            task_id: Optional pipeline task UUID for failure correlation.

        Returns:
            List of completed pipeline states.
        """
        async with self._batch_slot():
            return await self._process_batch_impl(articles, article_ids, task_id)

    async def _process_batch_impl(
        self,
        articles: list[RawArticle],
        article_ids: list[Any] | None = None,
        task_id: Any | None = None,
    ) -> list[PipelineState]:
        """Run the full pipeline over a batch (caller holds a batch slot)."""
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
        # Cache-hit states already carry a complete processed snapshot; they
        # skip Phase 1 (and Phase 3) — that is the point of the short-circuit.
        cache_hit_states = [s for s in states if s.get("_cache_hit")]
        pending_phase1 = [s for s in states if not s.get("_cache_hit")]
        batch_size = self._settings.pipeline_process.worker_batch_size if self._settings else 20
        phase1_results: list[Any] = []
        for i in range(0, len(pending_phase1), batch_size):
            batch = pending_phase1[i : i + batch_size]
            batch_tasks = [self._phase1_per_article(s, pending_stage_updates) for s in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=not self._debug)
            phase1_results.extend(batch_results)

        if self._debug:
            states = cache_hit_states + list(phase1_results)
        else:
            # Fatal provider errors must abort the entire batch immediately
            _check_fatal_provider_errors(phase1_results, "phase1")

            # Flush Phase 1 stage updates in bulk
            await self._flush_stage_updates(pending_stage_updates)

            # Handle errors gracefully - failed articles get error state, others continue
            states = list(cache_hit_states)
            for i, result in enumerate(phase1_results):
                if isinstance(result, Exception):
                    src = pending_phase1[i]
                    raw_obj = src.get("raw")
                    log.error(
                        "phase1_task_failed",
                        article_index=i,
                        article_id=src.get("article_id"),
                        url=getattr(raw_obj, "url", "unknown"),
                        error=str(result),
                        error_type=type(result).__name__,
                    )
                    MetricsCollector.pipeline_failure_count.labels(
                        stage="phase1",
                        error_type=type(result).__name__,
                    ).inc()
                    # Create failed state for the article (raw may be absent
                    # on a malformed/cached state — PipelineState is
                    # total=False).
                    failed_state = (
                        PipelineState(raw=raw_obj) if raw_obj is not None else PipelineState()
                    )
                    if src.get("article_id"):
                        failed_state["article_id"] = src["article_id"]
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

            # Phase 3: Per-article post-merge nodes (concurrent).
            # Cache-hit states skip Phase 3: their snapshot already contains
            # the full Phase 3 analysis from the original processing run.
            pre_phase3_states = [s for s in states if not s.get("_cache_hit")]
            phase3_tasks = [
                self._phase3_per_article(state, pending_stage_updates)
                for state in pre_phase3_states
            ]
            phase3_results = await asyncio.gather(*phase3_tasks, return_exceptions=not self._debug)

            if self._debug:
                states = cache_hit_states + list(phase3_results)
            else:
                # Fatal provider errors must abort the entire batch immediately
                _check_fatal_provider_errors(phase3_results, "phase3")
                # Handle errors gracefully - preserve original state for failed articles
                states = list(cache_hit_states)
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
        async with self._batch_slot():
            return await self._process_batch_fast_impl(articles, article_ids, task_id)

    async def _process_batch_fast_impl(
        self,
        articles: list[RawArticle],
        article_ids: list[Any] | None = None,
        task_id: Any | None = None,
    ) -> list[PipelineState]:
        """Run the Phase-1-only pipeline over a batch (caller holds a slot)."""
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

            # === Phase 3 concurrent block (fix) ===
            # fake_news_detector + conflict_detector + narrative_schema are
            # independent (each reads shared state and writes its own keys).
            # Run them via asyncio.gather to cut Phase 3 tail latency from
            # 3x LLM to ~1x LLM.
            #
            # Nodes modify state in-place (see conflict_detector.execute:
            # ``state["data_conflicts"] = ...``), so gather returns the same
            # state reference 4 times; no merge needed. Each inner function
            # preserves MetricsCollector.pipeline_stage_latency observability.
            #
            # sentiment_tracker + entity_resolver remain serial (they depend
            # on entity_extractor output and run after this block).
            async def _run_fake_news() -> str | None:
                if "fake_news_detector" in self._disabled_phase3_stage_names:
                    return None
                if self._fake_news_node is None:
                    return None
                start_fn = time.monotonic()
                await self._fake_news_node.execute(state)
                MetricsCollector.pipeline_stage_latency.labels(stage="fake_news_detector").observe(
                    time.monotonic() - start_fn
                )
                return "fake_news_detector"

            async def _run_conflict() -> str | None:
                if "conflict_detector" in self._disabled_phase3_stage_names:
                    return None
                start_c = time.monotonic()
                await self._conflict_detector.execute(state)
                MetricsCollector.pipeline_stage_latency.labels(stage="conflict_detector").observe(
                    time.monotonic() - start_c
                )
                return "conflict_detector"

            async def _run_narrative_schema() -> str | None:
                if "narrative_schema" in self._disabled_phase3_stage_names:
                    return None
                if self._narrative_schema is None:
                    return None
                start_ns = time.monotonic()
                await self._narrative_schema.execute(state)
                MetricsCollector.pipeline_stage_latency.labels(stage="narrative_schema").observe(
                    time.monotonic() - start_ns
                )
                return "narrative_schema"

            concurrent_results = await asyncio.gather(
                _run_fake_news(),
                _run_conflict(),
                _run_narrative_schema(),
                return_exceptions=not self._debug,
            )

            # Update processing stages serially after concurrent completion
            # to preserve stage ordering (fake_news → conflict →
            # narrative_schema).
            stage_runners = {
                "fake_news_detector": "phase3_fake_news_detector",
                "conflict_detector": "phase3_conflict_detector",
                "narrative_schema": "phase3_narrative_schema",
            }
            for runner, stage_key in zip(concurrent_results, stage_runners):
                if isinstance(runner, BaseException):
                    # Exception from gather: record it like the other phase
                    # gather blocks do — silently skipping here would leave
                    # the article persisted with missing analysis data and
                    # no trace in metrics.
                    raw = state.get("raw")
                    log.error(
                        "phase3_concurrent_stage_failed",
                        stage=stage_key,
                        article_id=state.get("article_id"),
                        url=getattr(raw, "url", None) if raw else None,
                        error=str(runner),
                        error_type=type(runner).__name__,
                    )
                    MetricsCollector.pipeline_failure_count.labels(
                        stage="phase3",
                        error_type=type(runner).__name__,
                    ).inc()
                    continue
                if runner is None:
                    continue  # stage disabled or node unavailable
                await self._update_processing_stage(
                    state, PHASE3_STAGES[stage_key], pending_updates
                )

            # === Sentiment Tracker 阶段 ===
            # Pure computation node — no LLM. Computes per-entity article-level
            # sentiment shifts and persists to sentiment_shifts. Skipped when
            # sentiment_shift_repo is unavailable, when terminal/merged, or
            # when disabled in TOML config (independent stage).
            if (
                self._sentiment_tracker is not None
                and "sentiment_tracker" not in self._disabled_phase3_stage_names
            ):
                start = time.monotonic()
                state = await self._sentiment_tracker.execute(state)
                MetricsCollector.pipeline_stage_latency.labels(stage="sentiment_tracker").observe(
                    time.monotonic() - start
                )
                await self._update_processing_stage(
                    state, PHASE3_STAGES["sentiment_tracker"], pending_updates
                )

            # === Entity Resolver 阶段 ===
            if state.get("entities") and self._deps.nlp.entity_resolver:
                resolved_entities = await self._deps.nlp.entity_resolver.resolve_entities_batch(
                    entities=state["entities"]
                )
                state["resolved_entities"] = resolved_entities
                # state["raw"] is always set for current callers, but use
                # .get() so a future caller that omits it cannot crash this
                # debug log.
                raw_obj = state.get("raw")
                log.debug(
                    "entity_resolver_complete",
                    url=raw_obj.url if raw_obj else None,
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
        """Stop accepting new pipeline tasks.

        Acquires the same condition lock as _batch_slot so a batch cannot
        claim a slot while _accepting flips (relevant when this is called
        from another thread via call_soon_threadsafe).
        """
        async with self._batch_slot_lock:
            self._accepting = False
        log.info("pipeline_stop_accepting")

    @asynccontextmanager
    async def _batch_slot(self):
        """Claim a batch slot: reject when not accepting, track in-flight.

        The accept check and the counter increment share the condition lock
        so a batch cannot slip in between stop_accepting() and drain().
        """
        async with self._batch_slot_lock:
            if not self._accepting:
                raise RuntimeError("Pipeline is not accepting new tasks")
            self._active_batches += 1
        try:
            yield
        finally:
            async with self._batch_slot_lock:
                self._active_batches -= 1
                self._batch_slot_lock.notify_all()

    async def drain(self) -> None:
        """Wait for all in-progress batches to complete.

        Used by graceful shutdown: after ``stop_accepting()`` refuses new
        batches, this returns only once every already-running batch has
        finished, so the container never closes DB pools under a writing
        batch.
        """
        async with self._batch_slot_lock:
            await self._batch_slot_lock.wait_for(lambda: self._active_batches == 0)
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

            from core.types.ingestion_models import RawArticle

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

        Delegates to the shared helper in ``core.utils.model_id`` — the
        single implementation backing container, pipeline and memory wiring.
        """
        from core.utils.model_id import extract_embedding_model_id

        llm_settings = getattr(settings, "llm", None)
        if llm_settings is None:
            return EmbeddingModel.DEFAULT
        return extract_embedding_model_id(llm_settings)
