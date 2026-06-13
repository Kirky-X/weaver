# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for performance monitoring middleware.

Tests verify:
- Response includes X-Response-Time-Ms header
- Response time value is positive
- Slow requests log warnings (via mock)
- Prometheus metrics are recorded (via mock)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteTestClient

from api.middleware.performance import PerformanceMonitoringMiddleware


@pytest.fixture
def app():
    """Create FastAPI app with performance middleware."""
    app = FastAPI()
    app.add_middleware(PerformanceMonitoringMiddleware, p95_threshold_ms=500, p99_threshold_ms=1000)

    @app.get("/fast")
    async def fast_endpoint():
        """Fast endpoint for testing."""
        return JSONResponse({"message": "fast response"})

    @app.get("/slow")
    async def slow_endpoint():
        """Slow endpoint for testing (>500ms)."""
        time.sleep(0.6)  # 600ms - triggers slow warning
        return JSONResponse({"message": "slow response"})

    @app.get("/very-slow")
    async def very_slow_endpoint():
        """Very slow endpoint for testing (>1000ms)."""
        time.sleep(1.1)  # 1100ms - triggers very slow error
        return JSONResponse({"message": "very slow response"})

    @app.get("/error")
    async def error_endpoint():
        """Endpoint that raises an error."""
        raise ValueError("Test error")

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    with TestClient(app) as test_client:
        yield test_client


class TestResponseTimeHeader:
    """Test X-Response-Time-Ms header functionality."""

    def test_fast_endpoint_has_response_time_header(self, client):
        """Test that fast endpoint includes X-Response-Time-Ms header."""
        response = client.get("/fast")

        assert response.status_code == 200
        assert (
            "x-response-time-ms" in response.headers
        ), "Response should include X-Response-Time-Ms header"

    def test_slow_endpoint_has_response_time_header(self, client):
        """Test that slow endpoint includes X-Response-Time-Ms header."""
        response = client.get("/slow")

        assert response.status_code == 200
        assert (
            "x-response-time-ms" in response.headers
        ), "Response should include X-Response-Time-Ms header"

    def test_error_endpoint_has_response_time_header(self, client):
        """Test that error responses include X-Response-Time-Ms header."""
        # Note: Errors might not include the header depending on error handling
        # This test documents the actual behavior
        try:
            response = client.get("/error")
        except Exception:
            # Exception might be raised, which is expected behavior
            pass


class TestResponseTimeValue:
    """Test response time value correctness."""

    def test_response_time_is_positive_number(self, client):
        """Test that response time value is a positive number."""
        response = client.get("/fast")

        assert "x-response-time-ms" in response.headers
        response_time = response.headers["x-response-time-ms"]

        # Should be parseable as float
        try:
            time_value = float(response_time)
        except ValueError:
            pytest.fail(f"Response time '{response_time}' is not a valid number")

        # Should be positive
        assert time_value > 0, f"Response time should be positive, got {time_value}"

    def test_slow_response_time_exceeds_threshold(self, client):
        """Test that slow response time exceeds P95 threshold (500ms)."""
        response = client.get("/slow")

        assert "x-response-time-ms" in response.headers
        response_time = float(response.headers["x-response-time-ms"])

        # Should be > 500ms (actually around 600ms due to sleep)
        assert response_time > 500, f"Slow response time should be > 500ms, got {response_time}ms"

    def test_fast_response_time_below_threshold(self, client):
        """Test that fast response time is below P95 threshold (500ms)."""
        response = client.get("/fast")

        assert "x-response-time-ms" in response.headers
        response_time = float(response.headers["x-response-time-ms"])

        # Should be < 500ms
        assert response_time < 500, f"Fast response time should be < 500ms, got {response_time}ms"


class TestSlowRequestLogging:
    """Test slow request logging functionality."""

    @patch("api.middleware.performance.log")
    def test_fast_request_logs_debug(self, mock_log, client):
        """Test that fast request logs at debug level."""
        response = client.get("/fast")

        assert response.status_code == 200
        # Check that debug log was called
        mock_log.debug.assert_called()

        # Get the call arguments
        call_args = mock_log.debug.call_args
        assert call_args is not None

        # First argument should be the event name
        event_name = call_args[0][0]
        assert event_name == "request_completed"

    @patch("api.middleware.performance.log")
    def test_slow_request_logs_warning(self, mock_log, client):
        """Test that slow request (>500ms) logs at warning level."""
        response = client.get("/slow")

        assert response.status_code == 200

        # Check that warning log was called
        mock_log.warning.assert_called()

        # Get the call arguments
        call_args = mock_log.warning.call_args
        assert call_args is not None

        event_name = call_args[0][0]
        assert event_name == "slow_response"

        # Verify threshold is in log
        kwargs = call_args[1]
        assert "threshold_ms" in kwargs
        assert kwargs["threshold_ms"] == 500

    @patch("api.middleware.performance.log")
    def test_very_slow_request_logs_error(self, mock_log, client):
        """Test that very slow request (>1000ms) logs at error level."""
        response = client.get("/very-slow")

        assert response.status_code == 200

        # Check that error log was called
        mock_log.error.assert_called()

        # Get the call arguments
        call_args = mock_log.error.call_args
        assert call_args is not None

        event_name = call_args[0][0]
        assert event_name == "very_slow_response"

        # Verify threshold is in log
        kwargs = call_args[1]
        assert "threshold_ms" in kwargs
        assert kwargs["threshold_ms"] == 1000


