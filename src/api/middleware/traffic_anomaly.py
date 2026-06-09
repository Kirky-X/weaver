# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Traffic anomaly detection middleware.

Uses Redis sliding window counters to detect:
1. Per-Key rate limiting (rate_limit_per_min)
2. Per-IP rate limiting (>200/min → block)
3. Burst detection (>10 req/s → slow_down)

Implements:
    TrafficAnomalyDetector: Redis-based traffic anomaly detector
    TrafficAnomalyMiddleware: FastAPI middleware for traffic anomaly detection
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.observability import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger(__name__)

# Endpoints to skip traffic anomaly detection
SKIP_PATHS = {"/health", "/metrics"}


@dataclass
class TrafficDecision:
    """Traffic anomaly detection decision.

    Attributes:
        action: Decision action - "allow", "block", or "slow_down".
        reason: Reason for the decision (if not "allow").
        retry_after: Suggested retry-after seconds (if blocked/slowed).

    """

    action: str = "allow"
    reason: str = ""
    retry_after: int = 0


@dataclass
class TrafficAnomalyConfig:
    """Configuration for traffic anomaly detection.

    Attributes:
        enabled: Whether to enable traffic anomaly detection.
        default_key_rate_limit: Default per-key rate limit (requests per minute).
        ip_rate_limit: Per-IP rate limit (requests per minute).
        burst_threshold: Burst detection threshold (requests per second).
        ip_ban_duration_seconds: Duration to ban an IP (seconds).
        key_ttl_seconds: TTL for per-key Redis keys (seconds).
        ip_ttl_seconds: TTL for per-IP Redis keys (seconds).
        burst_ttl_seconds: TTL for burst Redis keys (seconds).

    """

    enabled: bool = True
    default_key_rate_limit: int = 200
    ip_rate_limit: int = 200
    burst_threshold: int = 10
    ip_ban_duration_seconds: int = 900  # 15 minutes
    key_ttl_seconds: int = 120  # 2 minutes (slightly longer than 1 min window)
    ip_ttl_seconds: int = 120
    burst_ttl_seconds: int = 5  # 5 seconds (slightly longer than 1s window)


