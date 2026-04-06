# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLM provider metrics."""

import pytest

from core.llm.metrics import ProviderMetrics


class TestProviderMetrics:
    """Tests for ProviderMetrics."""

    def test_default_values(self):
        """Test default values after initialization."""
        metrics = ProviderMetrics()
        assert metrics.total_requests == 0
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 0
        assert metrics.total_latency_ms == 0.0
        assert metrics.last_request_time == 0.0
        assert metrics.last_error == ""
        assert metrics.last_error_time == 0.0

    def test_success_rate_no_requests(self):
        """Test success rate with no requests."""
        metrics = ProviderMetrics()
        assert metrics.success_rate == 1.0

    def test_success_rate_with_requests(self):
        """Test success rate with requests."""
        metrics = ProviderMetrics()
        metrics.total_requests = 10
        metrics.successful_requests = 8
        assert metrics.success_rate == 0.8

    def test_failure_rate(self):
        """Test failure rate."""
        metrics = ProviderMetrics()
        metrics.total_requests = 10
        metrics.successful_requests = 7
        assert metrics.failure_rate == pytest.approx(0.3)

    def test_avg_latency_no_requests(self):
        """Test average latency with no successful requests."""
        metrics = ProviderMetrics()
        assert metrics.avg_latency_ms == 0.0

    def test_avg_latency_with_requests(self):
        """Test average latency calculation."""
        metrics = ProviderMetrics()
        metrics.successful_requests = 5
        metrics.total_latency_ms = 100.0
        assert metrics.avg_latency_ms == 20.0

    @pytest.mark.asyncio
    async def test_record_success(self):
        """Test recording successful request."""
        metrics = ProviderMetrics()

        await metrics.record_success(50.0)

        assert metrics.total_requests == 1
        assert metrics.successful_requests == 1
        assert metrics.total_latency_ms == 50.0
        assert metrics.last_request_time > 0

    @pytest.mark.asyncio
    async def test_record_failure(self):
        """Test recording failed request."""
        metrics = ProviderMetrics()

        await metrics.record_failure("Connection timeout")

        assert metrics.total_requests == 1
        assert metrics.failed_requests == 1
        assert metrics.last_error == "Connection timeout"
        assert metrics.last_error_time > 0

    @pytest.mark.asyncio
    async def test_multiple_requests(self):
        """Test multiple requests accumulation."""
        metrics = ProviderMetrics()

        await metrics.record_success(100.0)
        await metrics.record_success(200.0)
        await metrics.record_failure("Rate limit")

        assert metrics.total_requests == 3
        assert metrics.successful_requests == 2
        assert metrics.failed_requests == 1
        assert metrics.total_latency_ms == 300.0
        assert metrics.avg_latency_ms == 150.0
        assert metrics.success_rate == pytest.approx(2 / 3)

    def test_to_dict(self):
        """Test to_dict conversion."""
        metrics = ProviderMetrics()
        metrics.total_requests = 10
        metrics.successful_requests = 9
        metrics.failed_requests = 1
        metrics.total_latency_ms = 500.0
        metrics.last_error = "Test error"

        result = metrics.to_dict()

        assert result["total_requests"] == 10
        assert result["successful_requests"] == 9
        assert result["failed_requests"] == 1
        assert result["success_rate"] == 0.9
        assert result["avg_latency_ms"] == pytest.approx(500.0 / 9)
        assert result["last_error"] == "Test error"

    def test_reset(self):
        """Test reset clears all metrics."""
        metrics = ProviderMetrics()
        metrics.total_requests = 100
        metrics.successful_requests = 90
        metrics.failed_requests = 10
        metrics.total_latency_ms = 1000.0
        metrics.last_request_time = 12345.0
        metrics.last_error = "Some error"
        metrics.last_error_time = 12346.0

        metrics.reset()

        assert metrics.total_requests == 0
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 0
        assert metrics.total_latency_ms == 0.0
        assert metrics.last_request_time == 0.0
        assert metrics.last_error == ""
        assert metrics.last_error_time == 0.0

    def test_lock_initialized(self):
        """Test that lock is initialized."""
        metrics = ProviderMetrics()
        assert metrics._lock is not None
