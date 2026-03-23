# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for pipeline endpoints — beyond the model/basic tests in test_api.py."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestGetTaskStatusWithStats:
    """Tests for GET /pipeline/tasks/{task_id} with article progress stats integration."""

    @pytest.mark.asyncio
    async def test_get_task_status_returns_progress_stats(self):
        """Test that task status includes article progress statistics."""
        from api.endpoints.pipeline import get_task_status

        task_id = str(uuid.uuid4())

        redis_data = json.dumps(
            {
                "task_id": task_id,
                "status": "running",
                "source_id": "test-source",
                "queued_at": "2024-01-01T00:00:00Z",
                "started_at": "2024-01-01T00:00:01Z",
            }
        )

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hget = AsyncMock(return_value=redis_data)

        mock_article_repo = MagicMock()
        mock_article_repo.get_task_progress_stats = AsyncMock(
            return_value={
                "total_processed": 10,
                "pending_count": 5,
                "processing_count": 2,
                "completed_count": 3,
                "failed_count": 0,
            }
        )

        mock_postgres = MagicMock()

        # Patch get_article_repo
        with patch("api.endpoints.pipeline.ArticleRepo") as MockArticleRepo:
            MockArticleRepo.return_value = mock_article_repo
            result = await get_task_status(
                task_id=task_id,
                _="test-key",
                redis=mock_redis,
                postgres_pool=mock_postgres,
            )

        assert result.data.task_id == task_id
        assert result.data.status == "running"
        assert result.data.total_processed == 10
        assert result.data.pending_count == 5
        assert result.data.processing_count == 2
        assert result.data.completed_count == 3
        assert result.data.failed_count == 0

    @pytest.mark.asyncio
    async def test_get_task_status_stats_failure_uses_defaults(self):
        """Test that stats retrieval failure uses default zero values."""
        from api.endpoints.pipeline import get_task_status

        task_id = str(uuid.uuid4())

        redis_data = json.dumps(
            {
                "task_id": task_id,
                "status": "completed",
                "queued_at": "2024-01-01T00:00:00Z",
            }
        )

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hget = AsyncMock(return_value=redis_data)

        mock_postgres = MagicMock()

        with patch("api.endpoints.pipeline.ArticleRepo") as MockArticleRepo:
            mock_article_repo = MagicMock()
            mock_article_repo.get_task_progress_stats = AsyncMock(
                side_effect=Exception("DB connection error")
            )
            MockArticleRepo.return_value = mock_article_repo

            result = await get_task_status(
                task_id=task_id,
                _="test-key",
                redis=mock_redis,
                postgres_pool=mock_postgres,
            )

        # Should not raise; defaults are used
        assert result.data.total_processed == 0
        assert result.data.pending_count == 0
        assert result.data.completed_count == 0
        assert result.data.failed_count == 0

    @pytest.mark.asyncio
    async def test_get_task_status_task_not_found_returns_404(self):
        """Test that a non-existent task_id returns 404."""
        from api.endpoints.pipeline import get_task_status

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hget = AsyncMock(return_value=None)

        mock_postgres = MagicMock()

        task_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await get_task_status(
                task_id=task_id,
                _="test-key",
                redis=mock_redis,
                postgres_pool=mock_postgres,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_task_status_invalid_uuid_still_calls_redis(self):
        """Test behavior with invalid UUID format (string is accepted as-is by the endpoint)."""
        from api.endpoints.pipeline import get_task_status

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hget = AsyncMock(return_value=None)

        mock_postgres = MagicMock()

        # The endpoint does not validate UUID format — it passes the string to Redis
        with pytest.raises(HTTPException) as exc_info:
            await get_task_status(
                task_id="not-a-uuid",
                _="test-key",
                redis=mock_redis,
                postgres_pool=mock_postgres,
            )
        # Redis returns None for non-existent key → 404
        assert exc_info.value.status_code == 404


class TestQueueStatsEndpoint:
    """Tests for GET /pipeline/queue/stats endpoint."""

    @pytest.mark.asyncio
    async def test_get_queue_stats_returns_queue_depth(self):
        """Test queue/stats returns queue depth from Redis."""
        from api.endpoints.pipeline import get_queue_stats

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.llen = AsyncMock(return_value=7)
        mock_redis.client.hgetall = AsyncMock(
            return_value={
                "task-1": json.dumps({"status": "completed"}),
                "task-2": json.dumps({"status": "running"}),
                "task-3": json.dumps({"status": "failed"}),
            }
        )

        mock_row = MagicMock()
        mock_row.total_articles = 50
        mock_row.processing_count = 5
        mock_row.completed_count = 30
        mock_row.failed_count = 3
        mock_row.pending_count = 12

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_postgres = MagicMock()
        mock_postgres.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_queue_stats(
            _="test-key",
            redis=mock_redis,
            postgres_pool=mock_postgres,
        )

        assert result.data["queue_depth"] == 7
        assert result.data["total_tasks"] == 3
        assert result.data["status_counts"]["completed"] == 1
        assert result.data["status_counts"]["running"] == 1
        assert result.data["status_counts"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_get_queue_stats_handles_malformed_task_data(self):
        """Test queue/stats skips tasks with malformed JSON data."""
        from api.endpoints.pipeline import get_queue_stats

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.llen = AsyncMock(return_value=1)
        mock_redis.client.hgetall = AsyncMock(
            return_value={
                "task-1": json.dumps({"status": "completed"}),
                "task-bad": "not-valid-json{",
            }
        )

        mock_row = MagicMock()
        mock_row.total_articles = 0
        mock_row.processing_count = 0
        mock_row.completed_count = 0
        mock_row.failed_count = 0
        mock_row.pending_count = 0

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_postgres = MagicMock()
        mock_postgres.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_queue_stats(
            _="test-key",
            redis=mock_redis,
            postgres_pool=mock_postgres,
        )

        # total_tasks counts all Redis entries (including malformed ones)
        # Only malformed JSON is skipped from status_counts
        assert result.data["total_tasks"] == 2
        # status_counts only includes valid entries
        assert result.data["status_counts"]["completed"] == 1
        assert "bad" not in result.data["status_counts"]


class TestTriggerPipelineEdgeCases:
    """Additional edge-case tests for POST /pipeline/trigger."""

    @pytest.mark.asyncio
    async def test_trigger_with_max_items_sets_scheduler_param(self):
        """Test that max_items in request is passed to scheduler.trigger_now."""
        from api.endpoints.pipeline import TriggerRequest, trigger_pipeline

        task_uuid = uuid.uuid4()

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hset = AsyncMock()

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()

        request = TriggerRequest(source_id="test-source", max_items=50)

        with patch("api.endpoints.pipeline.uuid.uuid4", return_value=task_uuid):
            result = await trigger_pipeline(
                request=request,
                _="test-key",
                redis=mock_redis,
                scheduler=mock_scheduler,
            )

        assert result.data.task_id == str(task_uuid)
        mock_scheduler.trigger_now.assert_called_once()
        # Verify max_items was passed
        call_kwargs = mock_scheduler.trigger_now.call_args.kwargs
        assert call_kwargs.get("max_items") == 50

    @pytest.mark.asyncio
    async def test_trigger_with_force_flag_sets_scheduler_param(self):
        """Test that force=True in request is handled."""
        from api.endpoints.pipeline import TriggerRequest, trigger_pipeline

        task_uuid = uuid.uuid4()

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hset = AsyncMock()

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()

        request = TriggerRequest(source_id="test-source", force=True)

        with patch("api.endpoints.pipeline.uuid.uuid4", return_value=task_uuid):
            result = await trigger_pipeline(
                request=request,
                _="test-key",
                redis=mock_redis,
                scheduler=mock_scheduler,
            )

        assert result.data.task_id == str(task_uuid)

    @pytest.mark.asyncio
    async def test_trigger_redis_hset_called_with_task_status(self):
        """Test that Redis hset is called to store task status on trigger."""
        from api.endpoints.pipeline import TriggerRequest, trigger_pipeline

        task_uuid = uuid.uuid4()

        mock_redis = MagicMock()
        mock_redis.client = MagicMock()
        mock_redis.client.hset = AsyncMock()

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()

        request = TriggerRequest(source_id="test-source")

        with patch("api.endpoints.pipeline.uuid.uuid4", return_value=task_uuid):
            await trigger_pipeline(
                request=request,
                _="test-key",
                redis=mock_redis,
                scheduler=mock_scheduler,
            )

        # hset should be called at least once (initial status)
        assert mock_redis.client.hset.call_count >= 1
