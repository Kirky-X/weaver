# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Extended tests for pipeline endpoint coverage.

This module tests previously uncovered code paths in pipeline.py:
- URL validation logic (lines 381-452)
- Background URL processing error handling (lines 521-533)
- Edge cases and timeout scenarios
"""

from __future__ import annotations

import asyncio
import json
import time
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
    async def test_should_reject_invalid_url_schemes(
        self, url: str, expected_detail: str, mock_settings
    ):
        """Test that non-HTTP/HTTPS schemes are rejected."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

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
            ("http://0.0.0.0/", "0.0.0.0"),  # Test: all interfaces (internal address)
            ("http://[::1]/api", "::1"),
            ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
        ],
    )
    async def test_should_block_internal_host_prefixes(
        self, url: str, blocked_host: str, mock_settings
    ):
        """Test that internal host prefixes are blocked (lines 396-401)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

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
    async def test_should_block_private_ip_addresses(self, url: str, ip_type: str, mock_settings):
        """Test that private IP addresses are blocked (lines 404-414)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert "internal IP" in exc_info.value.detail
        assert "blocked" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_should_block_reserved_ip_addresses(self, mock_settings):
        """Test that reserved IP addresses are blocked."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        # Test reserved address (240.0.0.0/4 range)
        url = "http://240.0.0.1/"

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert "blocked" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_should_block_link_local_ipv6(self, mock_settings):
        """Test that link-local IPv6 addresses are blocked."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        # fe80::/10 is link-local
        url = "http://[fe80::1]/"

        with pytest.raises(HTTPException) as exc_info:
            await _validate_url_for_processing(url, whitelist_mode=False, settings=mock_settings)

        assert exc_info.value.status_code == 403
        assert "blocked" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_should_handle_numeric_hostname_like_ip(self, mock_settings):
        """Test handling of numeric hostnames that look like IPs (lines 418-428)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        # This tests the code path where hostname.replace(".", "").isdigit() is True
        # but the IP validation happens in the nested try-except
        url = "http://192.168.1.1.nip.io/"  # This is a real service, should pass

        # Should not raise exception for valid public hostname
        result = await _validate_url_for_processing(
            url, whitelist_mode=False, settings=mock_settings
        )
        assert result == url

    @pytest.mark.asyncio
    async def test_should_allow_valid_public_url(self, mock_settings):
        """Test that valid public URLs are allowed."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        url = "https://example.com/article/123"
        result = await _validate_url_for_processing(
            url, whitelist_mode=False, settings=mock_settings
        )
        assert result == url

    @pytest.mark.asyncio
    async def test_should_allow_valid_public_url_with_port(self, mock_settings):
        """Test that valid public URLs with ports are allowed."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

        url = "https://example.com:8080/article"
        result = await _validate_url_for_processing(
            url, whitelist_mode=False, settings=mock_settings
        )
        assert result == url

    @pytest.mark.asyncio
    async def test_whitelist_mode_with_empty_domains_raises_error(self, mock_settings):
        """Test whitelist mode with no configured domains (lines 435-439)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

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
        self, url: str, allowed_domains: list[str], should_pass: bool, mock_settings
    ):
        """Test whitelist mode domain matching logic (lines 441-450)."""
        from api.endpoints.content.pipeline import _validate_url_for_processing

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


