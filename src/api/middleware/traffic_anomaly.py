# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Traffic anomaly detection middleware.

Thin wrapper that re-exports from the canonical implementation
in core.security.traffic_detector and provides the FastAPI middleware.

Implements:
    TrafficAnomalyMiddleware: FastAPI middleware for traffic anomaly detection
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from api.utils.client_ip import get_client_ip
from core.constants import HEALTH_PROBE_PATHS as SKIP_PATHS
from core.observability import get_logger
from core.security import (
    TrafficAction,
    TrafficAnomalyConfig,
    TrafficAnomalyDetector,
    TrafficDecision,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger(__name__)

# Endpoints to skip traffic anomaly detection (single source in core.constants).

__all__ = [
    "TrafficAction",
    "TrafficAnomalyConfig",
    "TrafficAnomalyDetector",
    "TrafficAnomalyMiddleware",
    "TrafficDecision",
]


class TrafficAnomalyMiddleware(BaseHTTPMiddleware):
    """Traffic anomaly detection middleware.

    Intercepts requests and checks for traffic anomalies before
    passing them to the next handler. Returns 429 for blocked
    requests and adds Retry-After header for slow_down responses.
    """

    def __init__(
        self,
        app: Any,
        detector: TrafficAnomalyDetector,
    ) -> None:
        super().__init__(app)
        self._detector = detector

    async def dispatch(self, request: Request, call_next) -> Response:
        """Check traffic anomalies for incoming requests."""
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # pass None through instead of an "anonymous" sentinel —
        # the detector branches on `key_id is None` to run the IP-based
        # unknown-key-scan check, and on `if key_id:` for per-key limiting.
        # A truthy sentinel silently disabled the scan path and pooled all
        # unauthenticated traffic into one shared bucket.
        key_id = getattr(request.state, "api_key_id", None)
        ip = get_client_ip(request)

        try:
            decision = await self._detector.check_request(key_id=key_id, ip=ip)
        except Exception:
            # Fail-open: a Redis outage must not 500 every request through
            # this middleware. Log and let the request proceed unshaped.
            log.exception(
                "traffic_anomaly_check_failed_fail_open",
                path=request.url.path,
            )
            return await call_next(request)

        if decision.action == TrafficAction.BLOCK:
            return JSONResponse(
                status_code=429,
                content={"error": decision.reason},
                headers={"Retry-After": str(decision.retry_after)},
            )

        if decision.action == TrafficAction.SLOW_DOWN:
            response = await call_next(request)
            response.headers["Retry-After"] = str(decision.retry_after)
            return response

        return await call_next(request)
