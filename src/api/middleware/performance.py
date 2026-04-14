# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Performance monitoring middleware for API response times."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from core.observability import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger(__name__)

# Response time thresholds in milliseconds
P95_THRESHOLD_MS = 500
P99_THRESHOLD_MS = 1000


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """Monitor API response times and log slow endpoints."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Measure request duration and log slow responses.

        Args:
            request: HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            HTTP response with timing header.

        """
        start_time = time.time()

        response = await call_next(request)

        duration_ms = (time.time() - start_time) * 1000

        # Log all requests with duration
        log.debug(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        # Warn on slow responses
        if duration_ms > P99_THRESHOLD_MS:
            log.error(
                "very_slow_response",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                threshold_ms=P99_THRESHOLD_MS,
            )
        elif duration_ms > P95_THRESHOLD_MS:
            log.warning(
                "slow_response",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                threshold_ms=P95_THRESHOLD_MS,
            )

        # Add timing header for client-side monitoring
        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))

        # Record Prometheus metrics
        from api.middleware.prometheus_metrics import record_http_request

        record_http_request(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_seconds=duration_ms / 1000,
        )

        return response
