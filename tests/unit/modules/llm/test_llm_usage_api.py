# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLM usage API endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.endpoints.admin import (
    get_llm_usage,
    get_llm_usage_by_call_point,
    get_llm_usage_by_model,
    get_llm_usage_by_provider,
    get_llm_usage_summary,
)
from api.schemas.llm_usage import (
    LLMUsageByCallPoint,
    LLMUsageByModel,
    LLMUsageByProvider,
    LLMUsageRecord,
    LLMUsageResponse,
    LLMUsageSummary,
)


class TestLLMUsageSchemas:
    """Tests for LLM usage schema models."""

    def test_llm_usage_record_model(self):
        """Test LLMUsageRecord model creation."""
        record = LLMUsageRecord(
            time_bucket=datetime(2024, 1, 15, 10, 0, 0),
            label="default",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            call_count=100,
            input_tokens=50000,
            output_tokens=25000,
            total_tokens=75000,
            latency_avg_ms=500.5,
            latency_min_ms=200.0,
            latency_max_ms=1500.0,
            success_count=98,
            failure_count=2,
        )
        assert record.call_count == 100
        assert record.provider == "anthropic"
        assert record.success_count == 98

    def test_llm_usage_response_model(self):
        """Test LLMUsageResponse model creation."""
        record = LLMUsageRecord(
            time_bucket=datetime(2024, 1, 15, 10, 0, 0),
            label="default",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            call_count=100,
            input_tokens=50000,
            output_tokens=25000,
            total_tokens=75000,
            latency_avg_ms=500.5,
            latency_min_ms=200.0,
            latency_max_ms=1500.0,
            success_count=98,
            failure_count=2,
        )
        response = LLMUsageResponse(records=[record], total=1)
        assert response.total == 1
        assert len(response.records) == 1

    def test_llm_usage_summary_model(self):
        """Test LLMUsageSummary model creation."""
        summary = LLMUsageSummary(
            total_calls=1000,
            total_input_tokens=500000,
            total_output_tokens=250000,
            total_tokens=750000,
            avg_latency_ms=450.5,
            success_rate=0.98,
        )
        assert summary.total_calls == 1000
        assert summary.success_rate == 0.98

    def test_llm_usage_by_provider_model(self):
        """Test LLMUsageByProvider model creation."""
        provider_stat = LLMUsageByProvider(
            provider="anthropic",
            call_count=500,
            total_tokens=300000,
            success_rate=0.99,
        )
        assert provider_stat.provider == "anthropic"
        assert provider_stat.call_count == 500

    def test_llm_usage_by_model_model(self):
        """Test LLMUsageByModel model creation."""
        model_stat = LLMUsageByModel(
            model="claude-3-opus",
            provider="anthropic",
            call_count=300,
            total_tokens=200000,
            success_rate=0.98,
        )
        assert model_stat.model == "claude-3-opus"
        assert model_stat.provider == "anthropic"


