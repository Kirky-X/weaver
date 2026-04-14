# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Extended tests for pipeline endpoint coverage.

This module tests previously uncovered code paths in pipeline.py:
- URL validation logic (lines 381-452)
- Background URL processing error handling (lines 521-533)
- Edge cases and timeout scenarios
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestURLValidationExtended:
    """Extended tests for _validate_url_for_processing function (lines 381-452)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url,expected_detail",
        [
            (
                "ftp://example.com/file",
                "URL must use http or https protocol",
            ),
            (
                "file:///etc/passwd",
                "URL must use http or https protocol",
            ),
            (
                "javascript:alert(1)",
                "URL must use http or https protocol",
            ),
        ],
    )
    async def test_should_reject_invalid_url_schemes(self, url: str, expected_detail: str):
        """Test that non-HTTP/HTTPS schemes are rejected."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert expected_detail in exc_info.value.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url,blocked_host",
        [
            ("http://localhost/admin", "localhost"),
            ("http://localhost:8080/api", "localhost"),
            ("http://127.0.0.1/", "127.0.0.1"),
            ("http://127.0.0.1:5000/test", "127.0.0.1"),
            ("http://0.0.0.0/", "0.0.0.0"),  # noqa: S104
            ("http://[::1]/api", "::1"),
            ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
        ],
    )
    async def test_should_block_internal_host_prefixes(self, url: str, blocked_host: str):
        """Test that internal host prefixes are blocked (lines 396-401)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert blocked_host in exc_info.value.detail
        assert "blocked" in exc_info.value.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url,ip_type",
        [
            ("http://10.0.0.1/", "private"),
            ("http://10.255.255.255/api", "private"),
            ("http://172.16.0.1/", "private"),
            ("http://172.31.255.255/test", "private"),
            ("http://192.168.0.1/", "private"),
            ("http://192.168.255.255/admin", "private"),
        ],
    )
    async def test_should_block_private_ip_addresses(self, url: str, ip_type: str):
        """Test that private IP addresses are blocked (lines 404-414)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert "internal IP" in exc_info.value.detail
        assert "blocked" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_should_block_reserved_ip_addresses(self):
        """Test that reserved IP addresses are blocked."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        # Test reserved address (240.0.0.0/4 range)
        url = "http://240.0.0.1/"

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert "blocked" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_should_block_link_local_ipv6(self):
        """Test that link-local IPv6 addresses are blocked."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        # fe80::/10 is link-local
        url = "http://[fe80::1]/"

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert "blocked" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_should_handle_numeric_hostname_like_ip(self):
        """Test handling of numeric hostnames that look like IPs (lines 418-428)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        # This tests the code path where hostname.replace(".", "").isdigit() is True
        # but the IP validation happens in the nested try-except
        url = "http://192.168.1.1.nip.io/"  # This is a real service, should pass

        # Should not raise exception for valid public hostname
        result = await _validate_url_for_processing(
            url, whitelist_mode=False, settings=mock_settings
        )
        assert result == url

    @pytest.mark.asyncio
    async def test_should_allow_valid_public_url(self):
        """Test that valid public URLs are allowed."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        url = "https://example.com/article/123"
        result = await _validate_url_for_processing(
            url, whitelist_mode=False, settings=mock_settings
        )
        assert result == url

    @pytest.mark.asyncio
    async def test_should_allow_valid_public_url_with_port(self):
        """Test that valid public URLs with ports are allowed."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = False

        url = "https://example.com:8080/article"
        result = await _validate_url_for_processing(
            url, whitelist_mode=False, settings=mock_settings
        )
        assert result == url

    @pytest.mark.asyncio
    async def test_whitelist_mode_with_empty_domains_raises_error(self):
        """Test whitelist mode with no configured domains (lines 435-439)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = True
        mock_settings.pipeline_url_endpoint.allowed_domains = []

        url = "https://example.com/article"

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=True, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert "no allowed domains configured" in exc_info.value.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url,allowed_domains,should_pass",
        [
            ("https://trusted.com/article", ["trusted.com"], True),
            ("https://news.trusted.com/article", ["trusted.com"], True),
            ("https://deep.sub.trusted.com/", ["trusted.com"], True),
            ("https://untrusted.com/article", ["trusted.com"], False),
            ("https://fake-trusted.com/article", ["trusted.com"], False),
            ("https://example.com/", ["trusted.com", "example.com"], True),
            ("https://blog.example.com/", ["trusted.com", "example.com"], True),
        ],
    )
    async def test_whitelist_mode_domain_validation(
        self, url: str, allowed_domains: list[str], should_pass: bool
    ):
        """Test whitelist mode domain matching logic (lines 441-450)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        mock_settings = MagicMock()
        mock_settings.pipeline_url_endpoint.whitelist_enabled = True
        mock_settings.pipeline_url_endpoint.allowed_domains = allowed_domains

        if should_pass:
            result = await _validate_url_for_processing(
                url, whitelist_mode=True, settings=mock_settings
            )
            assert result == url
        else:
            with pytest.raises(HTTPException) as exc_info:
                await _validate_url_for_processing(url, whitelist_mode=True, settings=mock_settings)
            assert exc_info.value.status_code == 403
            assert "not in the allowed list" in exc_info.value.detail


class TestProcessSingleUrlExtended:
    """Extended tests for _process_single_url function (lines 521-533)."""

    @pytest.mark.asyncio
    async def test_should_handle_crawler_no_results(self):
        """Test handling when crawler returns empty results (line 521)."""
        from api.endpoints.content.pipeline import _process_single_url

        task_id = str(uuid.uuid4())
        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=json.dumps({"task_id": task_id}))
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(return_value=[])

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id=task_id,
                cache=mock_cache,
            )

        # Verify status was updated to failed
        assert mock_cache.hset.call_count >= 2
        calls = [call.args for call in mock_cache.hset.call_args_list]
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] == "failed"
        assert "no results" in last_call_data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_should_handle_pipeline_processing_exception(self):
        """Test exception handling in pipeline processing (lines 541-549)."""
        from api.endpoints.content.pipeline import _process_single_url

        task_id = str(uuid.uuid4())
        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=json.dumps({"task_id": task_id}))
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_article = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        mock_pipeline = MagicMock()
        mock_pipeline.process_batch = AsyncMock(
            side_effect=RuntimeError("Pipeline processing failed")
        )

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler
        mock_container.pipeline.return_value = mock_pipeline

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id=task_id,
                cache=mock_cache,
            )

        # Verify status was updated to failed with error message
        calls = [call.args for call in mock_cache.hset.call_args_list]
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] == "failed"
        assert "Pipeline processing failed" in last_call_data.get("error", "")

    @pytest.mark.asyncio
    async def test_should_handle_crawler_exception(self):
        """Test handling when crawler raises exception."""
        from api.endpoints.content.pipeline import _process_single_url

        task_id = str(uuid.uuid4())
        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=json.dumps({"task_id": task_id}))
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(side_effect=ConnectionError("Network timeout"))

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id=task_id,
                cache=mock_cache,
            )

        # Verify status was updated to failed
        calls = [call.args for call in mock_cache.hset.call_args_list]
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] == "failed"
        assert "Network timeout" in last_call_data.get("error", "")

    @pytest.mark.asyncio
    async def test_should_handle_multiple_pipeline_states(self):
        """Test handling when pipeline returns multiple states."""
        from api.endpoints.content.pipeline import _process_single_url

        task_id = str(uuid.uuid4())
        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=json.dumps({"task_id": task_id}))
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_article = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        mock_pipeline = MagicMock()
        # Return multiple states (batch processing)
        mock_pipeline.process_batch = AsyncMock(
            return_value=[
                {"article_id": "123", "status": "success"},
                {"article_id": "124", "status": "success"},
            ]
        )

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler
        mock_container.pipeline.return_value = mock_pipeline

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id=task_id,
                cache=mock_cache,
            )

        # Should use first state from the batch
        calls = [call.args for call in mock_cache.hset.call_args_list]
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] == "completed"
        assert last_call_data.get("article_id") == "123"

    @pytest.mark.asyncio
    async def test_should_handle_empty_pipeline_states(self):
        """Test handling when pipeline returns empty states list."""
        from api.endpoints.content.pipeline import _process_single_url

        task_id = str(uuid.uuid4())
        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=json.dumps({"task_id": task_id}))
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_article = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        mock_pipeline = MagicMock()
        mock_pipeline.process_batch = AsyncMock(return_value=[])

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler
        mock_container.pipeline.return_value = mock_pipeline

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id=task_id,
                cache=mock_cache,
            )

        # Should still complete successfully with empty state
        calls = [call.args for call in mock_cache.hset.call_args_list]
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_should_include_article_id_in_completion_status(self):
        """Test that article_id is included in completion status (line 538)."""
        from api.endpoints.content.pipeline import _process_single_url

        task_id = str(uuid.uuid4())
        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=json.dumps({"task_id": task_id}))
        mock_cache.hset = AsyncMock()

        mock_crawler = MagicMock()
        mock_article = MagicMock()
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        mock_pipeline = MagicMock()
        mock_pipeline.process_batch = AsyncMock(return_value=[{"article_id": "article-uuid-123"}])

        mock_container = MagicMock()
        mock_container.crawler.return_value = mock_crawler
        mock_container.pipeline.return_value = mock_pipeline

        with patch("container.get_container", return_value=mock_container):
            await _process_single_url(
                url="https://example.com/article",
                task_id=task_id,
                cache=mock_cache,
            )

        # Verify article_id is in the completion status
        calls = [call.args for call in mock_cache.hset.call_args_list]
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] == "completed"
        assert last_call_data.get("article_id") == "article-uuid-123"
        assert "completed_at" in last_call_data


class TestUpdateTaskStatus:
    """Tests for _update_task_status helper function."""

    @pytest.mark.asyncio
    async def test_should_update_existing_task_status(self):
        """Test updating status of existing task."""
        from api.endpoints.content.pipeline import _update_task_status

        existing_data = json.dumps(
            {
                "task_id": "test-id",
                "status": "queued",
                "url": "https://example.com",
            }
        )

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=existing_data)
        mock_cache.hset = AsyncMock()

        await _update_task_status(
            cache=mock_cache,
            task_id="test-id",
            status="running",
            started_at="2024-01-01T00:00:00",
        )

        # Verify hset was called with updated data
        mock_cache.hset.assert_called_once()
        call_args = mock_cache.hset.call_args.args
        updated_data = json.loads(call_args[2])

        assert updated_data["status"] == "running"
        assert updated_data["task_id"] == "test-id"
        assert updated_data["url"] == "https://example.com"  # Preserved
        assert updated_data["started_at"] == "2024-01-01T00:00:00"

    @pytest.mark.asyncio
    async def test_should_create_new_task_status(self):
        """Test creating status for new task."""
        from api.endpoints.content.pipeline import _update_task_status

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=None)
        mock_cache.hset = AsyncMock()

        await _update_task_status(
            cache=mock_cache,
            task_id="new-task-id",
            status="queued",
        )

        mock_cache.hset.assert_called_once()
        call_args = mock_cache.hset.call_args.args
        data = json.loads(call_args[2])

        assert data["task_id"] == "new-task-id"
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_should_merge_extra_fields(self):
        """Test that extra fields are merged into status data."""
        from api.endpoints.content.pipeline import _update_task_status

        mock_cache = MagicMock()
        mock_cache.hget = AsyncMock(return_value=json.dumps({"task_id": "test-id"}))
        mock_cache.hset = AsyncMock()

        await _update_task_status(
            cache=mock_cache,
            task_id="test-id",
            status="completed",
            completed_at="2024-01-01T00:00:00",
            article_id="123",
            custom_field="value",
        )

        call_args = mock_cache.hset.call_args.args
        data = json.loads(call_args[2])

        assert data["status"] == "completed"
        assert data["completed_at"] == "2024-01-01T00:00:00"
        assert data["article_id"] == "123"
        assert data["custom_field"] == "value"
