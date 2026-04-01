# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for scheduler jobs metrics."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY


class TestRetryPipelineMetrics:
    """Test metrics emission for retry_pipeline_processing."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance with pipeline."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            pipeline=MagicMock(),
        )

    @pytest.fixture(autouse=True)
    def clear_metrics_registry(self):
        """Clear Prometheus registry before and after each test."""
        from core.observability.metrics import metrics

        # Store original metrics
        original_retry_total = metrics.pipeline_retry_total
        original_retry_success = metrics.pipeline_retry_success_total

        yield

        # Restore original metrics to other tests
        metrics.pipeline_retry_total = original_retry_total
        metrics.pipeline_retry_success_total = original_retry_success

    @pytest.mark.asyncio
    async def test_retry_pipeline_emits_started_and_completed_metrics(self, scheduler_jobs):
        """Test that pipeline_retry_total metrics are emitted at start and end."""
        from core.observability.metrics import metrics

        # Setup mocks
        scheduler_jobs._article_repo.get_pending = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_failed_articles = AsyncMock(return_value=[])

        # Get initial metric values
        started_before = metrics.pipeline_retry_total.labels(status="started")._value._value
        completed_before = metrics.pipeline_retry_total.labels(status="completed")._value._value

        await scheduler_jobs.retry_pipeline_processing()

        started_after = metrics.pipeline_retry_total.labels(status="started")._value._value
        completed_after = metrics.pipeline_retry_total.labels(status="completed")._value._value

        # Verify metrics were incremented
        assert started_after == started_before + 1
        assert completed_after == completed_before + 1

    @pytest.mark.asyncio
    async def test_retry_pipeline_emits_pending_success_metric(self, scheduler_jobs):
        """Test that pipeline_retry_success_total is emitted for pending articles."""
        from core.observability.metrics import metrics

        mock_article = MagicMock()
        mock_article.id = MagicMock()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.source_host = "example.com"
        mock_article.task_id = None

        scheduler_jobs._article_repo.get_pending = AsyncMock(return_value=[mock_article])
        scheduler_jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs._pipeline.process_batch = AsyncMock()

        pending_before = metrics.pipeline_retry_success_total.labels(type="pending")._value._value

        await scheduler_jobs.retry_pipeline_processing()

        pending_after = metrics.pipeline_retry_success_total.labels(type="pending")._value._value

        assert pending_after == pending_before + 1

    @pytest.mark.asyncio
    async def test_retry_pipeline_emits_stuck_success_metric(self, scheduler_jobs):
        """Test that pipeline_retry_success_total is emitted for stuck articles."""
        from core.observability.metrics import metrics

        mock_article = MagicMock()
        mock_article.id = MagicMock()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.source_host = "example.com"
        mock_article.task_id = None

        scheduler_jobs._article_repo.get_pending = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[mock_article])
        scheduler_jobs._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs._pipeline.process_batch = AsyncMock()

        stuck_before = metrics.pipeline_retry_success_total.labels(type="stuck")._value._value

        await scheduler_jobs.retry_pipeline_processing()

        stuck_after = metrics.pipeline_retry_success_total.labels(type="stuck")._value._value

        assert stuck_after == stuck_before + 1

    @pytest.mark.asyncio
    async def test_retry_pipeline_emits_failed_success_metric(self, scheduler_jobs):
        """Test that pipeline_retry_success_total is emitted for failed articles."""
        from core.observability.metrics import metrics

        mock_article = MagicMock()
        mock_article.id = MagicMock()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.source_host = "example.com"
        mock_article.task_id = None

        scheduler_jobs._article_repo.get_pending = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_failed_articles = AsyncMock(return_value=[mock_article])
        scheduler_jobs._pipeline.process_batch = AsyncMock()

        failed_before = metrics.pipeline_retry_success_total.labels(type="failed")._value._value

        await scheduler_jobs.retry_pipeline_processing()

        failed_after = metrics.pipeline_retry_success_total.labels(type="failed")._value._value

        assert failed_after == failed_before + 1

    @pytest.mark.asyncio
    async def test_retry_pipeline_emits_multiple_success_metrics(self, scheduler_jobs):
        """Test that multiple success metrics are emitted correctly."""
        from core.observability.metrics import metrics

        mock_article1 = MagicMock()
        mock_article1.id = MagicMock()
        mock_article1.source_url = "https://example.com/test1"
        mock_article1.title = "Test1"
        mock_article1.body = "Body1"
        mock_article1.source_host = "example.com"
        mock_article1.task_id = None

        mock_article2 = MagicMock()
        mock_article2.id = MagicMock()
        mock_article2.source_url = "https://example.com/test2"
        mock_article2.title = "Test2"
        mock_article2.body = "Body2"
        mock_article2.source_host = "example.com"
        mock_article2.task_id = None

        scheduler_jobs._article_repo.get_pending = AsyncMock(return_value=[mock_article1])
        scheduler_jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[mock_article2])
        scheduler_jobs._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs._pipeline.process_batch = AsyncMock()

        pending_before = metrics.pipeline_retry_success_total.labels(type="pending")._value._value
        stuck_before = metrics.pipeline_retry_success_total.labels(type="stuck")._value._value

        await scheduler_jobs.retry_pipeline_processing()

        pending_after = metrics.pipeline_retry_success_total.labels(type="pending")._value._value
        stuck_after = metrics.pipeline_retry_success_total.labels(type="stuck")._value._value

        assert pending_after == pending_before + 1
        assert stuck_after == stuck_before + 1

    @pytest.mark.asyncio
    async def test_retry_pipeline_no_items_still_emits_metrics(self, scheduler_jobs):
        """Test that metrics are emitted even when no items are retried."""
        from core.observability.metrics import metrics

        scheduler_jobs._article_repo.get_pending = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.get_failed_articles = AsyncMock(return_value=[])

        started_before = metrics.pipeline_retry_total.labels(status="started")._value._value
        completed_before = metrics.pipeline_retry_total.labels(status="completed")._value._value

        result = await scheduler_jobs.retry_pipeline_processing()

        started_after = metrics.pipeline_retry_total.labels(status="started")._value._value
        completed_after = metrics.pipeline_retry_total.labels(status="completed")._value._value

        assert result == 0
        assert started_after == started_before + 1
        assert completed_after == completed_before + 1

    @pytest.mark.asyncio
    async def test_retry_pipeline_no_pipeline_no_metrics(self, scheduler_jobs):
        """Test that no metrics are emitted when pipeline is not configured."""
        from modules.scheduler.jobs import SchedulerJobs

        jobs_no_pipeline = SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            pipeline=None,
        )

        from core.observability.metrics import metrics

        started_before = metrics.pipeline_retry_total.labels(status="started")._value._value

        await jobs_no_pipeline.retry_pipeline_processing()

        started_after = metrics.pipeline_retry_total.labels(status="started")._value._value

        # No metric should be emitted when pipeline is not configured
        assert started_after == started_before
