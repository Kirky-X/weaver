# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for scheduler jobs dynamic batch sizing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import SchedulerSettings


@pytest.fixture
def scheduler_jobs_with_settings():
    """Create SchedulerJobs instance with custom settings."""
    from modules.scheduler.jobs import SchedulerJobs

    return SchedulerJobs(
        relational_pool=MagicMock(),
        cache=MagicMock(),
        graph_writer=MagicMock(),
        vector_repo=MagicMock(),
        article_repo=MagicMock(),
        source_authority_repo=MagicMock(),
        pending_sync_repo=MagicMock(),
        pipeline=MagicMock(),
        settings=SchedulerSettings(
            pipeline_retry_batch_size=20,
            pipeline_retry_dynamic_batch=True,
            pipeline_retry_success_rate_threshold=0.8,
        ),
    )


@pytest.fixture
def scheduler_jobs_no_dynamic():
    """Create SchedulerJobs instance with dynamic batching disabled."""
    from modules.scheduler.jobs import SchedulerJobs

    return SchedulerJobs(
        relational_pool=MagicMock(),
        cache=MagicMock(),
        graph_writer=MagicMock(),
        vector_repo=MagicMock(),
        article_repo=MagicMock(),
        source_authority_repo=MagicMock(),
        pending_sync_repo=MagicMock(),
        pipeline=MagicMock(),
        settings=SchedulerSettings(
            pipeline_retry_batch_size=20,
            pipeline_retry_dynamic_batch=False,
        ),
    )


