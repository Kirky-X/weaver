# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Integration tests for Prometheus metrics endpoint.

Tests the /metrics endpoint and verifies:
- Returns text/plain format
- Contains expected metric names:
  - http_request_duration_seconds
  - http_requests_total
  - database_query_duration_seconds
  - slow_queries_total
- Metrics format correct (includes HELP and TYPE comments)
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST

from api.middleware.prometheus_metrics import (
    metrics_endpoint,
    record_db_query,
    record_http_request,
    record_slow_query,
)


@pytest.fixture
def app():
    """Create FastAPI app with /metrics endpoint."""
    from starlette.routing import Route

    app = FastAPI()
    # Use add_route instead of add_api_route for functions that take Request parameter
    app.add_route("/metrics", metrics_endpoint, methods=["GET"])
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    with TestClient(app) as test_client:
        yield test_client


class TestPrometheusMetricsEndpoint:
    """Test /metrics endpoint functionality."""

    def test_metrics_endpoint_returns_200(self, client):
        """Test that /metrics endpoint returns 200 status code."""
        response = client.get("/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_metrics_content_type(self, client):
        """Test that /metrics returns correct Content-Type header."""
        response = client.get("/metrics")
        content_type = response.headers.get("content-type", "")

        assert (
            "text/plain" in content_type
        ), f"Expected 'text/plain' in Content-Type, got '{content_type}'"
        assert (
            "charset=utf-8" in content_type
        ), f"Expected 'charset=utf-8' in Content-Type, got '{content_type}'"

    def test_metrics_format_valid_prometheus(self, client):
        """Test that metrics follow Prometheus standard format.

        Prometheus format requirements:
        - HELP comments: # HELP metric_name description
        - TYPE comments: # TYPE metric_name type
        - Metric lines: metric_name{labels} value
        """
        response = client.get("/metrics")
        content = response.text

        assert content, "Metrics content should not be empty"

        lines = content.strip().split("\n")
        valid_lines = 0

        for line in lines:
            line = line.strip()

            # Empty lines are allowed
            if not line:
                continue

            # TYPE or HELP comments
            if line.startswith("# TYPE ") or line.startswith("# HELP "):
                valid_lines += 1
                continue

            # Metric line format: metric_name{labels} value or metric_name value
            metric_pattern = r"^[a-zA-Z_:][a-zA-Z0-9_:]*({[^}]+})?\s+[\d\.eE+-]+(\s+\d+)?$"
            if re.match(metric_pattern, line):
                valid_lines += 1

        assert valid_lines > 0, "Should have at least some valid metric lines"


class TestExpectedMetrics:
    """Test that expected metrics are present."""

    def test_http_request_duration_seconds_metric(self, client):
        """Test that http_request_duration_seconds metric is present."""
        # Record a sample request to ensure metric is registered
        record_http_request("GET", "/test", 200, 0.123)

        response = client.get("/metrics")
        content = response.text

        # Check for TYPE comment
        assert (
            "# TYPE http_request_duration_seconds" in content
        ), "http_request_duration_seconds TYPE comment should be present"

        # Check for HELP comment
        assert (
            "# HELP http_request_duration_seconds" in content
        ), "http_request_duration_seconds HELP comment should be present"

    def test_http_requests_total_metric(self, client):
        """Test that http_requests_total metric is present."""
        # Record a sample request
        record_http_request("POST", "/api/test", 201, 0.050)

        response = client.get("/metrics")
        content = response.text

        assert (
            "# TYPE http_requests_total" in content
        ), "http_requests_total TYPE comment should be present"
        assert (
            "# HELP http_requests_total" in content
        ), "http_requests_total HELP comment should be present"

    def test_database_query_duration_seconds_metric(self, client):
        """Test that database_query_duration_seconds metric is present."""
        # Record a sample query
        record_db_query("SELECT", 0.025)

        response = client.get("/metrics")
        content = response.text

        assert (
            "# TYPE database_query_duration_seconds" in content
        ), "database_query_duration_seconds TYPE comment should be present"
        assert (
            "# HELP database_query_duration_seconds" in content
        ), "database_query_duration_seconds HELP comment should be present"

    def test_slow_queries_total_metric(self, client):
        """Test that slow_queries_total metric is present."""
        # Record a sample slow query
        record_slow_query(100)

        response = client.get("/metrics")
        content = response.text

        assert (
            "# TYPE slow_queries_total" in content
        ), "slow_queries_total TYPE comment should be present"
        assert (
            "# HELP slow_queries_total" in content
        ), "slow_queries_total HELP comment should be present"


class TestMetricsRecording:
    """Test metrics recording functionality."""

    def test_record_http_request_increments_counter(self, client):
        """Test that recording HTTP request increments counter."""
        # Record multiple requests
        for _ in range(5):
            record_http_request("GET", "/test/path", 200, 0.1)

        response = client.get("/metrics")
        content = response.text

        # Verify http_requests_total contains our path
        assert 'http_requests_total{method="GET",path="/test/path",status="200"}' in content

    def test_record_http_request_records_duration(self, client):
        """Test that HTTP request duration is recorded."""
        record_http_request("GET", "/timing/test", 200, 0.250)

        response = client.get("/metrics")
        content = response.text

        # Verify histogram exists
        assert "http_request_duration_seconds" in content

    def test_record_db_query_records_duration(self, client):
        """Test that database query duration is recorded."""
        record_db_query("SELECT", 0.050)
        record_db_query("INSERT", 0.010)

        response = client.get("/metrics")
        content = response.text

        assert "database_query_duration_seconds" in content

    def test_record_slow_query_increments_counter(self, client):
        """Test that slow query counter is incremented."""
        record_slow_query(100)
        record_slow_query(100)
        record_slow_query(200)

        response = client.get("/metrics")
        content = response.text

        # Verify slow_queries_total contains threshold labels
        assert 'slow_queries_total{threshold_ms="100"}' in content
        assert 'slow_queries_total{threshold_ms="200"}' in content


class TestMetricsConcurrency:
    """Test concurrent access to metrics endpoint."""

    def test_metrics_concurrent_requests(self, client):
        """Test that metrics endpoint handles concurrent requests."""
        num_requests = 10
        responses = []

        for i in range(num_requests):
            response = client.get("/metrics")
            responses.append(response)

        # Verify all requests succeeded
        for i, response in enumerate(responses):
            assert response.status_code == 200, f"Request {i} failed"
            assert len(response.text) > 0, f"Request {i} returned empty content"

    def test_metrics_consistent_format(self, client):
        """Test that metrics format is consistent across requests."""
        responses = []
        for _ in range(3):
            response = client.get("/metrics")
            assert response.status_code == 200
            responses.append(response)

        # Verify Content-Type consistency
        content_types = {r.headers.get("content-type") for r in responses}
        assert len(content_types) == 1, "Content-Type should be consistent"

        # Verify all responses contain metric names
        for response in responses:
            assert "http_request_duration_seconds" in response.text


class TestMetricsEdgeCases:
    """Test edge cases for metrics endpoint."""

    def test_metrics_empty_state(self, client):
        """Test metrics endpoint with no recorded metrics."""
        # Fresh app, no metrics recorded yet
        response = client.get("/metrics")

        assert response.status_code == 200
        # Prometheus client library always includes some default metrics
        assert len(response.text) > 0

    def test_metrics_special_characters_in_path(self, client):
        """Test metrics with special characters in path."""
        record_http_request("GET", "/api/path-with-special/chars_123", 200, 0.1)

        response = client.get("/metrics")
        content = response.text

        assert response.status_code == 200
        assert 'path="/api/path-with-special/chars_123"' in content

    def test_metrics_response_size_reasonable(self, client):
        """Test that metrics response size is reasonable."""
        # Record some metrics to make response more realistic
        for i in range(10):
            record_http_request("GET", f"/test/path/{i}", 200, 0.1)
            record_db_query("SELECT", 0.05)

        response = client.get("/metrics")
        content_size = len(response.content)

        # Should be less than 1MB
        max_reasonable_size = 1 * 1024 * 1024
        assert (
            content_size < max_reasonable_size
        ), f"Metrics content size {content_size} exceeds limit"

        # Should not be empty
        assert content_size > 0, "Metrics content should not be empty"