class TestSafeEchoAndReflectedXSS:
    """Regression tests for pipeline_020: error details SHALL NOT reflect
    raw user input that could carry XSS payloads.

    The fix introduces ``_safe_echo`` which HTML-escapes and truncates
    user-supplied identifiers before they are interpolated into
    ``HTTPException(detail=...)`` strings.
    """

    def test_safe_echo_escapes_script_tag(self) -> None:
        """``<script>`` SHALL be escaped to ``&lt;script&gt;``."""
        from core.security.safe_echo import safe_echo

        raw = "'\"<script>alert(1)</script>"
        sanitized = safe_echo(raw)
        assert "<script>" not in sanitized
        assert "&lt;script&gt;" in sanitized
        assert "'" not in sanitized  # quote=True escapes single quotes too
        assert '"' not in sanitized

    def test_safe_echo_truncates_long_input(self) -> None:
        """Inputs longer than 64 chars SHALL be truncated."""
        from core.security.safe_echo import _MAX_DETAIL_ECHO_LEN, safe_echo

        long_value = "a" * 200
        sanitized = safe_echo(long_value)
        assert len(sanitized) == _MAX_DETAIL_ECHO_LEN

    def test_safe_echo_preserves_safe_input(self) -> None:
        """Plain ASCII identifiers SHALL pass through unchanged."""
        from core.security.safe_echo import safe_echo

        assert safe_echo("reuters") == "reuters"
        assert safe_echo("source-123") == "source-123"

    def test_safe_echo_handles_empty_string(self) -> None:
        """Empty input SHALL return empty string (no crash)."""
        from core.security.safe_echo import safe_echo

        assert safe_echo("") == ""

    def test_safe_echo_never_contains_raw_dangerous_chars(self) -> None:
        """No combination of dangerous chars SHALL appear raw in output."""
        from core.security.safe_echo import safe_echo

        payloads = [
            "<script>",
            "<img src=x onerror=alert(1)>",
            "javascript:alert(1)",
            "'><script>alert(1)</script>",
            '"><svg/onload=alert(1)>',
        ]
        for payload in payloads:
            sanitized = safe_echo(payload)
            assert "<" not in sanitized, f"Raw '<' leaked for payload: {payload!r}"
            assert ">" not in sanitized, f"Raw '>' leaked for payload: {payload!r}"
            assert '"' not in sanitized, f"Raw '\"' leaked for payload: {payload!r}"
            assert "'" not in sanitized, f"Raw '\\'' leaked for payload: {payload!r}"

    @pytest.mark.asyncio
    async def test_trigger_pipeline_xss_source_id_is_escaped(self) -> None:
        """trigger_pipeline SHALL not reflect raw XSS payload from source_id.

        Regression for pipeline_020: previously the error message was
        ``Source ''\"<script>' not found`` (raw reflection). Now the
        detail MUST contain escaped HTML entities instead of raw ``<script>``.
        """
        from api.endpoints.content.pipeline import trigger_pipeline
        from api.schemas.response import APIResponse

        # Build mocks: scheduler returns empty source list so any source_id
        # is "not found".
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[])
        mock_scheduler.list_all_sources = MagicMock(return_value=[])

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_cache.hget = AsyncMock()

        # TriggerRequest with XSS payload
        request = MagicMock()
        request.source_id = "'\"<script>alert(1)</script>"
        request.force = False
        request.max_items = None

        with pytest.raises(HTTPException) as exc_info:
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        detail = exc_info.value.detail
        assert "<script>" not in detail, "Raw XSS payload leaked into detail"
        assert "&lt;script&gt;" in detail, "Payload should be HTML-escaped"
        assert exc_info.value.status_code == 404


