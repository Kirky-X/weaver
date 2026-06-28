# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Comprehensive unit tests for admin API endpoints.

Tests cover:
- Authority management (list, update, auto-score refresh)
- LLM failure monitoring (list, stats)
- LLM usage analytics (unified endpoint with all group_by options)
- Article management (deduplication)
- Memory system diagnostics and consolidation
- Error handling and edge cases

Coverage target: 85%+
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.endpoints.admin.articles import DeduplicateResponse, deduplicate_articles
from api.endpoints.admin.authorities import (
    AutoScoreRefreshResponse,
    UpdateAuthorityRequest,
    UpdateAuthorityResponse,
    list_authorities,
    refresh_auto_scores,
    update_authority,
)
from api.endpoints.admin.llm_monitoring import (
    LLMFailureResponse,
    LLMFailureStatsResponse,
    get_llm_failure_stats,
    get_llm_usage_unified,
    list_llm_failures,
)
from api.endpoints.admin.memory import (
    ConsolidationResult,
    MemoryDiagnosticResponse,
    memory_diagnostics,
    trigger_consolidation,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """No-op fixture: slowapi rate limiter has been replaced by Redis token bucket."""
    yield


@pytest.fixture
def mock_request():
    """Create a mock Starlette Request for testing."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_api_key():
    """Mock verified API key."""
    return "test-api-key-12345"


@pytest.fixture
def mock_authority_repo():
    """Mock source authority repository."""
    repo = AsyncMock()
    repo.list_all = AsyncMock(return_value=[])
    repo.get_needs_review = AsyncMock(return_value=[])
    repo.get_or_create = AsyncMock()
    repo.update_authority = AsyncMock()
    repo.update_auto_score = AsyncMock()
    return repo


@pytest.fixture
def mock_llm_failure_repo():
    """Mock LLM failure repository."""
    repo = AsyncMock()
    repo.query = AsyncMock(return_value=[])
    repo.get_stats = AsyncMock(
        return_value={
            "total": 0,
            "by_call_point": {},
            "by_error_type": {},
            "last_failure_at": None,
        }
    )
    return repo


@pytest.fixture
def mock_llm_usage_repo():
    """Mock LLM usage repository."""
    repo = AsyncMock()
    repo.get_summary = AsyncMock(
        return_value={
            "total_calls": 1000,
            "total_input_tokens": 500000,
            "total_output_tokens": 250000,
            "total_tokens": 750000,
            "avg_latency_ms": 450.0,
            "max_latency_ms": 1200.0,
            "min_latency_ms": 100.0,
            "success_rate": 0.98,
            "error_types": {"timeout": 10, "rate_limit": 5},
        }
    )
    repo.query_hourly = AsyncMock(return_value=[])
    repo.get_by_provider = AsyncMock(return_value=[])
    repo.get_by_model = AsyncMock(return_value=[])
    repo.get_by_call_point = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_container():
    """Mock application container."""
    container = MagicMock()
    container.memory_service = None
    container._scheduler = None
    container.source_authority_repo = MagicMock(return_value=AsyncMock())
    return container


@pytest.fixture
def mock_pool():
    """Mock database pool."""
    pool = MagicMock()
    pool.session = MagicMock()
    return pool


@pytest.fixture
def sample_time_range():
    """Sample time range for usage queries."""
    return {
        "from_": datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        "to": datetime(2024, 1, 31, 23, 59, tzinfo=UTC),
    }


# ── Authority Management Tests ───────────────────────────────────


class TestListAuthorities:
    """Tests for GET /admin/authorities endpoint."""

    @pytest.mark.asyncio
    async def test_list_all_authorities(self, mock_api_key, mock_request, mock_authority_repo):
        """Test listing all authorities."""
        mock_authority = MagicMock()
        mock_authority.id = 1
        mock_authority.host = "example.com"
        mock_authority.authority = 0.85
        mock_authority.tier = 2
        mock_authority.description = "News site"
        mock_authority.needs_review = False
        mock_authority.auto_score = 0.82
        mock_authority.updated_at = datetime(2024, 1, 15, tzinfo=UTC)

        mock_authority_repo.list_all.return_value = [mock_authority]

        response = await list_authorities(
            request=mock_request,
            needs_review_only=False,
            _=mock_api_key,
            repo=mock_authority_repo,
        )

        assert response.data is not None
        assert len(response.data) == 1
        assert response.data[0].host == "example.com"
        assert response.data[0].authority == 0.85
        mock_authority_repo.list_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_needs_review_only(self, mock_api_key, mock_request, mock_authority_repo):
        """Test listing only authorities needing review."""
        mock_authority = MagicMock()
        mock_authority.id = 2
        mock_authority.host = "review-needed.com"
        mock_authority.authority = 0.5
        mock_authority.tier = 1
        mock_authority.description = None
        mock_authority.needs_review = True
        mock_authority.auto_score = None
        mock_authority.updated_at = datetime(2024, 1, 10, tzinfo=UTC)

        mock_authority_repo.get_needs_review.return_value = [mock_authority]

        response = await list_authorities(
            request=mock_request,
            needs_review_only=True,
            _=mock_api_key,
            repo=mock_authority_repo,
        )

        assert len(response.data) == 1
        assert response.data[0].needs_review is True
        mock_authority_repo.get_needs_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_empty_authorities(self, mock_api_key, mock_request, mock_authority_repo):
        """Test listing when no authorities exist."""
        mock_authority_repo.list_all.return_value = []

        response = await list_authorities(
            request=mock_request,
            needs_review_only=False,
            _=mock_api_key,
            repo=mock_authority_repo,
        )

        assert len(response.data) == 0


class TestUpdateAuthority:
    """Tests for PATCH /admin/authorities/{host} endpoint."""

    @pytest.mark.asyncio
    async def test_update_authority_score(self, mock_api_key, mock_request, mock_authority_repo):
        """Test updating authority score."""
        existing = MagicMock()
        existing.authority = 0.7
        existing.tier = 2
        mock_authority_repo.get_or_create.return_value = existing

        request = UpdateAuthorityRequest(authority=0.9)

        response = await update_authority(
            mock_request,
            host="example.com",
            body=request,
            _=mock_api_key,
            repo=mock_authority_repo,
        )

        assert response.data.host == "example.com"
        assert response.data.authority == 0.9
        mock_authority_repo.update_authority.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_authority_tier(self, mock_api_key, mock_request, mock_authority_repo):
        """Test updating authority tier."""
        existing = MagicMock()
        existing.authority = 0.8
        existing.tier = 2
        mock_authority_repo.get_or_create.return_value = existing

        request = UpdateAuthorityRequest(tier=3)

        response = await update_authority(
            mock_request,
            host="example.com",
            body=request,
            _=mock_api_key,
            repo=mock_authority_repo,
        )

        assert response.data.tier == 3

    @pytest.mark.asyncio
    async def test_update_authority_description(
        self, mock_api_key, mock_request, mock_authority_repo
    ):
        """Test updating authority description."""
        existing = MagicMock()
        existing.authority = 0.8
        existing.tier = 2
        mock_authority_repo.get_or_create.return_value = existing

        request = UpdateAuthorityRequest(description="Updated description")

        response = await update_authority(
            mock_request,
            host="example.com",
            body=request,
            _=mock_api_key,
            repo=mock_authority_repo,
        )

        assert response.data.description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_authority_multiple_fields(
        self, mock_api_key, mock_request, mock_authority_repo
    ):
        """Test updating multiple fields at once."""
        existing = MagicMock()
        existing.authority = 0.7
        existing.tier = 1
        mock_authority_repo.get_or_create.return_value = existing

        request = UpdateAuthorityRequest(authority=0.95, tier=3, description="Top tier")

        response = await update_authority(
            mock_request,
            host="example.com",
            body=request,
            _=mock_api_key,
            repo=mock_authority_repo,
        )

        assert response.data.authority == 0.95
        assert response.data.tier == 3
        assert response.data.description == "Top tier"

    @pytest.mark.asyncio
    async def test_update_authority_no_fields_raises_error(
        self, mock_api_key, mock_request, mock_authority_repo
    ):
        """Test that updating no fields raises HTTPException."""
        request = UpdateAuthorityRequest()

        with pytest.raises(HTTPException) as exc_info:
            await update_authority(
                mock_request,
                host="example.com",
                body=request,
                _=mock_api_key,
                repo=mock_authority_repo,
            )

        assert exc_info.value.status_code == 400
        assert "At least one field must be updated" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_update_authority_rejects_sqli_host(
        self, mock_api_key, mock_request, mock_authority_repo
    ):
        """SQL-injection host SHALL be rejected with 422 (regression for admin_039)."""
        request = UpdateAuthorityRequest(authority=0.5)

        with pytest.raises(HTTPException) as exc_info:
            await update_authority(
                mock_request,
                host="'OR'1'='1",
                body=request,
                _=mock_api_key,
                repo=mock_authority_repo,
            )

        assert exc_info.value.status_code == 422
        assert "invalid characters" in exc_info.value.detail
        # DB SHALL NOT be touched when host is invalid
        mock_authority_repo.get_or_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_authority_rejects_overlong_host(
        self, mock_api_key, mock_request, mock_authority_repo
    ):
        """Overlong host (>253 chars) SHALL be rejected with 422 (regression for admin_040)."""
        request = UpdateAuthorityRequest(authority=0.5)

        with pytest.raises(HTTPException) as exc_info:
            await update_authority(
                mock_request,
                host="a" * 254 + ".example.com",
                body=request,
                _=mock_api_key,
                repo=mock_authority_repo,
            )

        assert exc_info.value.status_code == 422
        assert "too long" in exc_info.value.detail
        mock_authority_repo.get_or_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_authority_rejects_overlong_label(
        self, mock_api_key, mock_request, mock_authority_repo
    ):
        """Overlong label (>63 chars) SHALL be rejected with 422."""
        request = UpdateAuthorityRequest(authority=0.5)

        with pytest.raises(HTTPException) as exc_info:
            await update_authority(
                mock_request,
                host="a" * 64 + ".example.com",
                body=request,
                _=mock_api_key,
                repo=mock_authority_repo,
            )

        assert exc_info.value.status_code == 422
        assert "label too long" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_update_authority_rejects_underscore_host(
        self, mock_api_key, mock_request, mock_authority_repo
    ):
        """Host with underscore SHALL be rejected with 422 (RFC 1035)."""
        request = UpdateAuthorityRequest(authority=0.5)

        with pytest.raises(HTTPException) as exc_info:
            await update_authority(
                mock_request,
                host="bad_host.example.com",
                body=request,
                _=mock_api_key,
                repo=mock_authority_repo,
            )

        assert exc_info.value.status_code == 422
        assert "invalid characters" in exc_info.value.detail


# ── LLM Failure Monitoring Tests ─────────────────────────────────


class TestLLMFailures:
    """Tests for LLM failure endpoints."""

    @pytest.mark.asyncio
    async def test_list_failures_no_filter(self, mock_api_key, mock_request, mock_llm_failure_repo):
        """Test listing failures without filters."""
        mock_failure = MagicMock()
        mock_failure.id = 1
        mock_failure.call_point = "classifier"
        mock_failure.provider = "openai"
        mock_failure.error_type = "timeout"
        mock_failure.error_detail = "Request timed out"
        mock_failure.article_id = "art-123"
        mock_failure.task_id = "task-456"
        mock_failure.attempt = 2
        mock_failure.fallback_tried = True
        mock_failure.created_at = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)

        mock_llm_failure_repo.query.return_value = [mock_failure]

        response = await list_llm_failures(
            request=mock_request,
            call_point=None,
            status=None,
            since=None,
            limit=50,
            _=mock_api_key,
            repo=mock_llm_failure_repo,
        )

        assert len(response.data) == 1
        assert response.data[0].call_point == "classifier"
        assert response.data[0].error_type == "timeout"

    @pytest.mark.asyncio
    async def test_list_failures_with_filters(
        self, mock_api_key, mock_request, mock_llm_failure_repo
    ):
        """Test listing failures with filters."""
        mock_llm_failure_repo.query.return_value = []

        response = await list_llm_failures(
            request=mock_request,
            call_point="classifier",
            status="timeout",
            since=datetime(2024, 1, 1, tzinfo=UTC),
            limit=100,
            _=mock_api_key,
            repo=mock_llm_failure_repo,
        )

        mock_llm_failure_repo.query.assert_called_once_with(
            call_point="classifier",
            status="timeout",
            since=datetime(2024, 1, 1, tzinfo=UTC),
            limit=100,
        )

    @pytest.mark.asyncio
    async def test_get_failure_stats(self, mock_api_key, mock_request, mock_llm_failure_repo):
        """Test getting failure statistics."""
        mock_llm_failure_repo.get_stats.return_value = {
            "total": 150,
            "by_call_point": {"classifier": 100, "analyzer": 50},
            "by_error_type": {"timeout": 80, "rate_limit": 70},
            "last_failure_at": "2024-01-15T10:30:00Z",
        }

        response = await get_llm_failure_stats(
            request=mock_request,
            since=datetime(2024, 1, 1, tzinfo=UTC),
            _=mock_api_key,
            repo=mock_llm_failure_repo,
        )

        assert response.data.total_failures == 150
        assert response.data.by_call_point["classifier"] == 100
        assert response.data.last_failure_at == "2024-01-15T10:30:00Z"


# ── LLM Usage Analytics Tests ────────────────────────────────────


class TestLLMUsageUnified:
    """Tests for GET /admin/llm-usage unified endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "group_by",
        ["summary", "time", "provider", "model", "call_point"],
    )
    async def test_usage_all_group_types(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range, group_by
    ):
        """Test all group_by options for usage endpoint."""
        response = await get_llm_usage_unified(
            request=mock_request,
            from_=sample_time_range["from_"],
            to=sample_time_range["to"],
            group_by=group_by,
            granularity="hourly",
            provider=None,
            model=None,
            llm_type=None,
            call_point=None,
            _=mock_api_key,
            repo=mock_llm_usage_repo,
        )

        assert response.data is not None
        assert response.data["group_by"] == group_by

    @pytest.mark.asyncio
    async def test_usage_summary_group(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range
    ):
        """Test summary group returns correct metrics."""
        response = await get_llm_usage_unified(
            request=mock_request,
            from_=sample_time_range["from_"],
            to=sample_time_range["to"],
            group_by="summary",
            granularity="hourly",
            _=mock_api_key,
            repo=mock_llm_usage_repo,
        )

        data = response.data
        assert data["total_calls"] == 1000
        assert data["total_tokens"] == 750000
        assert data["success_rate"] == 0.98
        assert "error_types" in data

    @pytest.mark.asyncio
    async def test_usage_time_group(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range
    ):
        """Test time group returns records with time buckets."""
        mock_record = {
            "time_bucket": "2024-01-01T10:00:00",
            "label": "2024-01-01 10:00",
            "call_point": "classifier",
            "llm_type": "chat",
            "provider": "openai",
            "model": "gpt-4",
            "call_count": 50,
            "input_tokens_sum": 25000,
            "output_tokens_sum": 12500,
            "total_tokens_sum": 37500,
            "latency_avg_ms": 450.0,
            "success_count": 48,
            "failure_count": 2,
        }
        mock_llm_usage_repo.query_hourly.return_value = [mock_record]

        response = await get_llm_usage_unified(
            request=mock_request,
            from_=sample_time_range["from_"],
            to=sample_time_range["to"],
            group_by="time",
            granularity="daily",
            _=mock_api_key,
            repo=mock_llm_usage_repo,
        )

        assert len(response.data["records"]) == 1
        assert response.data["total"] == 1
        record = response.data["records"][0]
        assert record["call_count"] == 50

    @pytest.mark.asyncio
    async def test_usage_provider_group(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range
    ):
        """Test provider group returns provider breakdown."""
        mock_record = {
            "provider": "openai",
            "call_count": 700,
            "input_tokens": 350000,
            "output_tokens": 175000,
            "total_tokens": 525000,
            "avg_latency_ms": 420.0,
            "success_rate": 0.99,
        }
        mock_llm_usage_repo.get_by_provider.return_value = [mock_record]

        response = await get_llm_usage_unified(
            request=mock_request,
            from_=sample_time_range["from_"],
            to=sample_time_range["to"],
            group_by="provider",
            _=mock_api_key,
            repo=mock_llm_usage_repo,
        )

        assert len(response.data["records"]) == 1
        assert response.data["records"][0]["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_usage_model_group(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range
    ):
        """Test model group returns model breakdown."""
        mock_record = {
            "model": "gpt-4",
            "provider": "openai",
            "call_count": 500,
            "input_tokens": 250000,
            "output_tokens": 125000,
            "total_tokens": 375000,
            "avg_latency_ms": 480.0,
            "success_rate": 0.97,
        }
        mock_llm_usage_repo.get_by_model.return_value = [mock_record]

        response = await get_llm_usage_unified(
            request=mock_request,
            from_=sample_time_range["from_"],
            to=sample_time_range["to"],
            group_by="model",
            provider="openai",
            _=mock_api_key,
            repo=mock_llm_usage_repo,
        )

        assert response.data["records"][0]["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_usage_call_point_group(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range
    ):
        """Test call_point group returns call point breakdown."""
        mock_record = {
            "call_point": "classifier",
            "call_count": 400,
            "total_tokens": 200000,
            "avg_latency_ms": 350.0,
            "success_rate": 0.98,
        }
        mock_llm_usage_repo.get_by_call_point.return_value = [mock_record]

        response = await get_llm_usage_unified(
            request=mock_request,
            from_=sample_time_range["from_"],
            to=sample_time_range["to"],
            group_by="call_point",
            _=mock_api_key,
            repo=mock_llm_usage_repo,
        )

        assert response.data["records"][0]["call_point"] == "classifier"

    @pytest.mark.asyncio
    async def test_usage_with_filters(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range
    ):
        """Test usage endpoint with various filters."""
        await get_llm_usage_unified(
            request=mock_request,
            from_=sample_time_range["from_"],
            to=sample_time_range["to"],
            group_by="summary",
            granularity="hourly",
            provider="openai",
            model="gpt-4",
            llm_type="chat",
            call_point="classifier",
            _=mock_api_key,
            repo=mock_llm_usage_repo,
        )

        mock_llm_usage_repo.get_summary.assert_called_once()
        call_kwargs = mock_llm_usage_repo.get_summary.call_args[1]
        assert call_kwargs["provider"] == "openai"
        assert call_kwargs["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_usage_invalid_group_by_raises_error(
        self, mock_api_key, mock_request, mock_llm_usage_repo, sample_time_range
    ):
        """Test that invalid group_by raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            await get_llm_usage_unified(
                request=mock_request,
                from_=sample_time_range["from_"],
                to=sample_time_range["to"],
                group_by="invalid",
                _=mock_api_key,
                repo=mock_llm_usage_repo,
            )

        assert exc_info.value.status_code == 400
        assert "Invalid group_by" in exc_info.value.detail


# ── Article Management Tests ─────────────────────────────────────


class TestArticleDeduplication:
    """Tests for POST /admin/articles/deduplicate endpoint."""

    @pytest.mark.asyncio
    async def test_deduplicate_success(self, mock_api_key, mock_request, mock_pool):
        """Test successful article deduplication."""
        mock_article_repo = MagicMock()
        mock_article_repo.deduplicate_articles = AsyncMock(
            return_value={"removed": 150, "kept": 850}
        )

        with patch(
            "modules.storage.postgres.article_repo.ArticleRepo",
            return_value=mock_article_repo,
        ):
            mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

            response = await deduplicate_articles(
                request=mock_request, _=mock_api_key, pool=mock_pool
            )

            assert response.data.removed == 150
            assert response.data.kept == 850

    @pytest.mark.asyncio
    async def test_deduplicate_no_database_raises_error(self, mock_api_key, mock_request):
        """Test deduplication raises error when database not initialized."""
        with pytest.raises(HTTPException) as exc_info:
            await deduplicate_articles(request=mock_request, _=mock_api_key, pool=None)

        assert exc_info.value.status_code == 503
        assert "Database not initialized" in exc_info.value.detail


# ── Memory System Tests ──────────────────────────────────────────


class TestMemoryDiagnostics:
    """Tests for GET /admin/memory/diagnostics endpoint."""

    @pytest.mark.asyncio
    async def test_diagnostics_service_not_initialized(
        self, mock_api_key, mock_request, mock_container
    ):
        """Test diagnostics when memory service is not initialized."""
        mock_container.memory_diagnostics = AsyncMock(
            return_value={
                "service_initialized": False,
                "temporal_event_count": 0,
                "causal_link_count": 0,
                "pending_consolidation": 0,
                "slow_path_enabled": False,
            }
        )
        mock_container.is_job_registered = MagicMock(return_value=False)

        response = await memory_diagnostics(
            request=mock_request,
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.memory_service_initialized is False
        assert response.data.temporal_event_count == 0
        assert response.data.causal_link_count == 0

    @pytest.mark.asyncio
    async def test_diagnostics_service_initialized(
        self, mock_api_key, mock_request, mock_container
    ):
        """Test diagnostics with initialized memory service."""
        mock_container.memory_diagnostics = AsyncMock(
            return_value={
                "service_initialized": True,
                "temporal_event_count": 1500,
                "causal_link_count": 3000,
                "pending_consolidation": 25,
                "slow_path_enabled": True,
            }
        )
        mock_container.is_job_registered = MagicMock(return_value=True)

        response = await memory_diagnostics(
            request=mock_request,
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.memory_service_initialized is True
        assert response.data.temporal_event_count == 1500
        assert response.data.causal_link_count == 3000
        assert response.data.pending_consolidation == 25
        assert response.data.slow_path_enabled is True
        assert response.data.scheduler_job_registered is True

    @pytest.mark.asyncio
    async def test_diagnostics_query_failure_handled(
        self, mock_api_key, mock_request, mock_container
    ):
        """Test diagnostics handles query failures gracefully."""
        # Container 内部查询失败时返回降级值（失败处理已委托给 container.memory_diagnostics）
        mock_container.memory_diagnostics = AsyncMock(
            return_value={
                "service_initialized": True,
                "temporal_event_count": 0,
                "causal_link_count": 0,
                "pending_consolidation": 0,
                "slow_path_enabled": False,
            }
        )
        mock_container.is_job_registered = MagicMock(return_value=False)

        response = await memory_diagnostics(
            request=mock_request,
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.memory_service_initialized is True
        assert response.data.temporal_event_count == 0


class TestTriggerConsolidation:
    """Tests for POST /admin/memory/trigger-consolidation endpoint."""

    @pytest.mark.asyncio
    async def test_consolidation_success(self, mock_api_key, mock_request, mock_container):
        """Test successful consolidation trigger."""
        mock_ms = MagicMock()
        mock_result = MagicMock()
        mock_result.event_id = "event-123"
        mock_ms.consolidate = AsyncMock(return_value=[mock_result])

        mock_container.memory_service = mock_ms

        response = await trigger_consolidation(
            request=mock_request,
            batch_size=20,
            _=mock_api_key,
            container=mock_container,
        )

        assert response.data.processed == 1
        assert len(response.data.event_ids) == 1
        mock_ms.consolidate.assert_called_once_with(batch_size=20)

    @pytest.mark.asyncio
    async def test_consolidation_no_service_raises_error(
        self, mock_api_key, mock_request, mock_container
    ):
        """Test consolidation raises error when service not initialized."""
        mock_container.memory_service = None

        with pytest.raises(HTTPException) as exc_info:
            await trigger_consolidation(
                request=mock_request,
                batch_size=10,
                _=mock_api_key,
                container=mock_container,
            )

        assert exc_info.value.status_code == 503
        assert "Memory service not initialized" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_consolidation_batch_size_validation(
        self, mock_api_key, mock_request, mock_container
    ):
        """Test consolidation with different batch sizes."""
        mock_ms = MagicMock()
        mock_ms.consolidate = AsyncMock(return_value=[])
        mock_container.memory_service = mock_ms

        for batch_size in [1, 50, 100]:
            await trigger_consolidation(
                request=mock_request,
                batch_size=batch_size,
                _=mock_api_key,
                container=mock_container,
            )
            mock_ms.consolidate.assert_called_with(batch_size=batch_size)


# ── Authority Auto-Score Refresh Tests ───────────────────────────


class TestRefreshAutoScores:
    """Tests for POST /admin/authorities/refresh-auto-scores endpoint."""

    @pytest.mark.asyncio
    async def test_refresh_success_with_articles(
        self, mock_api_key, mock_request, mock_container, mock_pool
    ):
        """Test successful auto-score refresh with articles."""
        mock_repo = AsyncMock()
        mock_container.source_authority_repo.return_value = mock_repo

        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_result1 = MagicMock()
        mock_result1.scalars.return_value.all.return_value = []

        mock_article1 = MagicMock()
        mock_article1.credibility_score = 0.85
        mock_article2 = MagicMock()
        mock_article2.credibility_score = 0.90

        mock_result2 = MagicMock()
        mock_result2.scalars.return_value.all.return_value = [mock_article1, mock_article2]

        mock_session.execute = AsyncMock()
        mock_session.execute.side_effect = [
            MagicMock(__iter__=lambda self: iter([("example.com",), ("test.com",)])),
            mock_result1,
            mock_result2,
        ]

        response = await refresh_auto_scores(
            request=mock_request,
            _=mock_api_key,
            container=mock_container,
            pool=mock_pool,
        )

        assert response.data.sources_updated >= 0
        assert response.data.triggered_at is not None

    @pytest.mark.asyncio
    async def test_refresh_no_database_raises_error(
        self, mock_api_key, mock_request, mock_container
    ):
        """Test refresh raises error when database not initialized."""
        with pytest.raises(HTTPException) as exc_info:
            await refresh_auto_scores(
                request=mock_request,
                _=mock_api_key,
                container=mock_container,
                pool=None,
            )

        assert exc_info.value.status_code == 503
        assert "Database not initialized" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_refresh_handles_individual_errors(
        self, mock_api_key, mock_request, mock_container, mock_pool
    ):
        """Test refresh continues even if individual host fails."""
        mock_repo = AsyncMock()
        mock_repo.update_auto_score = AsyncMock(side_effect=Exception("Update failed"))
        mock_container.source_authority_repo.return_value = mock_repo

        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_session.execute = AsyncMock()
        mock_session.execute.side_effect = [
            MagicMock(__iter__=lambda self: iter([("example.com",)])),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]

        response = await refresh_auto_scores(
            request=mock_request,
            _=mock_api_key,
            container=mock_container,
            pool=mock_pool,
        )

        assert response.data.sources_updated == 0


# ── Response Model Tests ─────────────────────────────────────────


class TestResponseModels:
    """Tests for response model validation."""

    def test_authority_response_model(self):
        """Test AuthorityResponse model."""
        from api.endpoints.admin.authorities import AuthorityResponse

        response = AuthorityResponse(
            id=1,
            host="example.com",
            authority=0.85,
            tier=2,
            description="News site",
            needs_review=False,
            auto_score=0.82,
            updated_at="2024-01-15T00:00:00",
        )
        assert response.host == "example.com"
        assert response.authority == 0.85

    def test_llm_failure_response_model(self):
        """Test LLMFailureResponse model."""
        response = LLMFailureResponse(
            id=1,
            article_id="art-123",
            task_id="task-456",
            call_point="classifier",
            provider="openai",
            error_type="timeout",
            error_message="Request timed out",
            status="timeout",
            attempt=2,
            fallback_tried=True,
            created_at="2024-01-15T10:30:00",
        )
        assert response.call_point == "classifier"
        assert response.fallback_tried is True

    def test_deduplicate_response_model(self):
        """Test DeduplicateResponse model."""
        response = DeduplicateResponse(removed=150, kept=850)
        assert response.removed == 150
        assert response.kept == 850

    def test_memory_diagnostic_response_model(self):
        """Test MemoryDiagnosticResponse model."""
        response = MemoryDiagnosticResponse(
            memory_service_initialized=True,
            temporal_event_count=1500,
            causal_link_count=3000,
            pending_consolidation=25,
            slow_path_enabled=True,
            scheduler_job_registered=True,
        )
        assert response.temporal_event_count == 1500
        assert response.slow_path_enabled is True

    def test_consolidation_result_model(self):
        """Test ConsolidationResult model."""
        response = ConsolidationResult(
            processed=5,
            event_ids=["event-1", "event-2", "event-3"],
        )
        assert response.processed == 5
        assert len(response.event_ids) == 3

    def test_auto_score_refresh_response_model(self):
        """Test AutoScoreRefreshResponse model."""
        response = AutoScoreRefreshResponse(
            sources_updated=10,
            triggered_at="2024-01-15T10:30:00Z",
        )
        assert response.sources_updated == 10
        assert response.sources_updated == 10
