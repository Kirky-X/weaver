# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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


class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """Monitor API response times and log slow endpoints.

    Args:
        app: ASGI application.
        p95_threshold_ms: P95 latency threshold in milliseconds (default 100).
        p99_threshold_ms: P99 latency threshold in milliseconds (default 200).

    """

    def __init__(
        self,
        app,
        p95_threshold_ms: int = 100,
        p99_threshold_ms: int = 200,
    ) -> None:
        super().__init__(app)
        self._p95_threshold_ms = p95_threshold_ms
        self._p99_threshold_ms = p99_threshold_ms

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
        if duration_ms > self._p99_threshold_ms:
            log.error(
                "very_slow_response",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                threshold_ms=self._p99_threshold_ms,
            )
        elif duration_ms > self._p95_threshold_ms:
            log.warning(
                "slow_response",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                threshold_ms=self._p95_threshold_ms,
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
