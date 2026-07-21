# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for pipeline endpoints — beyond the model/basic tests in test_api.py."""

from __future__ import annotations

import asyncio
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
        from api.endpoints.content.pipeline import get_task_status

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

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=redis_data)

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
        with patch("api.endpoints.content.pipeline.ArticleRepo") as MockArticleRepo:
            MockArticleRepo.return_value = mock_article_repo
            result = await get_task_status(
                task_id=task_id,
                _="test-key",
                cache=mock_cache,
                relational_pool=mock_postgres,
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
        from api.endpoints.content.pipeline import get_task_status

        task_id = str(uuid.uuid4())

        redis_data = json.dumps(
            {
                "task_id": task_id,
                "status": "completed",
                "queued_at": "2024-01-01T00:00:00Z",
            }
        )

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=redis_data)

        mock_postgres = MagicMock()

        with patch("api.endpoints.content.pipeline.ArticleRepo") as MockArticleRepo:
            mock_article_repo = MagicMock()
            mock_article_repo.get_task_progress_stats = AsyncMock(
                side_effect=Exception("DB connection error")
            )
            MockArticleRepo.return_value = mock_article_repo

            result = await get_task_status(
                task_id=task_id,
                _="test-key",
                cache=mock_cache,
                relational_pool=mock_postgres,
            )

        # Should not raise; defaults are used
        assert result.data.total_processed == 0
        assert result.data.pending_count == 0
        assert result.data.completed_count == 0
        assert result.data.failed_count == 0

    @pytest.mark.asyncio
    async def test_get_task_status_task_not_found_returns_404(self):
        """Test that a non-existent task_id returns 404."""
        from api.endpoints.content.pipeline import get_task_status

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=None)

        mock_postgres = MagicMock()

        task_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await get_task_status(
                task_id=task_id,
                _="test-key",
                cache=mock_cache,
                relational_pool=mock_postgres,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_task_status_invalid_uuid_still_calls_redis(self):
        """Test behavior with invalid UUID format (string is accepted as-is by the endpoint)."""
        from api.endpoints.content.pipeline import get_task_status

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=None)

        mock_postgres = MagicMock()

        # The endpoint does not validate UUID format — it passes the string to Redis
        with pytest.raises(HTTPException) as exc_info:
            await get_task_status(
                task_id="not-a-uuid",
                _="test-key",
                cache=mock_cache,
                relational_pool=mock_postgres,
            )
        # Redis returns None for non-existent key → 404
        assert exc_info.value.status_code == 404


