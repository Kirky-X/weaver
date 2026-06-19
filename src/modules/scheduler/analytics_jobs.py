# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Analytics jobs for scheduler: aggregation, briefing, and signal detection.

Responsibilities:
- Aggregate LLM usage and comparison data from Redis to PostgreSQL
- Check and rotate expiring API keys
- Sync PhishTank phishing URL data
- Process pending enrichment (Pipeline B)
- Generate daily intelligence briefing
- Detect sentiment shifts in community data
- Decay knowledge cache hotness daily
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select

from config.settings import SchedulerSettings
from core.db import Article
from core.observability import get_logger
from modules.scheduler.wrapper import scheduled_task

if TYPE_CHECKING:
    from core.protocols import CachePool, RelationalPool
    from modules.scheduler.consistency_jobs import ConsistencyJobs

log = get_logger(__name__)


class AnalyticsJobs:
    """Scheduler jobs for analytics: aggregation, briefing, and signal detection.

    Handles LLM usage aggregation, API key rotation checks, PhishTank sync,
    daily briefing generation, sentiment shift detection, and knowledge cache
    hotness decay.
    """

    def __init__(
        self,
        relational_pool: RelationalPool,
        cache: CachePool,
        url_validator: Any = None,
        pipeline: Any = None,
        article_repo: Any = None,
        settings: SchedulerSettings | None = None,
        knowledge_cache: Any = None,
        consistency_jobs: ConsistencyJobs | None = None,
    ) -> None:
        self._relational_pool = relational_pool
        self._cache = cache
        self._url_validator = url_validator
        self._pipeline = pipeline
        self._article_repo = article_repo
        self._settings = settings or SchedulerSettings()
        self._knowledge_cache = knowledge_cache
        self._consistency_jobs = consistency_jobs

    @scheduled_task("llm_usage_aggregate", timeout_seconds=300)
    async def aggregate_llm_usage(self) -> int:
        """Aggregate LLM usage data from Redis buffer to PostgreSQL."""
        from modules.analytics.llm_usage.aggregator import flush_usage_buffer

        processed, errors = await flush_usage_buffer(
            cache=self._cache,
            relational_pool=self._relational_pool,
        )
        return processed

    @scheduled_task("llm_compare_aggregate", timeout_seconds=300)
    async def aggregate_llm_compare(self) -> int:
        """Aggregate LLM comparison data from Redis buffer to PostgreSQL."""
        from modules.analytics.llm_compare.aggregator import flush_compare_buffer

        processed, errors = await flush_compare_buffer(
            cache=self._cache,
            relational_pool=self._relational_pool,
        )
        return processed

    @scheduled_task("check_expiring_api_keys", timeout_seconds=300)
    async def check_expiring_api_keys(self) -> int:
        """Check for API keys expiring within 7 days and auto-rotate them.

        Returns:
            Number of keys rotated.
        """
        from core.security import ApiKeyManager

        log.info("check_expiring_api_keys_start")

        try:
            manager = ApiKeyManager(self._relational_pool)
            count = await manager.check_expiring_keys(days_before=7)
            log.info("check_expiring_api_keys_complete", count=count)
            return count
        except Exception as exc:
            log.error("check_expiring_api_keys_failed", error=str(exc))
            return 0

    @scheduled_task("sync_phishtank_data", timeout_seconds=600)
    async def sync_phishtank_data(self) -> bool:
        """Sync PhishTank phishing URL database.

        Downloads the latest PhishTank data and updates the local blacklist.
        This job only runs if URL validator is configured with PhishTank enabled.

        Returns:
            True if sync was successful or skipped, False on error.
        """
        log.info("sync_phishtank_data_start")

        if not self._url_validator:
            log.info("sync_phishtank_data_skipped_no_validator")
            return True

        try:
            await self._url_validator.sync_phishtank()
            log.info("sync_phishtank_data_complete")
            return True
        except Exception as exc:
            log.error("sync_phishtank_data_failed", error=str(exc))
            return False

    async def process_pending_enrichment(self) -> int:
        """Process pending enrichment for stored articles.

        Pipeline B: Enrichment (PG_DONE → NEO4J_DONE)
        This job handles articles that have been stored but need Phase 3 enrichment.

        Returns:
            Number of articles processed.
        """
        if not self._pipeline or not self._article_repo:
            log.warning("process_pending_enrichment_no_pipeline")
            return 0

        log.info("process_pending_enrichment_start")

        # Get articles that need enrichment (stored but not enriched)
        # This delegates to retry_pipeline_processing which handles pending/stuck articles
        if self._consistency_jobs is None:
            log.warning("process_pending_enrichment_no_consistency_jobs")
            return 0
        return await self._consistency_jobs.retry_pipeline_processing()

    @scheduled_task("generate_daily_briefing", timeout_seconds=300)
    async def generate_daily_briefing(self) -> dict[str, Any]:
        """Generate daily intelligence briefing.

        Uses BriefingEngine to analyze recent articles and produce
        a ranked briefing with diversity across categories.

        Returns:
            Dict with briefing_id, date, and items count.
        """
        log.info("generate_daily_briefing_start")

        try:
            from modules.briefing import DailyBriefingEngine

            engine = DailyBriefingEngine(pool=self._relational_pool)
            result = await engine.generate()

            log.info(
                "generate_daily_briefing_complete",
                briefing_id=result.get("id"),
                items=len(result.get("items", [])),
            )
            return result
        except Exception as exc:
            log.error("generate_daily_briefing_failed", error=str(exc))
            return {"error": str(exc)}

    @scheduled_task("detect_sentiment_shifts", timeout_seconds=300)
    async def detect_sentiment_shifts(self) -> list[dict[str, Any]]:
        """Detect sentiment shifts in community data.

        Uses SentimentShiftDetector with PELT + CUSUM dual-layer
        algorithms to identify significant sentiment changes over time.

        Returns:
            List of detected shift points.
        """
        log.info("detect_sentiment_shifts_start")

        try:
            from modules.analytics import SentimentShiftDetector, ShiftConfig

            config = ShiftConfig(
                window_days=self._settings.cleanup_old_synced_days or 14,
            )
            detector = SentimentShiftDetector(config=config)

            # Fetch recent sentiment signal from database
            signal = await self._fetch_sentiment_signal(config.window_days)

            if not signal or len(signal) < config.min_size * 2:
                log.info("detect_sentiment_shifts_insufficient_data")
                return []

            shifts = detector.detect(signal)

            log.info(
                "detect_sentiment_shifts_complete",
                shifts_count=len(shifts),
                signal_length=len(signal),
            )
            return shifts
        except Exception as exc:
            log.error("detect_sentiment_shifts_failed", error=str(exc))
            return []

    @scheduled_task("daily_hotness_decay", timeout_seconds=300)
    async def daily_hotness_decay(self) -> int:
        """Decay knowledge cache hotness daily.

        Executes knowledge_cache.decay_hotness(0.95) to reduce
        hotness of all clusters by 5%, ensuring stale entries
        gradually become eligible for cleanup.

        Returns:
            Number of clusters decayed.
        """
        if self._knowledge_cache is None:
            log.info("daily_hotness_decay_skipped", reason="no_knowledge_cache")
            return 0

        try:
            decayed = await self._knowledge_cache.decay_hotness(0.95)
            log.info("daily_hotness_decay_complete", decayed=decayed)
            return decayed
        except Exception as exc:
            log.error("daily_hotness_decay_failed", error=str(exc))
            return 0

    async def _fetch_sentiment_signal(self, window_days: int) -> list[float]:
        """Fetch daily sentiment scores for shift detection.

        Args:
            window_days: Number of days to look back.

        Returns:
            List of daily sentiment scores (0.0-1.0).
        """
        try:
            from datetime import timedelta

            from sqlalchemy import func

            threshold = datetime.now(UTC) - timedelta(days=window_days)

            async with self._relational_pool.session() as session:
                stmt = (
                    select(
                        func.date(Article.created_at).label("day"),
                        func.avg(Article.credibility_score).label("avg_score"),
                    )
                    .where(
                        and_(
                            Article.created_at >= threshold,
                            Article.credibility_score.isnot(None),
                        )
                    )
                    .group_by(func.date(Article.created_at))
                    .order_by(func.date(Article.created_at))
                )

                result = await session.execute(stmt)
                rows = result.all()

                if not rows:
                    return []

                return [float(row[1] or 0.5) for row in rows]
        except Exception as exc:
            log.error("fetch_sentiment_signal_failed", error=str(exc))
            return []