class TestGetLLMUsageEndpoint:
    """Tests for GET /admin/llm-usage endpoint."""

    @pytest.mark.asyncio
    async def test_get_llm_usage_default_params(self):
        """Test get_llm_usage with default parameters."""
        mock_repo = MagicMock()
        mock_repo.query_hourly = AsyncMock(
            return_value=[
                {
                    "time_bucket": "2024-01-15T10:00:00",
                    "call_count": 100,
                    "input_tokens_sum": 50000,
                    "output_tokens_sum": 25000,
                    "total_tokens_sum": 75000,
                    "latency_avg_ms": 500.5,
                    "latency_min_ms": 200.0,
                    "latency_max_ms": 1500.0,
                    "success_count": 98,
                    "failure_count": 2,
                }
            ]
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage(
            from_=from_time,
            to=to_time,
            granularity="hourly",
            provider=None,
            model=None,
            llm_type=None,
            call_point=None,
            _="test-key",
            repo=mock_repo,
        )

        assert result.data.total == 1
        assert len(result.data.records) == 1
        mock_repo.query_hourly.assert_called_once_with(
            start_time=from_time,
            end_time=to_time,
            granularity="hourly",
            provider=None,
            model=None,
            llm_type=None,
            call_point=None,
        )

    @pytest.mark.asyncio
    async def test_get_llm_usage_with_filters(self):
        """Test get_llm_usage with all filters applied."""
        mock_repo = MagicMock()
        mock_repo.query_hourly = AsyncMock(return_value=[])

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage(
            from_=from_time,
            to=to_time,
            granularity="daily",
            provider="anthropic",
            model="claude-3-opus",
            llm_type="chat",
            call_point="classifier",
            _="test-key",
            repo=mock_repo,
        )

        assert result.data.total == 0
        mock_repo.query_hourly.assert_called_once_with(
            start_time=from_time,
            end_time=to_time,
            granularity="daily",
            provider="anthropic",
            model="claude-3-opus",
            llm_type="chat",
            call_point="classifier",
        )

    @pytest.mark.asyncio
    async def test_get_llm_usage_monthly_granularity(self):
        """Test get_llm_usage with monthly granularity."""
        mock_repo = MagicMock()
        mock_repo.query_hourly = AsyncMock(
            return_value=[
                {
                    "time_bucket": "2024-01-01T00:00:00",
                    "call_count": 5000,
                    "input_tokens_sum": 2500000,
                    "output_tokens_sum": 1250000,
                    "total_tokens_sum": 3750000,
                    "latency_avg_ms": 450.0,
                    "latency_min_ms": 100.0,
                    "latency_max_ms": 2000.0,
                    "success_count": 4950,
                    "failure_count": 50,
                }
            ]
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 3, 31, tzinfo=UTC)

        result = await get_llm_usage(
            from_=from_time,
            to=to_time,
            granularity="monthly",
            provider=None,
            model=None,
            llm_type=None,
            call_point=None,
            _="test-key",
            repo=mock_repo,
        )

        assert result.data.total == 1
        mock_repo.query_hourly.assert_called_once()


class TestGetLLMUsageSummaryEndpoint:
    """Tests for GET /admin/llm-usage/summary endpoint."""

    @pytest.mark.asyncio
    async def test_get_llm_usage_summary(self):
        """Test get_llm_usage_summary returns correct statistics."""
        mock_repo = MagicMock()
        mock_repo.get_summary = AsyncMock(
            return_value={
                "total_calls": 1000,
                "total_input_tokens": 500000,
                "total_output_tokens": 250000,
                "total_tokens": 750000,
                "avg_latency_ms": 450.5,
                "max_latency_ms": 2000.0,
                "min_latency_ms": 100.0,
                "success_rate": 0.98,
                "error_types": {"rate_limit": 10, "timeout": 5},
            }
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_summary(
            from_=from_time,
            to=to_time,
            provider=None,
            model=None,
            llm_type=None,
            call_point=None,
            _="test-key",
            repo=mock_repo,
        )

        assert result.data.total_calls == 1000
        assert result.data.total_tokens == 750000
        assert result.data.success_rate == 0.98
        assert result.data.error_types == {"rate_limit": 10, "timeout": 5}

    @pytest.mark.asyncio
    async def test_get_llm_usage_summary_with_filters(self):
        """Test get_llm_usage_summary with filters passed to repo."""
        mock_repo = MagicMock()
        mock_repo.get_summary = AsyncMock(
            return_value={
                "total_calls": 500,
                "total_input_tokens": 250000,
                "total_output_tokens": 125000,
                "total_tokens": 375000,
                "avg_latency_ms": 400.0,
                "success_rate": 1.0,
                "error_types": {},
            }
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_summary(
            from_=from_time,
            to=to_time,
            provider="anthropic",
            model="claude-3-opus",
            llm_type="chat",
            call_point="classifier",
            _="test-key",
            repo=mock_repo,
        )

        mock_repo.get_summary.assert_called_once_with(
            start_time=from_time,
            end_time=to_time,
            provider="anthropic",
            model="claude-3-opus",
            llm_type="chat",
            call_point="classifier",
        )

    @pytest.mark.asyncio
    async def test_get_llm_usage_summary_empty_data(self):
        """Test get_llm_usage_summary with no data in range."""
        mock_repo = MagicMock()
        mock_repo.get_summary = AsyncMock(
            return_value={
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "avg_latency_ms": 0.0,
                "max_latency_ms": 0.0,
                "min_latency_ms": 0.0,
                "success_rate": 1.0,
                "error_types": {},
            }
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_summary(
            from_=from_time,
            to=to_time,
            provider=None,
            model=None,
            llm_type=None,
            call_point=None,
            _="test-key",
            repo=mock_repo,
        )

        assert result.data.total_calls == 0
        assert result.data.success_rate == 1.0


class TestGetLLMUsageByProviderEndpoint:
    """Tests for GET /admin/llm-usage/by-provider endpoint."""

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_provider(self):
        """Test get_llm_usage_by_provider returns provider statistics."""
        mock_repo = MagicMock()
        mock_repo.get_by_provider = AsyncMock(
            return_value=[
                {
                    "provider": "anthropic",
                    "call_count": 500,
                    "total_tokens": 300000,
                    "avg_latency_ms": 400.0,
                    "success_rate": 0.99,
                },
                {
                    "provider": "openai",
                    "call_count": 300,
                    "total_tokens": 200000,
                    "avg_latency_ms": 350.0,
                    "success_rate": 0.98,
                },
            ]
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_provider(
            from_=from_time,
            to=to_time,
            llm_type=None,
            _="test-key",
            repo=mock_repo,
        )

        assert len(result.data) == 2
        assert result.data[0].provider == "anthropic"
        assert result.data[1].provider == "openai"

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_provider_with_llm_type_filter(self):
        """Test get_llm_usage_by_provider with LLM type filter."""
        mock_repo = MagicMock()
        mock_repo.get_by_provider = AsyncMock(
            return_value=[
                {
                    "provider": "anthropic",
                    "call_count": 400,
                    "total_tokens": 250000,
                    "avg_latency_ms": 420.0,
                    "success_rate": 0.98,
                },
            ]
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_provider(
            from_=from_time,
            to=to_time,
            llm_type="chat",
            _="test-key",
            repo=mock_repo,
        )

        mock_repo.get_by_provider.assert_called_once_with(
            start_time=from_time,
            end_time=to_time,
            llm_type="chat",
        )

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_provider_empty(self):
        """Test get_llm_usage_by_provider with no data."""
        mock_repo = MagicMock()
        mock_repo.get_by_provider = AsyncMock(return_value=[])

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_provider(
            from_=from_time,
            to=to_time,
            llm_type=None,
            _="test-key",
            repo=mock_repo,
        )

        assert len(result.data) == 0


class TestGetLLMUsageByModelEndpoint:
    """Tests for GET /admin/llm-usage/by-model endpoint."""

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_model(self):
        """Test get_llm_usage_by_model returns model statistics."""
        mock_repo = MagicMock()
        mock_repo.get_by_model = AsyncMock(
            return_value=[
                {
                    "model": "claude-3-opus",
                    "provider": "anthropic",
                    "call_count": 300,
                    "total_tokens": 200000,
                    "avg_latency_ms": 500.0,
                    "success_rate": 0.99,
                },
                {
                    "model": "gpt-4",
                    "provider": "openai",
                    "call_count": 200,
                    "total_tokens": 150000,
                    "avg_latency_ms": 400.0,
                    "success_rate": 0.98,
                },
            ]
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_model(
            from_=from_time,
            to=to_time,
            provider=None,
            _="test-key",
            repo=mock_repo,
        )

        assert len(result.data) == 2
        assert result.data[0].model == "claude-3-opus"
        assert result.data[0].provider == "anthropic"
        assert result.data[1].model == "gpt-4"

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_model_with_provider_filter(self):
        """Test get_llm_usage_by_model with provider filter."""
        mock_repo = MagicMock()
        mock_repo.get_by_model = AsyncMock(
            return_value=[
                {
                    "model": "claude-3-opus",
                    "provider": "anthropic",
                    "call_count": 300,
                    "total_tokens": 200000,
                    "avg_latency_ms": 500.0,
                    "success_rate": 0.99,
                },
            ]
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_model(
            from_=from_time,
            to=to_time,
            provider="anthropic",
            _="test-key",
            repo=mock_repo,
        )

        mock_repo.get_by_model.assert_called_once_with(
            start_time=from_time,
            end_time=to_time,
            provider="anthropic",
        )

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_model_empty(self):
        """Test get_llm_usage_by_model with no data."""
        mock_repo = MagicMock()
        mock_repo.get_by_model = AsyncMock(return_value=[])

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_model(
            from_=from_time,
            to=to_time,
            provider=None,
            _="test-key",
            repo=mock_repo,
        )

        assert len(result.data) == 0


class TestGetLLMUsageByCallPointEndpoint:
    """Tests for GET /admin/llm-usage/by-call-point endpoint."""

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_call_point(self):
        """Test get_llm_usage_by_call_point returns call point statistics."""
        mock_repo = MagicMock()
        mock_repo.get_by_call_point = AsyncMock(
            return_value=[
                {
                    "call_point": "classifier",
                    "call_count": 500,
                    "total_tokens": 300000,
                    "avg_latency_ms": 300.0,
                    "success_rate": 0.99,
                },
                {
                    "call_point": "analyzer",
                    "call_count": 300,
                    "total_tokens": 200000,
                    "avg_latency_ms": 500.0,
                    "success_rate": 0.98,
                },
                {
                    "call_point": "entity_extractor",
                    "call_count": 200,
                    "total_tokens": 150000,
                    "avg_latency_ms": 400.0,
                    "success_rate": 0.97,
                },
            ]
        )

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_call_point(
            from_=from_time,
            to=to_time,
            _="test-key",
            repo=mock_repo,
        )

        assert len(result.data) == 3
        assert result.data[0].call_point == "classifier"
        assert result.data[1].call_point == "analyzer"
        assert result.data[2].call_point == "entity_extractor"

    @pytest.mark.asyncio
    async def test_get_llm_usage_by_call_point_empty(self):
        """Test get_llm_usage_by_call_point with no data."""
        mock_repo = MagicMock()
        mock_repo.get_by_call_point = AsyncMock(return_value=[])

        from_time = datetime(2024, 1, 1, tzinfo=UTC)
        to_time = datetime(2024, 1, 31, tzinfo=UTC)

        result = await get_llm_usage_by_call_point(
            from_=from_time,
            to=to_time,
            _="test-key",
            repo=mock_repo,
        )

        assert len(result.data) == 0


class TestLLMUsageRepoDependency:
    """Tests for LLM usage repo dependency injection."""

    def test_get_llm_usage_repo_returns_repo(self):
        """Test get_llm_usage_repo dependency returns repo from Endpoints."""
        from api.endpoints._deps import Endpoints
        from api.endpoints.admin import get_llm_usage_repo

        mock_repo = MagicMock()
        Endpoints._llm_usage_repo = mock_repo

        result = get_llm_usage_repo()
        assert result == mock_repo

    def test_get_llm_usage_repo_raises_on_not_initialized(self):
        """Test get_llm_usage_repo raises HTTPException when not initialized."""
        from api.endpoints._deps import Endpoints
        from api.endpoints.admin import get_llm_usage_repo

        Endpoints._llm_usage_repo = None

        with pytest.raises(HTTPException) as exc_info:
            get_llm_usage_repo()
        assert exc_info.value.status_code == 503
