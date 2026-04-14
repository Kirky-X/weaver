# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Prometheus metrics middleware for API monitoring.

Exposes metrics at /metrics endpoint for Prometheus scraping.
Tracks:
- HTTP request duration (histogram)
- HTTP requests total (counter)
- Database query duration (histogram)
- Slow queries total (counter)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import Response

from core.observability import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

log = get_logger(__name__)

# Prometheus metrics
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=["method", "path", "status"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=["method", "path", "status"],
)

DB_QUERY_DURATION = Histogram(
    "database_query_duration_seconds",
    "Database query duration in seconds",
    labelnames=["operation"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

SLOW_QUERIES_TOTAL = Counter(
    "slow_queries_total",
    "Total slow database queries",
    labelnames=["threshold_ms"],
)


async def metrics_endpoint(request: Request) -> Response:
    """Expose Prometheus metrics.

    Args:
        request: HTTP request.

    Returns:
        Prometheus metrics in text format.

    """
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def record_http_request(method: str, path: str, status: int, duration_seconds: float) -> None:
    """Record HTTP request metrics.

    Args:
        method: HTTP method.
        path: Request path.
        status: Response status code.
        duration_seconds: Request duration in seconds.

    """
    HTTP_REQUEST_DURATION.labels(method=method, path=path, status=status).observe(duration_seconds)
    HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status=status).inc()


def record_db_query(operation: str, duration_seconds: float) -> None:
    """Record database query metrics.

    Args:
        operation: Query operation type.
        duration_seconds: Query duration in seconds.

    """
    DB_QUERY_DURATION.labels(operation=operation).observe(duration_seconds)


def record_slow_query(threshold_ms: int) -> None:
    """Record slow query occurrence.

    Args:
        threshold_ms: Slow query threshold in milliseconds.

    """
    SLOW_QUERIES_TOTAL.labels(threshold_ms=str(threshold_ms)).inc()