class TestTriggerPipelineSourceIds:
    """Regression tests for CRITICAL bug: ``POST /api/v1/pipeline/trigger``
    with body ``{"source_ids": []}`` caused server crash.

    Root cause: ``TriggerRequest`` only had ``source_id`` (singular). The
    unknown ``source_ids`` field was silently ignored, ``source_id`` defaulted
    to ``None``, and the handler triggered *all* enabled sources concurrently
    (up to 18), causing memory exhaustion / process crash.

    Required behaviour after fix:
    - Empty ``source_ids`` → 400 Bad Request ("source_ids cannot be empty")
    - All non-existent ``source_ids`` → 404
    - Partially existing → trigger existing, skip missing (with warning log)
    - ``source_ids`` (plural) takes precedence over ``source_id`` (singular)
    - Trigger executes asynchronously; HTTP request returns immediately
    - Background task exceptions MUST be caught — process must not crash
    - Compatible with PostgreSQL and DuckDB (uses scheduler protocol)
    """

    @pytest.mark.asyncio
    async def test_empty_source_ids_returns_400_bad_request(self) -> None:
        """Body ``{"source_ids": []}`` SHALL return 400 Bad Request.

        Regression for the critical crash bug: previously empty source_ids
        was silently ignored and triggered all sources.
        """
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=[])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[])
        mock_scheduler.trigger_now = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert exc_info.value.status_code == 400
        assert "source_ids cannot be empty" in exc_info.value.detail
        # Critical: scheduler.trigger_now must NOT be called when validation fails
        mock_scheduler.trigger_now.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_source_ids_does_not_trigger_any_source(self) -> None:
        """Empty source_ids MUST NOT trigger any source — not even one."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=[])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        # Simulate 18 enabled sources (the bug scenario)
        mock_sources = []
        for i in range(18):
            mock_src = MagicMock()
            mock_src.id = f"source-{i}"
            mock_sources.append(mock_src)

        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=mock_sources)
        mock_scheduler.list_all_sources = MagicMock(return_value=mock_sources)
        mock_scheduler.trigger_now = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert exc_info.value.status_code == 400
        # Critical regression check: NO source should be triggered
        mock_scheduler.trigger_now.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_nonexistent_source_ids_returns_404(self) -> None:
        """When all source_ids are nonexistent, SHALL return 404."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["ghost-1", "ghost-2"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[])
        mock_scheduler.list_all_sources = MagicMock(return_value=[])
        mock_scheduler.trigger_now = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert exc_info.value.status_code == 404
        mock_scheduler.trigger_now.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_source_ids_triggers_existing_skips_missing(self) -> None:
        """Partially existing source_ids: trigger existing, skip missing."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["existing-1", "missing-1", "existing-2"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_src_1 = MagicMock()
        mock_src_1.id = "existing-1"
        mock_src_2 = MagicMock()
        mock_src_2.id = "existing-2"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src_1, mock_src_2])
        mock_scheduler.list_all_sources = MagicMock(return_value=[mock_src_1, mock_src_2])
        mock_scheduler.trigger_now = AsyncMock()

        task_uuid = uuid.uuid4()
        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            result = await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert result.data.task_id == str(task_uuid)

        # Yield to event loop so background task runs
        await asyncio.sleep(0.05)

        # trigger_now should be called only for existing sources
        assert mock_scheduler.trigger_now.call_count == 2
        called_source_ids = [
            call.args[0] if call.args else call.kwargs.get("source_id")
            for call in mock_scheduler.trigger_now.call_args_list
        ]
        assert "existing-1" in called_source_ids
        assert "existing-2" in called_source_ids
        assert "missing-1" not in called_source_ids

    @pytest.mark.asyncio
    async def test_all_valid_source_ids_triggers_each(self) -> None:
        """All valid source_ids SHALL each be triggered."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["source-a", "source-b"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_src_a = MagicMock()
        mock_src_a.id = "source-a"
        mock_src_b = MagicMock()
        mock_src_b.id = "source-b"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src_a, mock_src_b])
        mock_scheduler.list_all_sources = MagicMock(return_value=[mock_src_a, mock_src_b])
        mock_scheduler.trigger_now = AsyncMock()

        task_uuid = uuid.uuid4()
        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            result = await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert result.data.task_id == str(task_uuid)
        await asyncio.sleep(0.05)
        assert mock_scheduler.trigger_now.call_count == 2

    @pytest.mark.asyncio
    async def test_source_ids_takes_precedence_over_source_id(self) -> None:
        """When both source_id and source_ids provided, source_ids wins."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(
            source_id="legacy-source",
            source_ids=["new-source-1", "new-source-2"],
        )
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_legacy = MagicMock()
        mock_legacy.id = "legacy-source"
        mock_new_1 = MagicMock()
        mock_new_1.id = "new-source-1"
        mock_new_2 = MagicMock()
        mock_new_2.id = "new-source-2"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(
            return_value=[mock_legacy, mock_new_1, mock_new_2]
        )
        mock_scheduler.list_all_sources = MagicMock(
            return_value=[mock_legacy, mock_new_1, mock_new_2]
        )
        mock_scheduler.trigger_now = AsyncMock()

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=uuid.uuid4()):
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        await asyncio.sleep(0.05)

        # legacy-source MUST NOT be triggered (source_ids takes precedence)
        called_source_ids = [
            call.args[0] if call.args else call.kwargs.get("source_id")
            for call in mock_scheduler.trigger_now.call_args_list
        ]
        assert "legacy-source" not in called_source_ids
        assert "new-source-1" in called_source_ids
        assert "new-source-2" in called_source_ids

    @pytest.mark.asyncio
    async def test_no_source_ids_triggers_all_enabled_backward_compat(self) -> None:
        """Neither source_id nor source_ids provided → trigger all enabled (backward compat)."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest()  # All defaults
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_src_1 = MagicMock()
        mock_src_1.id = "source-1"
        mock_src_2 = MagicMock()
        mock_src_2.id = "source-2"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src_1, mock_src_2])
        mock_scheduler.trigger_now = AsyncMock()

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=uuid.uuid4()):
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        await asyncio.sleep(0.05)
        assert mock_scheduler.trigger_now.call_count == 2

    @pytest.mark.asyncio
    async def test_trigger_returns_immediately_without_blocking(self) -> None:
        """HTTP request SHALL return immediately with task_id, not block on crawl.

        Regression for the 30-second curl timeout / server crash: trigger_pipeline
        must not ``await`` the slow crawl directly — it must run in background.
        """
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["source-1"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_src = MagicMock()
        mock_src.id = "source-1"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src])
        mock_scheduler.list_all_sources = MagicMock(return_value=[mock_src])

        # Simulate slow crawl — if trigger_pipeline awaits directly, we'd block
        async def slow_trigger(*args, **kwargs):
            await asyncio.sleep(2.0)

        mock_scheduler.trigger_now = slow_trigger

        task_uuid = uuid.uuid4()
        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=task_uuid):
            start = time.monotonic()
            result = await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )
            elapsed = time.monotonic() - start

        # Should return well under 2 seconds (background task takes 2s)
        assert elapsed < 1.0, f"trigger_pipeline blocked for {elapsed:.2f}s"
        assert result.data.task_id == str(task_uuid)

    @pytest.mark.asyncio
    async def test_background_exception_does_not_crash_process(self) -> None:
        """Exception in scheduler.trigger_now SHALL be caught, not crash the process.

        Regression for the "process disappears" symptom: a single source's
        failure must not propagate out of the background task.
        """
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["source-1"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_src = MagicMock()
        mock_src.id = "source-1"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src])
        mock_scheduler.list_all_sources = MagicMock(return_value=[mock_src])
        mock_scheduler.trigger_now = AsyncMock(
            side_effect=RuntimeError("Simulated catastrophic LLM failure")
        )

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=uuid.uuid4()):
            # MUST NOT raise — exception is contained in background task
            result = await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert result.data.task_id  # Got a task_id immediately

        # Wait for background task to finish failing
        await asyncio.sleep(0.1)

        # Verify status was updated to failed (or completed via gather's
        # return_exceptions=True). Either way, no crash.
        calls = [call.args for call in mock_cache.hset.call_args_list]
        assert len(calls) >= 1
        last_call_data = json.loads(calls[-1][2])
        assert last_call_data["status"] in (
            "failed",
            "completed",
        ), f"Unexpected status: {last_call_data['status']}"

    @pytest.mark.asyncio
    async def test_database_exception_returns_500(self) -> None:
        """Database exception during source lookup SHALL return 500, not crash."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["source-1"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_scheduler = MagicMock()
        # Simulate DB error (PostgreSQL or DuckDB failure)
        mock_scheduler.list_enabled_sources = MagicMock(
            side_effect=RuntimeError("DB connection lost")
        )
        mock_scheduler.trigger_now = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert exc_info.value.status_code == 500
        mock_scheduler.trigger_now.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_source_ids_deduplicated(self) -> None:
        """Duplicate source_ids SHALL be deduplicated — each source triggered once."""
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["source-1", "source-1", "source-2"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_src_1 = MagicMock()
        mock_src_1.id = "source-1"
        mock_src_2 = MagicMock()
        mock_src_2.id = "source-2"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src_1, mock_src_2])
        mock_scheduler.list_all_sources = MagicMock(return_value=[mock_src_1, mock_src_2])
        mock_scheduler.trigger_now = AsyncMock()

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=uuid.uuid4()):
            await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        await asyncio.sleep(0.05)
        # source-1 must only be triggered once (deduplicated)
        assert mock_scheduler.trigger_now.call_count == 2

    @pytest.mark.asyncio
    async def test_scheduler_without_list_all_sources_still_works(self) -> None:
        """Scheduler without list_all_sources method SHALL fall back to enabled sources.

        This ensures compatibility with simplified scheduler mocks and any
        scheduler implementation that only exposes list_enabled_sources.
        """
        from api.endpoints.content.pipeline import TriggerRequest, trigger_pipeline

        request = TriggerRequest(source_ids=["source-1"])
        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()

        mock_src = MagicMock()
        mock_src.id = "source-1"
        mock_scheduler = MagicMock(spec=["list_enabled_sources", "trigger_now"])
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src])
        mock_scheduler.trigger_now = AsyncMock()

        with patch("api.endpoints.content.pipeline.uuid.uuid4", return_value=uuid.uuid4()):
            result = await trigger_pipeline(
                request=request,
                _="test-api-key",
                cache=mock_cache,
                scheduler=mock_scheduler,
            )

        assert result.data.task_id
        await asyncio.sleep(0.05)
        assert mock_scheduler.trigger_now.call_count == 1


class TestTriggerPipelineHTTPIntegration:
    """HTTP-level integration tests using FastAPI TestClient.

    These tests verify the full HTTP request → response cycle, including
    pydantic validation, dependency injection, and HTTP status codes.
    They reproduce the exact bug scenario: ``POST /api/v1/pipeline/trigger``
    with body ``{"source_ids": []}``.
    """

    def test_post_trigger_empty_source_ids_returns_http_400(self) -> None:
        """HTTP POST with body ``{"source_ids": []}`` SHALL return 400.

        This is the regression test for the original critical bug — it
        exercises the full FastAPI stack (pydantic validation + handler)
        and asserts the server returns 400, not 200/500/crash.
        """
        from api.dependencies import get_cache_client, get_source_scheduler
        from api.endpoints.content.pipeline import router
        from tests.helpers import create_test_client

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_cache.hget = AsyncMock(return_value=None)

        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[])
        mock_scheduler.list_all_sources = MagicMock(return_value=[])
        mock_scheduler.trigger_now = AsyncMock()

        client = create_test_client(
            router,
            dependency_overrides={
                get_cache_client: lambda: mock_cache,
                get_source_scheduler: lambda: mock_scheduler,
            },
        )

        # The critical regression scenario: empty source_ids
        response = client.post(
            "/pipeline/trigger",
            json={"source_ids": []},
            headers={"X-API-Key": "test-api-key"},
        )

        assert response.status_code == 400, (
            f"Expected 400 for empty source_ids, got {response.status_code}: {response.text}"
        )
        body = response.json()
        # APIResponse envelope: {"data": {...}, "meta": {...}}
        detail = body.get("detail") or body.get("message") or str(body)
        assert "source_ids cannot be empty" in detail, (
            f"Expected 'source_ids cannot be empty' in response, got: {body}"
        )
        # Critical: scheduler.trigger_now MUST NOT have been called
        mock_scheduler.trigger_now.assert_not_called()

    def test_post_trigger_empty_source_ids_does_not_crash_server(self) -> None:
        """After a 400 response, the server SHALL remain responsive.

        Regression for the "process disappears" symptom — the TestClient
        must still serve subsequent requests after the empty source_ids call.
        """
        from api.dependencies import get_cache_client, get_source_scheduler
        from api.endpoints.content.pipeline import router
        from tests.helpers import create_test_client

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_cache.hget = AsyncMock(return_value=None)

        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[])
        mock_scheduler.list_all_sources = MagicMock(return_value=[])
        mock_scheduler.trigger_now = AsyncMock()

        client = create_test_client(
            router,
            dependency_overrides={
                get_cache_client: lambda: mock_cache,
                get_source_scheduler: lambda: mock_scheduler,
            },
        )

        # First request: empty source_ids → 400
        r1 = client.post(
            "/pipeline/trigger",
            json={"source_ids": []},
            headers={"X-API-Key": "test-api-key"},
        )
        assert r1.status_code == 400

        # Second request: server should still be alive and respond
        r2 = client.post(
            "/pipeline/trigger",
            json={"source_ids": []},
            headers={"X-API-Key": "test-api-key"},
        )
        assert r2.status_code == 400

        # Third request with valid source_ids should also work
        mock_src = MagicMock()
        mock_src.id = "valid-source"
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src])
        mock_scheduler.list_all_sources = MagicMock(return_value=[mock_src])
        r3 = client.post(
            "/pipeline/trigger",
            json={"source_ids": ["valid-source"]},
            headers={"X-API-Key": "test-api-key"},
        )
        assert r3.status_code == 200
        # The server is alive and serving — no crash.

    def test_post_trigger_valid_source_ids_returns_200_with_task_id(self) -> None:
        """HTTP POST with valid source_ids SHALL return 200 with task_id."""
        from api.dependencies import get_cache_client, get_source_scheduler
        from api.endpoints.content.pipeline import router
        from tests.helpers import create_test_client

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_cache.hget = AsyncMock(return_value=None)

        mock_src = MagicMock()
        mock_src.id = "reuters"
        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[mock_src])
        mock_scheduler.list_all_sources = MagicMock(return_value=[mock_src])
        mock_scheduler.trigger_now = AsyncMock()

        client = create_test_client(
            router,
            dependency_overrides={
                get_cache_client: lambda: mock_cache,
                get_source_scheduler: lambda: mock_scheduler,
            },
        )

        response = client.post(
            "/pipeline/trigger",
            json={"source_ids": ["reuters"]},
            headers={"X-API-Key": "test-api-key"},
        )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert "data" in body
        assert "task_id" in body["data"]
        assert body["data"]["task_id"]  # non-empty

    def test_post_trigger_all_nonexistent_returns_http_404(self) -> None:
        """HTTP POST with all nonexistent source_ids SHALL return 404."""
        from api.dependencies import get_cache_client, get_source_scheduler
        from api.endpoints.content.pipeline import router
        from tests.helpers import create_test_client

        mock_cache = MagicMock()
        mock_cache.hset = AsyncMock()
        mock_cache.hget = AsyncMock(return_value=None)

        mock_scheduler = MagicMock()
        mock_scheduler.list_enabled_sources = MagicMock(return_value=[])
        mock_scheduler.list_all_sources = MagicMock(return_value=[])
        mock_scheduler.trigger_now = AsyncMock()

        client = create_test_client(
            router,
            dependency_overrides={
                get_cache_client: lambda: mock_cache,
                get_source_scheduler: lambda: mock_scheduler,
            },
        )

        response = client.post(
            "/pipeline/trigger",
            json={"source_ids": ["ghost-1", "ghost-2"]},
            headers={"X-API-Key": "test-api-key"},
        )

        assert response.status_code == 404
        mock_scheduler.trigger_now.assert_not_called()
