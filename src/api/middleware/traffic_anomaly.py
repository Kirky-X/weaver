# Copyright (c) 2026 KirkyX. All Rights Reserved
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

from core.observability import get_logger
from core.security.traffic_detector import (
    TrafficAction,
    TrafficAnomalyConfig,
    TrafficAnomalyDetector,
    TrafficDecision,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger(__name__)

# Endpoints to skip traffic anomaly detection
SKIP_PATHS = {"/health", "/metrics"}

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

        key_id = getattr(request.state, "api_key_id", None) or "anonymous"
        ip = request.client.host if request.client else "unknown"

        decision = await self._detector.check_request(key_id=key_id, ip=ip)

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
