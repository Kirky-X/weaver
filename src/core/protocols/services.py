# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Service layer protocol definitions for cross-module communication.

This module defines Protocol classes for service layer interfaces that
enable loose coupling between modules. Services encapsulate business logic
and provide stable interfaces for other modules to depend on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from datetime import date

    from modules.briefing.models import BriefingResult
    from modules.trend.models import SentimentTrendResult, TrendDetectionResult


@runtime_checkable
class PipelineService(Protocol):
    """Protocol for pipeline processing service.

    This service provides a stable interface for modules that need to
    trigger pipeline processing without depending on internal implementation.

    Implementations:
        - PipelineServiceImpl: Wraps PipelineGraph with a service interface
    """

    async def run_phase3_per_article(
        self,
        article_id: str,
        *,
        force_reprocess: bool = False,
    ) -> dict[str, Any]:
        """Run phase 3 processing for a single article.

        Args:
            article_id: The article ID to process.
            force_reprocess: Force reprocessing even if already processed.

        Returns:
            Processing result with entity extraction status.

        Raises:
            ArticleNotFoundError: If article does not exist.
            ProcessingError: If processing fails.
        """
        ...

    async def get_pipeline_status(self, article_id: str) -> dict[str, Any]:
        """Get the processing status for an article.

        Args:
            article_id: The article ID to check.

        Returns:
            Status dict with phase completion flags.
        """
        ...

    async def run_full_pipeline(
        self,
        url: str,
        *,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        """Run the complete pipeline for a URL.

        Args:
            url: URL to process.
            source_name: Optional source name override.

        Returns:
            Processing result with article ID and status.
        """
        ...


@runtime_checkable
class TaskRegistryService(Protocol):
    """Protocol for background task tracking.

    This service provides a way to track, query, and cancel background
    tasks started by API endpoints.

    Implementations:
        - InMemoryTaskRegistry: In-memory task tracking
    """

    async def register(
        self,
        task_id: str,
        task: Coroutine[Any, Any, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a background task.

        Args:
            task_id: Unique identifier for the task.
            task: The coroutine to track.
            metadata: Optional metadata about the task.
        """
        ...

    async def get_status(self, task_id: str) -> dict[str, Any]:
        """Get the status of a registered task.

        Args:
            task_id: The task ID to query.

        Returns:
            Status dict with 'status', 'progress', 'result', 'error' fields.
        """
        ...

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: The task ID to cancel.

        Returns:
            True if task was cancelled, False if not found or already done.
        """
        ...

    async def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List registered tasks.

        Args:
            status: Filter by status (pending, running, done, cancelled).
            limit: Maximum number of tasks to return.

        Returns:
            List of task status dicts.
        """
        ...


@runtime_checkable
class EmbeddingServiceProtocol(Protocol):
    """Protocol for embedding service.

    Implementations:
        - EmbeddingServiceWrapper: Container-managed embedding service
    """

    async def embed(self, text: str) -> list[float]:
        """Compute embedding for a single text."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for multiple texts."""
        ...

    def is_ready(self) -> bool:
        """Check if the embedding service is ready."""
        ...

    def start_loading(self) -> None:
        """Start loading the model in background."""
        ...


@runtime_checkable
class DeduplicationStrategy(Protocol):
    """Protocol for URL deduplication strategy.

    Implementations:
        - Deduplicator: Two-level cache + DB deduplication
    """

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize a URL for consistent deduplication."""
        ...


@runtime_checkable
class DailyBriefingProtocol(Protocol):
    """Protocol for daily briefing service (R-briefing-001).

    This service provides a stable interface for modules that need to
    generate, fetch, and list daily briefings without depending on the
    concrete implementation (DailyBriefingService, T008).

    Implementations:
        - DailyBriefingService: src/modules/briefing/service.py (T008)

    Used by:
        - T009 briefings endpoint: GET /api/v1/briefings/daily and
          POST /api/v1/briefings/daily/generate depend on this Protocol
          via api.dependencies.get_briefing_service.
        - T010 APScheduler task: generate_daily_briefing calls
          generate_briefing for 4 categories (general/finance/tech/ai).

    Naming (Rule 7 — exposed conflict):
        Parameter name is `date` (not `briefing_date`) per spec
        R-briefing-001. The `date: date` annotation (parameter name
        shadowing type name) is intentional — spec compliance takes
        priority over stylistic preference. BriefingResult field is
        also `date`, keeping Protocol↔DTO naming aligned.
    """

    async def generate_briefing(
        self,
        date: date,
        category: str | None = None,
    ) -> BriefingResult:
        """Generate (or regenerate) a daily briefing for the given date + category.

        Idempotent: same (date, category) replaces any existing briefing.

        Args:
            date: The date to generate the briefing for.
            category: Briefing category — one of {finance, tech, ai, general}.
                None means "综合" (general, no article filter).

        Returns:
            BriefingResult with summary, items, and narrative_mode flag.
            On LLM failure, summary is None but briefing is still persisted
            (Rule 12: best-effort per spec R-briefing-002).
        """
        ...

    async def get_briefing(
        self,
        date: date,
        category: str | None = None,
    ) -> BriefingResult | None:
        """Fetch an existing briefing for the given date + category.

        Args:
            date: The date to fetch.
            category: Briefing category. None means "综合".

        Returns:
            BriefingResult if found, None otherwise.
        """
        ...

    async def list_briefings(
        self,
        date_from: date,
        date_to: date,
    ) -> list[BriefingResult]:
        """List briefings within a date range (inclusive).

        Args:
            date_from: Start date (inclusive).
            date_to: End date (inclusive).

        Returns:
            List of BriefingResult sorted by date descending. Empty list
            if no briefings in the range.
        """
        ...


@runtime_checkable
class SentimentTrendProtocol(Protocol):
    """Protocol for sentiment trend analysis (R-sentiment-001).

    This service provides a stable interface for modules that need to
    analyze sentiment shifts over a time window for an entity or
    community, without depending on the concrete implementation
    (SentimentTrendAnalyzer, T012).

    Implementations:
        - SentimentTrendAnalyzer: src/modules/trend/sentiment.py (T012)

    Used by:
        - T013 trends endpoint: GET /api/v1/trends/sentiment depends on
          this Protocol via api.dependencies.get_sentiment_trend_service.
        - T018 TrendAlertEvaluator: sentiment_shift trigger_type rules
          invoke analyze_trend to detect shifts > threshold.
        - T015 TrendDetector: optional dependency for sentiment_change
          contribution to trend_score (R-trend-005).

    Field semantics (Rule 7 — exposed ambiguity in spec):
        spec R-sentiment-001 lists two list-typed fields ``shifts`` and
        ``list`` in SentimentTrendResult. They serve distinct purposes:
        - ``shifts``: raw shift records from sentiment_shifts table
          (one entry per article-level comparison).
        - ``list``: aggregated trend data points (e.g. daily avg_shift),
          suitable for charting / time-series visualization.
        Both default to empty list when no data is found in the window.
    """

    async def analyze_trend(
        self,
        entity_name: str | None = None,
        community_id: str | None = None,
        window_days: int = 7,
    ) -> SentimentTrendResult:
        """Analyze sentiment shifts for an entity or community over a window.

        Args:
            entity_name: Canonical entity name to filter article-level
                sentiment_shifts (article_id IS NOT NULL). Mutually
                exclusive with community_id — at least one MUST be set
                (spec R-sentiment-001 constraints).
            community_id: Community identifier to filter community-level
                shifts. When given, all entity shifts within the community
                are aggregated.
            window_days: Time window in days (only 7 and 30 are supported
                per spec R-sentiment-001 constraints; other values raise
                ValueError at the implementation layer).

        Returns:
            SentimentTrendResult with raw shifts, aggregated list,
            avg_shift, and trend_direction ('up'/'down'/'stable').

        Raises:
            ValueError: If both entity_name and community_id are None,
                or window_days is not in {7, 30}.
            Exception: On DB error (Rule 12 — fail loud).
        """
        ...


@runtime_checkable
class TrendDetectionProtocol(Protocol):
    """Protocol for trend detection (R-trend-001).

    This service provides a stable interface for modules that need to
    detect trending entities over a time window by analyzing EventNode
    frequency changes and optional sentiment contribution, without
    depending on the concrete implementation (TrendDetector, T015).

    Implementations:
        - TrendDetector: src/modules/trend/detection.py (T015)

    Used by:
        - T016 trends endpoint: GET /api/v1/trends/detection depends on
          this Protocol via api.dependencies.get_trend_detection_service.
        - T018 TrendAlertEvaluator: trend_spike / trend_drop trigger_type
          rules invoke detect_trends to evaluate frequency changes.

    Trend score formula (R-trend-005):
        trend_score = 0.6 * frequency_change + 0.4 * sentiment_change
        When sentiment data is unavailable (analyzer None or entity has
        no sentiment_shifts), trend_score degenerates to frequency_change
        alone (Rule 12 — fail loud, but degrade gracefully on data
        availability rather than raising).

    Direction thresholds (R-trend-005):
        trend_score > 0.2  → 'up'
        trend_score < -0.2 → 'down'
        otherwise         → 'stable'

    Insufficient-data contract (R-trend-003):
        When EventNode count < 50 in the window, returns
        status='insufficient_data', trends=[], list=[]. Does NOT raise —
        data insufficiency is a legitimate state, not an error. The API
        endpoint returns HTTP 200 in this case (R-trend-004).
    """

    async def detect_trends(
        self,
        window_days: int = 7,
        entity_type: str | None = None,
    ) -> TrendDetectionResult:
        """Detect trending entities over a time window (R-trend-002/003).

        Args:
            window_days: Time window in days (7 or 30 per spec constraints;
                other values raise ValueError at the implementation layer).
            entity_type: Optional EventNode.name filter (R-trend-002:
                "按 entity_type 过滤"). None aggregates across all entity
                types.

        Returns:
            TrendDetectionResult with per-entity trends, aggregated
            MENTIONS heat time-series, and status
            ('ok' when EventNode count ≥ 50, 'insufficient_data' otherwise).

        Raises:
            ValueError: If window_days is not in {7, 30}.
            Exception: On graph DB error (Rule 12 — fail loud). Note that
                insufficient data is NOT a DB error and does not raise.
        """
        ...


__all__ = [
    "DailyBriefingProtocol",
    "DeduplicationStrategy",
    "EmbeddingServiceProtocol",
    "PipelineService",
    "SentimentTrendProtocol",
    "TaskRegistryService",
    "TrendDetectionProtocol",
]