class TrafficAnomalyDetector:
    """Redis sliding window based traffic anomaly detector.

    Detects three types of anomalies:
    1. Per-Key rate: exceeds rate_limit_per_min → block
    2. Per-IP rate: exceeds ip_rate_limit → block + temporary ban
    3. Burst: exceeds burst_threshold per second → slow_down

    Redis Key Design:
        traffic:key:{key_id}:{minute}  → Per-Key per-minute counter
        traffic:ip:{ip}:{minute}       → Per-IP per-minute counter
        traffic:burst:{key_id}:{second} → Per-Key per-second counter
        traffic:blocked:ip:{ip}        → IP ban marker (TTL = ip_ban_duration_seconds)
    """

    def __init__(
        self,
        redis: Any,
        config: TrafficAnomalyConfig | None = None,
    ) -> None:
        """Initialize TrafficAnomalyDetector.

        Args:
            redis: Redis client instance.
            config: Detector configuration. Uses defaults if None.

        """
        self._redis = redis
        self._config = config or TrafficAnomalyConfig()

    async def check_request(
        self,
        key_id: str,
        ip: str,
        key_rate_limit: int | None = None,
    ) -> TrafficDecision:
        """Check request against all anomaly detection rules.

        Args:
            key_id: API key identifier.
            ip: Client IP address.
            key_rate_limit: Per-key rate limit (overrides config default).

        Returns:
            TrafficDecision with action, reason, and retry_after.

        """
        if not self._config.enabled:
            return TrafficDecision(action="allow")

        # Check if IP is banned
        if await self._is_ip_banned(ip):
            return TrafficDecision(
                action="block",
                reason="ip_banned",
                retry_after=await self._get_ip_ban_ttl(ip),
            )

        rate_limit = key_rate_limit or self._config.default_key_rate_limit

        # 1. Per-Key rate check
        key_decision = await self._check_key_rate(key_id, rate_limit)
        if key_decision.action != "allow":
            return key_decision

        # 2. Per-IP rate check
        ip_decision = await self._check_ip_rate(ip)
        if ip_decision.action != "allow":
            return ip_decision

        # 3. Burst detection
        burst_decision = await self._check_burst(key_id)
        if burst_decision.action != "allow":
            return burst_decision

        return TrafficDecision(action="allow")

    async def _is_ip_banned(self, ip: str) -> bool:
        """Check if an IP is currently banned.

        Args:
            ip: Client IP address.

        Returns:
            True if IP is banned.

        """
        try:
            banned = await self._redis.exists(f"traffic:blocked:ip:{ip}")
            return bool(banned)
        except Exception as exc:
            log.warning(
                "ip_ban_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return False

    async def _get_ip_ban_ttl(self, ip: str) -> int:
        """Get remaining TTL for an IP ban.

        Args:
            ip: Client IP address.

        Returns:
            Remaining TTL in seconds.

        """
        try:
            ttl = await self._redis.ttl(f"traffic:blocked:ip:{ip}")
            return max(ttl, 60) if ttl > 0 else 60
        except Exception:
            return 60

    async def _check_key_rate(self, key_id: str, rate_limit: int) -> TrafficDecision:
        """Check per-key rate limit.

        Args:
            key_id: API key identifier.
            rate_limit: Maximum requests per minute.

        Returns:
            TrafficDecision.

        """
        now_minute = int(time.time()) // 60
        key = f"traffic:key:{key_id}:{now_minute}"

        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, self._config.key_ttl_seconds)

            if count > rate_limit:
                log.warning(
                    "key_rate_exceeded",
                    key_id=key_id,
                    count=count,
                    limit=rate_limit,
                )
                return TrafficDecision(
                    action="block",
                    reason="key_rate_exceeded",
                    retry_after=60,
                )

            # Approaching limit warning (80% threshold)
            if count > rate_limit * 0.8:
                return TrafficDecision(
                    action="slow_down",
                    reason="key_rate_approaching",
                    retry_after=5,
                )

        except Exception as exc:
            log.warning(
                "key_rate_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return TrafficDecision(action="allow")

    async def _check_ip_rate(self, ip: str) -> TrafficDecision:
        """Check per-IP rate limit.

        Args:
            ip: Client IP address.

        Returns:
            TrafficDecision.

        """
        now_minute = int(time.time()) // 60
        key = f"traffic:ip:{ip}:{now_minute}"

        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, self._config.ip_ttl_seconds)

            if count > self._config.ip_rate_limit:
                # Ban the IP
                await self._redis.setex(
                    f"traffic:blocked:ip:{ip}",
                    self._config.ip_ban_duration_seconds,
                    "1",
                )
                log.warning(
                    "ip_rate_exceeded_banned",
                    ip=ip,
                    count=count,
                    limit=self._config.ip_rate_limit,
                    ban_duration=self._config.ip_ban_duration_seconds,
                )
                return TrafficDecision(
                    action="block",
                    reason="ip_rate_exceeded",
                    retry_after=self._config.ip_ban_duration_seconds,
                )

        except Exception as exc:
            log.warning(
                "ip_rate_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return TrafficDecision(action="allow")

    async def _check_burst(self, key_id: str) -> TrafficDecision:
        """Check burst detection (per-second rate).

        Args:
            key_id: API key identifier.

        Returns:
            TrafficDecision.

        """
        now_second = int(time.time())
        key = f"traffic:burst:{key_id}:{now_second}"

        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, self._config.burst_ttl_seconds)

            if count > self._config.burst_threshold:
                log.warning(
                    "burst_detected",
                    key_id=key_id,
                    count=count,
                    threshold=self._config.burst_threshold,
                )
                return TrafficDecision(
                    action="slow_down",
                    reason="burst_detected",
                    retry_after=5,
                )

        except Exception as exc:
            log.warning(
                "burst_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return TrafficDecision(action="allow")


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
        """Initialize middleware.

        Args:
            app: ASGI application.
            detector: TrafficAnomalyDetector instance.

        """
        super().__init__(app)
        self._detector = detector

    async def dispatch(self, request: Request, call_next) -> Response:
        """Check traffic anomalies for incoming requests.

        Args:
            request: HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            HTTP response or 429 error if traffic anomaly detected.

        """
        # Skip certain endpoints
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # Extract key_id and IP
        key_id = getattr(request.state, "api_key_id", None) or "anonymous"
        ip = request.client.host if request.client else "unknown"

        # Check traffic anomaly
        decision = await self._detector.check_request(key_id, ip)

        if decision.action == "block":
            return JSONResponse(
                status_code=429,
                content={"error": decision.reason},
                headers={"Retry-After": str(decision.retry_after)},
            )

        if decision.action == "slow_down":
            response = await call_next(request)
            response.headers["Retry-After"] = str(decision.retry_after)
            return response

        return await call_next(request)