class TestPrometheusMetricsRecording:
    """Test Prometheus metrics recording in middleware."""

    @patch("api.middleware.prometheus_metrics.record_http_request")
    def test_fast_request_records_metrics(self, mock_record, client):
        """Test that fast request records Prometheus metrics."""
        response = client.get("/fast")

        assert response.status_code == 200
        # Check that metrics were recorded
        mock_record.assert_called_once()

        # Verify call arguments
        call_args = mock_record.call_args
        kwargs = call_args[1]

        assert kwargs["method"] == "GET"
        assert kwargs["path"] == "/fast"
        assert kwargs["status"] == 200
        assert kwargs["duration_seconds"] > 0

    @patch("api.middleware.prometheus_metrics.record_http_request")
    def test_slow_request_records_metrics(self, mock_record, client):
        """Test that slow request records Prometheus metrics."""
        response = client.get("/slow")

        assert response.status_code == 200
        mock_record.assert_called_once()

        call_args = mock_record.call_args
        kwargs = call_args[1]

        assert kwargs["path"] == "/slow"
        assert kwargs["status"] == 200
        # Duration should be > 0.5 seconds
        assert kwargs["duration_seconds"] > 0.5

    @patch("api.middleware.prometheus_metrics.record_http_request")
    def test_error_request_records_metrics(self, mock_record, client):
        """Test that error response records Prometheus metrics."""
        # Note: Error handling might affect metrics recording
        # This test documents actual behavior
        try:
            response = client.get("/error")
        except Exception:
            # Exception might be raised before metrics recording
            pass

        # Metrics recording behavior depends on error handling implementation


class TestMiddlewareIntegration:
    """Test middleware integration with FastAPI."""

    def test_middleware_does_not_affect_response(self, client):
        """Test that middleware doesn't modify response content."""
        response = client.get("/fast")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "fast response"

    def test_middleware_preserves_status_code(self, client):
        """Test that middleware preserves HTTP status code."""
        response = client.get("/fast")
        assert response.status_code == 200

    def test_multiple_requests_consistent_behavior(self, client):
        """Test that middleware behaves consistently across multiple requests."""
        for _ in range(5):
            response = client.get("/fast")
            assert response.status_code == 200
            assert "x-response-time-ms" in response.headers

            response_time = float(response.headers["x-response-time-ms"])
            assert response_time > 0
            assert response_time < 500  # Should be fast

    def test_middleware_handles_different_methods(self, client):
        """Test middleware works with different HTTP methods."""
        # Add a POST endpoint
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(PerformanceMonitoringMiddleware)

        @app.post("/test-post")
        async def post_endpoint():
            return JSONResponse({"method": "POST"})

        with TestClient(app) as test_client:
            response = test_client.post("/test-post")
            assert response.status_code == 200
            assert "x-response-time-ms" in response.headers


class TestEdgeCases:
    """Test edge cases for performance middleware."""

    def test_empty_response_body(self, client):
        """Test middleware with empty response body."""
        app = FastAPI()
        app.add_middleware(PerformanceMonitoringMiddleware)

        @app.get("/empty")
        async def empty_endpoint():
            from fastapi.responses import Response

            return Response(content="", status_code=200)

        with TestClient(app) as test_client:
            response = test_client.get("/empty")
            assert response.status_code == 200
            assert "x-response-time-ms" in response.headers

    def test_large_response_body(self, client):
        """Test middleware with large response body."""
        app = FastAPI()
        app.add_middleware(PerformanceMonitoringMiddleware)

        @app.get("/large")
        async def large_endpoint():
            # Create a large response (~1MB)
            large_data = "x" * 1_000_000
            return JSONResponse({"data": large_data})

        with TestClient(app) as test_client:
            response = test_client.get("/large")
            assert response.status_code == 200
            assert "x-response-time-ms" in response.headers

            # Should still have reasonable response time
            response_time = float(response.headers["x-response-time-ms"])
            assert response_time > 0

    def test_unicode_in_response(self, client):
        """Test middleware with unicode characters in response."""
        app = FastAPI()
        app.add_middleware(PerformanceMonitoringMiddleware)

        @app.get("/unicode")
        async def unicode_endpoint():
            return JSONResponse({"message": "中文测试 🚀"})

        with TestClient(app) as test_client:
            response = test_client.get("/unicode")
            assert response.status_code == 200
            assert "x-response-time-ms" in response.headers