class TestTriggerPipelineEdgeCases:
    """Additional edge-case tests for POST /admin/pipeline/trigger."""

    @pytest.mark.asyncio
    async def test_trigger_with_max_items_sets_scheduler_param(self):
        """Test that max_items in request is passed to scheduler.trigger_now."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        task_uuid = uuid.uuid4()

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        # Atomic lock acquire (CWE-362 fix): set_nx replaces check-then-set
        mock_cache.set_nx = AsyncMock(return_value=True)
        mock_cache.delete = AsyncMock()

        mock_source = MagicMock()
        mock_source.id = "test-source"
        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()
        mock_scheduler.list_enabled_sources.return_value = [mock_source]
        mock_scheduler.list_all_sources.return_value = [mock_source]

        request = TriggerRequest(source_id="test-source", max_items=50)

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            result = await trigger_pipeline(
                request=request,
                _="test-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        # Wait for background task created by asyncio.create_task to execute
        await asyncio.sleep(0.01)

        assert result.data.task_id == str(task_uuid)
        mock_scheduler.trigger_now.assert_called_once()
        # Verify max_items was passed
        call_kwargs = mock_scheduler.trigger_now.call_args.kwargs
        assert call_kwargs.get("max_items") == 50

    @pytest.mark.asyncio
    async def test_trigger_with_force_flag_sets_scheduler_param(self):
        """Test that force=True in request is handled."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        task_uuid = uuid.uuid4()

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        # Atomic lock acquire (CWE-362 fix): set_nx replaces check-then-set
        mock_cache.set_nx = AsyncMock(return_value=True)
        mock_cache.delete = AsyncMock()

        mock_source = MagicMock()
        mock_source.id = "test-source"
        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()
        mock_scheduler.list_enabled_sources.return_value = [mock_source]
        mock_scheduler.list_all_sources.return_value = [mock_source]

        request = TriggerRequest(source_id="test-source", force=True)

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            result = await trigger_pipeline(
                request=request,
                _="test-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert result.data.task_id == str(task_uuid)

    @pytest.mark.asyncio
    async def test_trigger_redis_hset_called_with_task_status(self):
        """Test that Redis hset is called to store task status on trigger."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        task_uuid = uuid.uuid4()

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        # Atomic lock acquire (CWE-362 fix): set_nx replaces check-then-set
        mock_cache.set_nx = AsyncMock(return_value=True)
        mock_cache.delete = AsyncMock()

        mock_source = MagicMock()
        mock_source.id = "test-source"
        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()
        mock_scheduler.list_enabled_sources.return_value = [mock_source]
        mock_scheduler.list_all_sources.return_value = [mock_source]

        request = TriggerRequest(source_id="test-source")

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            await trigger_pipeline(
                request=request,
                _="test-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        # hset should be called at least once (initial status)
        assert mock_cache.hset.call_count >= 1


class TestTriggerPipelineSourceDedup:
    """Tests for per-source dedup lock on POST /pipeline/trigger (vuln-0002 fix)."""

    @pytest.mark.asyncio
    async def test_trigger_returns_409_when_source_already_locked(self):
        """If source lock exists, trigger returns 409 Conflict."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        # set_nx returns False → simulates lock already held by another task
        mock_cache.set_nx = AsyncMock(return_value=False)

        mock_source = MagicMock()
        mock_source.id = "test-source"
        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()
        mock_scheduler.list_enabled_sources.return_value = [mock_source]
        mock_scheduler.list_all_sources.return_value = [mock_source]

        request = TriggerRequest(source_id="test-source")

        with pytest.raises(HTTPException) as exc_info:
            await trigger_pipeline(
                request=request,
                _="test-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert exc_info.value.status_code == 409
        assert "already being processed" in exc_info.value.detail
        # No task should be queued
        assert mock_cache.hset.call_count == 0
        # set_nx must have been attempted (atomic acquire)
        mock_cache.set_nx.assert_called()

    @pytest.mark.asyncio
    async def test_trigger_sets_source_lock_when_not_locked(self):
        """If source is not locked, trigger acquires the lock atomically via set_nx."""
        from api.endpoints.content.pipeline import (
            _SOURCE_LOCK_TTL_SECONDS,
            TriggerRequest,
            trigger_pipeline,
        )

        task_uuid = uuid.uuid4()
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        # set_nx returns True → lock acquired atomically (CWE-362 fix)
        mock_cache.set_nx = AsyncMock(return_value=True)
        mock_cache.delete = AsyncMock()

        mock_source = MagicMock()
        mock_source.id = "test-source"
        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()
        mock_scheduler.list_enabled_sources.return_value = [mock_source]
        mock_scheduler.list_all_sources.return_value = [mock_source]

        request = TriggerRequest(source_id="test-source")

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            await trigger_pipeline(
                request=request,
                _="test-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        await asyncio.sleep(0.05)  # Let background task run

        # Lock should be acquired atomically via set_nx with TTL
        mock_cache.set_nx.assert_called()
        nx_call = mock_cache.set_nx.call_args
        assert "pipeline:source:lock:test-source" in nx_call.args[0]
        assert nx_call.kwargs.get("ex") == _SOURCE_LOCK_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_background_task_releases_lock_on_completion(self):
        """Background task releases source lock after completion."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        task_uuid = uuid.uuid4()
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_cache.set_nx = AsyncMock(return_value=True)
        mock_cache.delete = AsyncMock()

        mock_source = MagicMock()
        mock_source.id = "test-source"
        mock_scheduler = MagicMock()
        mock_scheduler.trigger_now = AsyncMock()
        mock_scheduler.list_enabled_sources.return_value = [mock_source]
        mock_scheduler.list_all_sources.return_value = [mock_source]

        request = TriggerRequest(source_id="test-source")

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            await trigger_pipeline(
                request=request,
                _="test-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        await asyncio.sleep(0.1)  # Wait for background task

        # Lock should be deleted after completion (batch release via *keys)
        mock_cache.delete.assert_called()
        delete_call = mock_cache.delete.call_args
        # All positional args are lock keys — at least one must match prefix
        assert any("pipeline:source:lock:" in str(arg) for arg in delete_call.args)


class TestProcessSingleUrlEndpoint:
    """Tests for POST /pipeline/url endpoint."""

    @pytest.mark.asyncio
    async def test_process_url_returns_task_id(self, mock_settings):
        """Test that processing a URL returns a task ID."""
        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        task_uuid = uuid.uuid4()

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        request = ProcessUrlRequest(url="https://example.com/article/123")

        # Mock URL validation
        with patch(
            "api.endpoints.content.pipeline._validate_url_for_processing",
            return_value="example.com",
        ):
            with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
                with patch("api.endpoints.content.pipeline.asyncio.create_task"):
                    result = await process_single_url(
                        request=request,
                        _="test-key",
                        cache=mock_cache,
                        settings=mock_settings,
                    )

        assert result.data.task_id == str(task_uuid)
        assert result.data.status == "queued"

    @pytest.mark.asyncio
    async def test_process_url_blocks_ssrf_localhost(self, mock_settings):
        """Test that SSRF URLs are blocked."""
        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        mock_cache = MagicMock()

        request = ProcessUrlRequest(url="http://127.0.0.1/admin")

        # Mock URL validation to raise HTTPException for SSRF
        with patch(
            "api.endpoints.content.pipeline._validate_url_for_processing",
            side_effect=HTTPException(
                status_code=403, detail="Access to internal host '127.0.0.1' is blocked"
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await process_single_url(
                    request=request,
                    _="test-key",
                    cache=mock_cache,
                    settings=mock_settings,
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_process_url_blocks_ssrf_private_ip(self, mock_settings):
        """Test that private IP addresses are blocked."""
        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        mock_cache = MagicMock()

        request = ProcessUrlRequest(url="http://192.168.1.1/")

        # Mock URL validation to raise HTTPException for SSRF
        with patch(
            "api.endpoints.content.pipeline._validate_url_for_processing",
            side_effect=HTTPException(
                status_code=403, detail="Access to internal IP '192.168.1.1' is blocked"
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await process_single_url(
                    request=request,
                    _="test-key",
                    cache=mock_cache,
                    settings=mock_settings,
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_process_url_blocks_ssrf_aws_metadata(self, mock_settings):
        """Test that AWS metadata endpoint is blocked."""
        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        mock_cache = MagicMock()

        request = ProcessUrlRequest(url="http://169.254.169.254/latest/meta-data/")

        # Mock URL validation to raise HTTPException for SSRF
        with patch(
            "api.endpoints.content.pipeline._validate_url_for_processing",
            side_effect=HTTPException(
                status_code=403, detail="Access to internal IP '169.254.169.254' is blocked"
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await process_single_url(
                    request=request,
                    _="test-key",
                    cache=mock_cache,
                    settings=mock_settings,
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_process_url_whitelist_mode_blocks_non_allowed_domain(self, mock_settings):
        """Test that whitelist mode blocks non-allowed domains."""
        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        mock_cache = MagicMock()
        mock_settings.pipeline_url_endpoint.allowed_domains = ["trusted.com", "news.example.org"]

        request = ProcessUrlRequest(url="https://untrusted.com/article", whitelist_mode=True)

        # Mock URL validation to raise HTTPException for whitelist violation
        with patch(
            "api.endpoints.content.pipeline._validate_url_for_processing",
            side_effect=HTTPException(
                status_code=403, detail="Domain 'untrusted.com' is not in the allowed list"
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await process_single_url(
                    request=request,
                    _="test-key",
                    cache=mock_cache,
                    settings=mock_settings,
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_process_url_whitelist_mode_allows_subdomain(self, mock_settings):
        """Test that whitelist mode allows subdomains of allowed domains."""
        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        task_uuid = uuid.uuid4()

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_settings.pipeline_url_endpoint.allowed_domains = ["example.com"]

        # subdomain.example.com should be allowed
        request = ProcessUrlRequest(url="https://blog.example.com/article", whitelist_mode=True)

        # Mock URL validation to pass
        with patch(
            "api.endpoints.content.pipeline._validate_url_for_processing",
            return_value="blog.example.com",
        ):
            with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
                with patch("api.endpoints.content.pipeline.asyncio.create_task"):
                    result = await process_single_url(
                        request=request,
                        _="test-key",
                        cache=mock_cache,
                        settings=mock_settings,
                    )

        assert result.data.task_id == str(task_uuid)

    @pytest.mark.asyncio
    async def test_process_url_invalid_url_format(self):
        """Test that invalid URL format is rejected."""
        from pydantic import ValidationError

        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        # Missing scheme
        with pytest.raises(ValidationError) as exc_info:
            ProcessUrlRequest(url="example.com/article")

        assert "http or https" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_process_url_file_scheme_rejected(self):
        """Test that file:// scheme is rejected."""
        from pydantic import ValidationError

        from api.endpoints.content.pipeline import ProcessUrlRequest, process_single_url

        with pytest.raises(ValidationError) as exc_info:
            ProcessUrlRequest(url="file:///etc/passwd")

        assert "http or https" in str(exc_info.value).lower()


class TestProcessSingleUrlBackground:
    """Tests for the background URL processing function."""

    @pytest.mark.asyncio
    async def test_background_process_updates_status_to_running(self):
        """Test that background processing updates status to running."""
        from api.endpoints.content.pipeline import _process_single_url

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=b'{"task_id": "test-id"}')
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(return_value=[MagicMock()])

        mock_pipeline = MagicMock()
        mock_pipeline.process_batch = AsyncMock(return_value=[{"article_id": "123"}])

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler
        mock_container.pipeline.return_value = mock_pipeline

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id="test-id",
                cache=mock_cache,
            )

        # Verify status was updated to running and then completed
        assert mock_cache.hset.call_count >= 2

    @pytest.mark.asyncio
    async def test_background_process_handles_fetch_error(self):
        """Test that FetchError is handled and status set to failed."""
        from api.endpoints.content.pipeline import _process_single_url
        from modules.ingestion.fetching.exceptions import FetchError

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=b'{"task_id": "test-id"}')
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(
            return_value=[FetchError(url="https://example.com", message="Connection failed")]
        )

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id="test-id",
                cache=mock_cache,
            )

        # Status should be updated to failed
        calls = [call.args for call in mock_cache.hset.call_args_list]
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] == "failed"
        assert "Connection failed" in last_call_data.get("error", "")
