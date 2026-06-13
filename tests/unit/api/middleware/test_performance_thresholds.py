# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for configurable performance monitoring thresholds.

TDD Phase 1: Write tests first, then implement.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Mock setfit before any imports that trigger the chain
if "setfit" not in sys.modules:
    sys.modules["setfit"] = MagicMock()
    sys.modules["setfit.span"] = MagicMock()
    sys.modules["setfit.span.trainer"] = MagicMock()

import pytest


class TestPerformanceThresholds:
    """Test configurable performance thresholds."""

    def test_default_p99_threshold_200ms(self) -> None:
        """Default P99 threshold should be 200ms."""
        from api.middleware.performance import PerformanceMonitoringMiddleware

        middleware = PerformanceMonitoringMiddleware(app=MagicMock())
        assert middleware._p99_threshold_ms == 200

    def test_default_p95_threshold_100ms(self) -> None:
        """Default P95 threshold should be 100ms."""
        from api.middleware.performance import PerformanceMonitoringMiddleware

        middleware = PerformanceMonitoringMiddleware(app=MagicMock())
        assert middleware._p95_threshold_ms == 100

    def test_custom_thresholds_via_constructor(self) -> None:
        """Custom thresholds should be accepted via constructor."""
        from api.middleware.performance import PerformanceMonitoringMiddleware

        middleware = PerformanceMonitoringMiddleware(
            app=MagicMock(),
            p95_threshold_ms=50,
            p99_threshold_ms=150,
        )
        assert middleware._p95_threshold_ms == 50
        assert middleware._p99_threshold_ms == 150

    @pytest.mark.asyncio
    async def test_exceed_p99_logs_error(self) -> None:
        """Exceeding P99 threshold should log ERROR."""
        from api.middleware.performance import PerformanceMonitoringMiddleware

        middleware = PerformanceMonitoringMiddleware(
            app=MagicMock(),
            p99_threshold_ms=200,
        )

        # Create mock request and response
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/v1/test"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_call_next = AsyncMock(return_value=mock_response)

        with patch("api.middleware.performance.log") as mock_log:
            with patch("api.middleware.performance.time") as mock_time:
                mock_time.time.side_effect = [0.0, 0.3]  # 300ms duration

                await middleware.dispatch(mock_request, mock_call_next)

                # Should log error for exceeding P99 (300ms > 200ms)
                error_calls = [
                    c for c in mock_log.error.call_args_list if "very_slow_response" in str(c)
                ]
                assert len(error_calls) > 0

    @pytest.mark.asyncio
    async def test_exceed_p95_logs_warning(self) -> None:
        """Exceeding P95 but not P99 should log WARNING."""
        from api.middleware.performance import PerformanceMonitoringMiddleware

        middleware = PerformanceMonitoringMiddleware(
            app=MagicMock(),
            p95_threshold_ms=100,
            p99_threshold_ms=200,
        )

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/v1/test"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_call_next = AsyncMock(return_value=mock_response)

        with patch("api.middleware.performance.log") as mock_log:
            with patch("api.middleware.performance.time") as mock_time:
                mock_time.time.side_effect = [0.0, 0.15]  # 150ms duration

                await middleware.dispatch(mock_request, mock_call_next)

                # Should log warning for exceeding P95 (150ms > 100ms)
                warning_calls = [
                    c for c in mock_log.warning.call_args_list if "slow_response" in str(c)
                ]
                assert len(warning_calls) > 0

    @pytest.mark.asyncio
    async def test_below_threshold_no_warning(self) -> None:
        """Below both thresholds should not log warning or error."""
        from api.middleware.performance import PerformanceMonitoringMiddleware

        middleware = PerformanceMonitoringMiddleware(
            app=MagicMock(),
            p95_threshold_ms=100,
            p99_threshold_ms=200,
        )

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/api/v1/test"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_call_next = AsyncMock(return_value=mock_response)

        with patch("api.middleware.performance.log") as mock_log:
            with patch("api.middleware.performance.time") as mock_time:
                mock_time.time.side_effect = [0.0, 0.05]  # 50ms duration

                await middleware.dispatch(mock_request, mock_call_next)

                # Should not log warning or error
                warning_calls = [
                    c for c in mock_log.warning.call_args_list if "slow_response" in str(c)
                ]
                error_calls = [
                    c for c in mock_log.error.call_args_list if "very_slow_response" in str(c)
                ]
                assert len(warning_calls) == 0
                assert len(error_calls) == 0


class TestPerformanceSettings:
    """Test PerformanceSettings configuration."""

    def test_default_values(self) -> None:
        """PerformanceSettings should have correct defaults."""
        from config.subconfigs import PerformanceSettings

        settings = PerformanceSettings()
        assert settings.p95_threshold_ms == 100
        assert settings.p99_threshold_ms == 200

    def test_custom_values(self) -> None:
        """PerformanceSettings should accept custom values."""
        from config.subconfigs import PerformanceSettings

        settings = PerformanceSettings(p95_threshold_ms=50, p99_threshold_ms=150)
        assert settings.p95_threshold_ms == 50
        assert settings.p99_threshold_ms == 150
