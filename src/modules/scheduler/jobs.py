# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Scheduled jobs for weaver backend.

The SchedulerJobs class is a backward-compatible facade that delegates to
three single-responsibility sub-classes:
- ConsistencyJobs: retry, sync, and consistency checks
- MaintenanceJobs: cleanup and archival
- AnalyticsJobs: aggregation, briefing, and signal detection

The registration/scheduling logic and the source-scoring/metrics jobs remain
in SchedulerJobs itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from config.settings import SchedulerSettings
from core.db import Article, PersistStatus
from core.observability import get_logger
from core.observability.metrics import metrics
from modules.ingestion.deduplication.retry import RetryQueue
from modules.scheduler.analytics_jobs import AnalyticsJobs
from modules.scheduler.consistency_jobs import ConsistencyJobs
from modules.scheduler.maintenance_jobs import MaintenanceJobs
from modules.scheduler.wrapper import scheduled_task
from modules.storage import ArticleRepo, PendingSyncRepo, SourceAuthorityRepo, VectorRepo

if TYPE_CHECKING:
    from core.protocols import CachePool, RelationalPool
    from modules.knowledge.graph.neo4j_writer import Neo4jWriter

log = get_logger(__name__)


class SchedulerJobs:
    """APScheduler jobs facade for compensation, maintenance, and analytics tasks.

    Delegates consistency, maintenance, and analytics jobs to dedicated
    sub-classes while keeping source scoring and persist-status metrics
    jobs inline. Preserves the original public API so external callers
    and tests can continue to invoke any job method directly on this class.

    Implements: composition root for ConsistencyJobs, MaintenanceJobs, AnalyticsJobs.
    """

    def __init__(
        self,
        relational_pool: RelationalPool,
        cache: CachePool,
        graph_writer: Neo4jWriter,
        vector_repo: VectorRepo,
        article_repo: ArticleRepo,
        source_authority_repo: SourceAuthorityRepo,
        pending_sync_repo: PendingSyncRepo,
        pipeline: Any = None,
        settings: SchedulerSettings | None = None,
        llm_failure_repo: Any = None,
        url_validator: Any = None,
        knowledge_cache: Any = None,
    ) -> None:
        self._relational_pool = relational_pool
        self._cache = cache
        self._graph_writer = graph_writer
        self._vector_repo = vector_repo
        self._article_repo = article_repo
        self._source_authority_repo = source_authority_repo
        self._pending_sync_repo = pending_sync_repo
        self._retry_queue = RetryQueue(cache)
        self._pipeline = pipeline
        self._settings_impl = settings or SchedulerSettings()
        self._llm_failure_repo = llm_failure_repo
        self._url_validator = url_validator
        self._knowledge_cache = knowledge_cache

        # Compose sub-class job handlers with shared dependencies.
        self._consistency_jobs = ConsistencyJobs(
            relational_pool=relational_pool,
            cache=cache,
            graph_writer=graph_writer,
            vector_repo=vector_repo,
            article_repo=article_repo,
            pending_sync_repo=pending_sync_repo,
            pipeline=pipeline,
            settings=self._settings_impl,
        )
        self._maintenance_jobs = MaintenanceJobs(
            relational_pool=relational_pool,
            graph_writer=graph_writer,
            pending_sync_repo=pending_sync_repo,
            vector_repo=vector_repo,
            llm_failure_repo=llm_failure_repo,
            settings=self._settings_impl,
        )
        self._analytics_jobs = AnalyticsJobs(
            relational_pool=relational_pool,
            cache=cache,
            url_validator=url_validator,
            pipeline=pipeline,
            article_repo=article_repo,
            settings=self._settings_impl,
            knowledge_cache=knowledge_cache,
            consistency_jobs=self._consistency_jobs,
        )

    # ── Settings propagation ────────────────────────────────────────
    # Tests and external callers may reassign `jobs._settings` after
    # construction; propagate the new value to all sub-classes so they
    # observe the updated configuration.
    @property
    def _settings(self) -> SchedulerSettings:
        return self._settings_impl

    @_settings.setter
    def _settings(self, value: SchedulerSettings) -> None:
        self._settings_impl = value
        self._consistency_jobs._settings = value
        self._maintenance_jobs._settings = value
        self._analytics_jobs._settings = value

    # ── ConsistencyJobs delegation ───────────────────────────────────
    async def retry_neo4j_writes(self) -> int:
        """Delegate to ConsistencyJobs.retry_neo4j_writes."""
        return await self._consistency_jobs.retry_neo4j_writes()

    async def flush_retry_queue(self) -> int:
        """Delegate to ConsistencyJobs.flush_retry_queue."""
        return await self._consistency_jobs.flush_retry_queue()

    async def sync_neo4j_with_postgres(self) -> dict[str, Any]:
        """Delegate to ConsistencyJobs.sync_neo4j_with_postgres."""
        return await self._consistency_jobs.sync_neo4j_with_postgres()

    async def _entity_consistency_check(self) -> None:
        """Delegate to ConsistencyJobs._entity_consistency_check."""
        await self._consistency_jobs._entity_consistency_check()

    async def retry_pipeline_processing(self) -> int:
        """Delegate to ConsistencyJobs.retry_pipeline_processing."""
        return await self._consistency_jobs.retry_pipeline_processing()

    async def sync_pending_to_neo4j(self) -> int:
        """Delegate to ConsistencyJobs.sync_pending_to_neo4j."""
        return await self._consistency_jobs.sync_pending_to_neo4j()

    async def consistency_check(self) -> dict[str, Any]:
        """Delegate to ConsistencyJobs.consistency_check."""
        return await self._consistency_jobs.consistency_check()

    async def _get_recent_success_rate(self) -> float:
        """Delegate to ConsistencyJobs._get_recent_success_rate."""
        return await self._consistency_jobs._get_recent_success_rate()

    async def _reconstruct_state(self, article: Article) -> dict:
        """Delegate to ConsistencyJobs._reconstruct_state."""
        return await self._consistency_jobs._reconstruct_state(article)

    # ── MaintenanceJobs delegation ───────────────────────────────────
    async def archive_old_neo4j_nodes(self) -> int:
        """Delegate to MaintenanceJobs.archive_old_neo4j_nodes."""
        return await self._maintenance_jobs.archive_old_neo4j_nodes()

    async def cleanup_orphan_entity_vectors(self) -> int:
        """Delegate to MaintenanceJobs.cleanup_orphan_entity_vectors."""
        return await self._maintenance_jobs.cleanup_orphan_entity_vectors()

    async def cleanup_old_synced(self) -> int:
        """Delegate to MaintenanceJobs.cleanup_old_synced."""
        return await self._maintenance_jobs.cleanup_old_synced()

    async def llm_failure_cleanup(self) -> int:
        """Delegate to MaintenanceJobs.llm_failure_cleanup."""
        return await self._maintenance_jobs.llm_failure_cleanup()

    async def llm_usage_raw_cleanup(self) -> int:
        """Delegate to MaintenanceJobs.llm_usage_raw_cleanup."""
        return await self._maintenance_jobs.llm_usage_raw_cleanup()

    # ── AnalyticsJobs delegation ─────────────────────────────────────
    async def aggregate_llm_usage(self) -> int:
        """Delegate to AnalyticsJobs.aggregate_llm_usage."""
        return await self._analytics_jobs.aggregate_llm_usage()

    async def aggregate_llm_compare(self) -> int:
        """Delegate to AnalyticsJobs.aggregate_llm_compare."""
        return await self._analytics_jobs.aggregate_llm_compare()

    async def check_expiring_api_keys(self) -> int:
        """Delegate to AnalyticsJobs.check_expiring_api_keys."""
        return await self._analytics_jobs.check_expiring_api_keys()

    async def sync_phishtank_data(self) -> bool:
        """Delegate to AnalyticsJobs.sync_phishtank_data."""
        return await self._analytics_jobs.sync_phishtank_data()

    async def process_pending_enrichment(self) -> int:
        """Delegate to AnalyticsJobs.process_pending_enrichment."""
        return await self._analytics_jobs.process_pending_enrichment()

    async def generate_daily_briefing(self) -> dict[str, Any]:
        """Delegate to AnalyticsJobs.generate_daily_briefing."""
        return await self._analytics_jobs.generate_daily_briefing()

    async def detect_sentiment_shifts(self) -> list[dict[str, Any]]:
        """Delegate to AnalyticsJobs.detect_sentiment_shifts."""
        return await self._analytics_jobs.detect_sentiment_shifts()

    async def daily_hotness_decay(self) -> int:
        """Delegate to AnalyticsJobs.daily_hotness_decay."""
        return await self._analytics_jobs.daily_hotness_decay()

    async def _fetch_sentiment_signal(self, window_days: int) -> list[float]:
        """Delegate to AnalyticsJobs._fetch_sentiment_signal."""
        return await self._analytics_jobs._fetch_sentiment_signal(window_days)

    # ── Inline jobs (source scoring & metrics) ───────────────────────
    @scheduled_task("update_source_auto_scores", timeout_seconds=600)
    async def update_source_auto_scores(self) -> int:
        """Automatically update source authority scores based on history.

        Analyzes historical articles to calculate average content_check_score
        per source and updates source_authorities.auto_score.

        Returns:
            Number of sources updated.
        """
        log.info("update_source_auto_scores_start")

        async with self._relational_pool.session() as session:
            # Get all sources with articles
            stmt = select(Article.source_host).distinct()
            result = await session.execute(stmt)
            hosts = [row[0] for row in result if row[0]]

            update_count = 0
            for host in hosts:
                try:
                    # Calculate average credibility score for this source
                    avg_stmt = select(Article).where(
                        Article.source_host == host,
                        Article.credibility_score.isnot(None),
                    )
                    articles_result = await session.execute(avg_stmt)
                    articles = articles_result.scalars().all()

                    if articles:
                        avg_score = sum(float(a.credibility_score or 0) for a in articles) / len(
                            articles
                        )

                        # Update source authority
                        await self._source_authority_repo.update_auto_score(host, float(avg_score))
                        update_count += 1

                        log.debug(
                            "source_auto_score_updated",
                            host=host,
                            score=avg_score,
                        )

                except Exception as exc:
                    log.error(
                        "source_auto_score_failed",
                        host=host,
                        error=str(exc),
                    )

        log.info("update_source_auto_scores_complete", count=update_count)
        return update_count

    @scheduled_task("update_persist_status_metrics", timeout_seconds=60)
    async def update_persist_status_metrics(self) -> None:
        """Update Prometheus gauge for article persist status counts.

        Scans the articles table and updates the persist_status_count gauge
        for each status, enabling persistence failure rate alerting.
        """
        from sqlalchemy import func

        log.info("update_persist_status_metrics_start")

        try:
            async with self._relational_pool.session() as session:
                stmt = select(Article.persist_status, func.count(Article.id)).group_by(
                    Article.persist_status
                )
                result = await session.execute(stmt)
                rows = result.all()

                # Reset all status gauges before setting new values
                for status in PersistStatus:
                    metrics.persist_status_count.labels(status=status.value).set(0)

                for row in rows:
                    status_value = row[0].value if hasattr(row[0], "value") else str(row[0])
                    count = row[1]
                    metrics.persist_status_count.labels(status=status_value).set(count)

                log.info(
                    "persist_status_metrics_updated",
                    statuses={row[0].value: row[1] for row in rows},
                )
        except Exception as exc:
            log.error("persist_status_metrics_update_error", error=str(exc))