class TestGetRecentSuccessRate:
    """Test _get_recent_success_rate method."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            relational_pool=MagicMock(),
            cache=MagicMock(),
            graph_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_get_recent_success_rate_returns_1_0_when_no_data(self, scheduler_jobs):
        """Test returns 1.0 when no data exists in Redis."""
        scheduler_jobs._cache.get = AsyncMock(return_value=None)

        rate = await scheduler_jobs._get_recent_success_rate()

        assert rate == 1.0

    @pytest.mark.asyncio
    async def test_get_recent_success_rate_returns_stored_value(self, scheduler_jobs):
        """Test returns stored success rate from Redis."""
        scheduler_jobs._cache.get = AsyncMock(return_value="0.85")

        rate = await scheduler_jobs._get_recent_success_rate()

        assert rate == 0.85

    @pytest.mark.asyncio
    async def test_get_recent_success_rate_handles_invalid_value(self, scheduler_jobs):
        """Test returns 1.0 for invalid values."""
        scheduler_jobs._cache.get = AsyncMock(return_value="invalid")

        rate = await scheduler_jobs._get_recent_success_rate()

        assert rate == 1.0

    @pytest.mark.asyncio
    async def test_get_recent_success_rate_handles_type_error(self, scheduler_jobs):
        """Test returns 1.0 for type errors."""
        scheduler_jobs._cache.get = AsyncMock(side_effect=TypeError("Unexpected type"))

        rate = await scheduler_jobs._get_recent_success_rate()

        assert rate == 1.0


class TestRetryPipelineProcessingDynamicBatch:
    """Test retry_pipeline_processing with dynamic batching."""

    @pytest.mark.asyncio
    async def test_dynamic_batch_disabled_uses_default_size(self, scheduler_jobs_no_dynamic):
        """Test uses default batch size when dynamic batching disabled."""
        scheduler_jobs_no_dynamic._article_repo.get_pending = AsyncMock(return_value=[MagicMock()])
        scheduler_jobs_no_dynamic._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_no_dynamic._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_no_dynamic._pipeline.process_batch = AsyncMock()

        await scheduler_jobs_no_dynamic.retry_pipeline_processing()

        # Verify default batch size was used
        scheduler_jobs_no_dynamic._article_repo.get_pending.assert_called_once_with(limit=20)

    @pytest.mark.asyncio
    async def test_dynamic_batch_doubles_when_high_success_rate(self, scheduler_jobs_with_settings):
        """Test doubles batch size when success rate >= threshold."""
        # Mock success rate of 0.9 (above 0.8 threshold)
        scheduler_jobs_with_settings._cache.get = AsyncMock(return_value="0.9")
        scheduler_jobs_with_settings._article_repo.get_pending = AsyncMock(
            return_value=[MagicMock()]
        )
        scheduler_jobs_with_settings._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._pipeline.process_batch = AsyncMock()

        await scheduler_jobs_with_settings.retry_pipeline_processing()

        # Verify doubled batch size (20 * 2 = 40)
        scheduler_jobs_with_settings._article_repo.get_pending.assert_called_once_with(limit=40)

    @pytest.mark.asyncio
    async def test_dynamic_batch_halves_when_low_success_rate(self, scheduler_jobs_with_settings):
        """Test halves batch size when success rate < threshold."""
        # Mock success rate of 0.5 (below 0.8 threshold)
        scheduler_jobs_with_settings._cache.get = AsyncMock(return_value="0.5")
        scheduler_jobs_with_settings._article_repo.get_pending = AsyncMock(
            return_value=[MagicMock()]
        )
        scheduler_jobs_with_settings._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._pipeline.process_batch = AsyncMock()

        await scheduler_jobs_with_settings.retry_pipeline_processing()

        # Verify halved batch size (20 // 2 = 10)
        scheduler_jobs_with_settings._article_repo.get_pending.assert_called_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_dynamic_batch_caps_at_max_when_success_high(self, scheduler_jobs_with_settings):
        """Test caps batch size at 50."""
        # Mock success rate of 1.0 (should double to 40, then capped at 50)
        scheduler_jobs_with_settings._cache.get = AsyncMock(return_value="1.0")
        scheduler_jobs_with_settings._article_repo.get_pending = AsyncMock(
            return_value=[MagicMock()]
        )
        scheduler_jobs_with_settings._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._pipeline.process_batch = AsyncMock()

        await scheduler_jobs_with_settings.retry_pipeline_processing()

        # Verify max batch size capped at 50
        scheduler_jobs_with_settings._article_repo.get_pending.assert_called_once_with(limit=40)

    @pytest.mark.asyncio
    async def test_dynamic_batch_caps_at_max_50(self, scheduler_jobs_with_settings):
        """Test caps batch size at 50 when doubling would exceed."""
        from config.settings import SchedulerSettings

        jobs = scheduler_jobs_with_settings
        jobs._settings = SchedulerSettings(
            pipeline_retry_batch_size=30,
            pipeline_retry_dynamic_batch=True,
            pipeline_retry_success_rate_threshold=0.8,
        )
        # Mock success rate of 1.0 (should double to 60, then capped at 50)
        jobs._cache.get = AsyncMock(return_value="1.0")
        jobs._article_repo.get_pending = AsyncMock(return_value=[MagicMock()])
        jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        jobs._article_repo.get_failed_articles = AsyncMock(return_value=[])
        jobs._pipeline.process_batch = AsyncMock()

        await jobs.retry_pipeline_processing()

        # Verify max batch size capped at 50
        jobs._article_repo.get_pending.assert_called_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_dynamic_batch_floors_at_min_when_success_low(self, scheduler_jobs_with_settings):
        """Test floors batch size at 5."""
        from config.settings import SchedulerSettings

        jobs = scheduler_jobs_with_settings
        jobs._settings = SchedulerSettings(
            pipeline_retry_batch_size=6,
            pipeline_retry_dynamic_batch=True,
            pipeline_retry_success_rate_threshold=0.8,
        )
        # Mock success rate of 0.0 (should half to 3, then floored at 5)
        jobs._cache.get = AsyncMock(return_value="0.0")
        jobs._article_repo.get_pending = AsyncMock(return_value=[MagicMock()])
        jobs._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        jobs._article_repo.get_failed_articles = AsyncMock(return_value=[])
        jobs._pipeline.process_batch = AsyncMock()

        await jobs.retry_pipeline_processing()

        # Verify min batch size floored at 5
        jobs._article_repo.get_pending.assert_called_once_with(limit=5)

    @pytest.mark.asyncio
    async def test_dynamic_batch_updates_success_rate_in_redis(self, scheduler_jobs_with_settings):
        """Test updates success rate in Redis after processing."""
        import uuid

        mock_article = MagicMock()
        mock_article.id = uuid.uuid4()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.source_host = "example.com"
        mock_article.task_id = None

        scheduler_jobs_with_settings._cache.get = AsyncMock(return_value=None)
        scheduler_jobs_with_settings._cache.set = AsyncMock()
        scheduler_jobs_with_settings._article_repo.get_pending = AsyncMock(
            return_value=[mock_article]
        )
        scheduler_jobs_with_settings._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._pipeline.process_batch = AsyncMock()

        await scheduler_jobs_with_settings.retry_pipeline_processing()

        # Verify success rate was updated with 1 hour TTL
        scheduler_jobs_with_settings._cache.set.assert_called_once_with(
            "pipeline:retry:success_rate", "1.0", ex=3600
        )

    @pytest.mark.asyncio
    async def test_dynamic_batch_calculates_correct_success_rate(
        self, scheduler_jobs_with_settings
    ):
        """Test success rate is calculated correctly from processing results."""
        import uuid

        # Create 3 articles: 2 succeed, 1 fails
        articles = []
        for _ in range(3):
            mock_article = MagicMock()
            mock_article.id = uuid.uuid4()
            mock_article.source_url = "https://example.com/test"
            mock_article.title = "Test"
            mock_article.body = "Body"
            mock_article.source_host = "example.com"
            mock_article.task_id = None
            articles.append(mock_article)

        scheduler_jobs_with_settings._cache.get = AsyncMock(return_value=None)
        scheduler_jobs_with_settings._cache.set = AsyncMock()
        scheduler_jobs_with_settings._article_repo.get_pending = AsyncMock(return_value=articles)
        scheduler_jobs_with_settings._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_failed_articles = AsyncMock(return_value=[])
        # First 2 succeed, 3rd fails
        scheduler_jobs_with_settings._pipeline.process_batch = AsyncMock(
            side_effect=[None, None, Exception("Process error")]
        )
        scheduler_jobs_with_settings._article_repo.mark_failed = AsyncMock()

        await scheduler_jobs_with_settings.retry_pipeline_processing()

        # Verify success rate was calculated correctly (2/3 = 0.666...)
        call_args = scheduler_jobs_with_settings._cache.set.call_args
        assert call_args is not None
        assert call_args[0][0] == "pipeline:retry:success_rate"
        # Check that rate is approximately 0.67 (with floating point tolerance)
        stored_rate = float(call_args[0][1])
        assert 0.66 < stored_rate < 0.67

    @pytest.mark.asyncio
    async def test_dynamic_batch_no_update_when_no_articles(self, scheduler_jobs_with_settings):
        """Test does not update success rate when no articles processed."""
        scheduler_jobs_with_settings._cache.get = AsyncMock(return_value=None)
        scheduler_jobs_with_settings._cache.set = AsyncMock()
        scheduler_jobs_with_settings._article_repo.get_pending = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_failed_articles = AsyncMock(return_value=[])

        await scheduler_jobs_with_settings.retry_pipeline_processing()

        # Verify success rate was NOT updated
        scheduler_jobs_with_settings._cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_dynamic_batch_no_update_when_disabled(self, scheduler_jobs_no_dynamic):
        """Test does not update success rate when dynamic batching disabled."""
        scheduler_jobs_no_dynamic._cache.get = AsyncMock(return_value=None)
        scheduler_jobs_no_dynamic._cache.set = AsyncMock()
        scheduler_jobs_no_dynamic._article_repo.get_pending = AsyncMock(return_value=[MagicMock()])
        scheduler_jobs_no_dynamic._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_no_dynamic._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_no_dynamic._pipeline.process_batch = AsyncMock()

        await scheduler_jobs_no_dynamic.retry_pipeline_processing()

        # Verify success rate was NOT updated
        scheduler_jobs_no_dynamic._cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_dynamic_batch_default_settings_used(
        self,
    ):
        """Test default SchedulerSettings have correct dynamic batch values."""
        from config.settings import SchedulerSettings

        settings = SchedulerSettings()

        assert settings.pipeline_retry_dynamic_batch is False
        assert settings.pipeline_retry_success_rate_threshold == 0.8
        assert settings.pipeline_retry_batch_size == 20

    @pytest.mark.asyncio
    async def test_dynamic_batch_with_exact_threshold(self, scheduler_jobs_with_settings):
        """Test uses doubled batch size when success rate equals threshold."""
        # Mock success rate exactly at threshold (0.8)
        scheduler_jobs_with_settings._cache.get = AsyncMock(return_value="0.8")
        scheduler_jobs_with_settings._article_repo.get_pending = AsyncMock(
            return_value=[MagicMock()]
        )
        scheduler_jobs_with_settings._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_settings._pipeline.process_batch = AsyncMock()

        await scheduler_jobs_with_settings.retry_pipeline_processing()

        # Verify doubled batch size when success rate >= threshold
        scheduler_jobs_with_settings._article_repo.get_pending.assert_called_once_with(limit=40)
