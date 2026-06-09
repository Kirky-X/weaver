"""Traffic anomaly detection with Redis sliding windows.

Detects:
- Per-key rate limit violations
- Per-IP DDoS attacks
- Request burst anomalies
- Error rate anomalies
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from core.observability import get_logger

log = get_logger(__name__)


class TrafficAction(str, Enum):
    ALLOW = "allow"
    SLOW_DOWN = "slow_down"
    BLOCK = "block"


@dataclass
class TrafficDecision:
    action: TrafficAction
    reason: str = ""
    retry_after: int = 0  # seconds


class TrafficAnomalyDetector:
    """Redis-based traffic anomaly detection with sliding windows."""

    def __init__(self, redis, api_key_manager=None):
        self._redis = redis
        self._key_manager = api_key_manager

    async def check_request(
        self,
        key_id: str | None = None,
        ip: str = "unknown",
    ) -> TrafficDecision:
        """Evaluate incoming request and return traffic decision.

        Args:
            key_id: API key ID (if authenticated).
            ip: Client IP address.

        Returns:
            TrafficDecision: allow / slow_down / block.
        """
        now = datetime.now(UTC)
        minute_key = now.strftime("%Y%m%d%H%M")
        second_key = now.strftime("%Y%m%d%H%M%S")

        # 1. Per-IP rate limit (prevent DDoS)
        ip_count = await self._redis.incr(f"traffic:ip:{ip}:{minute_key}")
        await self._redis.expire(f"traffic:ip:{ip}:{minute_key}", 120)

        if ip_count > 500:  # >500 req/min from single IP → block
            log.warning("traffic_ip_blocked", ip=ip, count=ip_count)
            return TrafficDecision(TrafficAction.BLOCK, "ip_rate_exceeded", retry_after=60)
        if ip_count > 300:  # >300 req/min → slow down
            return TrafficDecision(TrafficAction.SLOW_DOWN, "ip_rate_high", retry_after=5)

        # 2. Per-key rate limit
        if key_id:
            key_count = await self._redis.incr(f"traffic:key:{key_id}:{minute_key}")
            await self._redis.expire(f"traffic:key:{key_id}:{minute_key}", 120)

            key_limit = 100  # default
            if self._key_manager:
                with contextlib.suppress(Exception):
                    key_limit = await self._key_manager.get_rate_limit(key_id)

            if key_count > key_limit:
                log.warning("traffic_key_blocked", key_id=key_id, count=key_count)
                return TrafficDecision(TrafficAction.BLOCK, "key_rate_exceeded", retry_after=60)

            # Warn at 80% threshold
            if key_count > int(key_limit * 0.8):
                return TrafficDecision(
                    TrafficAction.SLOW_DOWN, "key_rate_approaching", retry_after=2
                )

        # 3. Burst detection (requests per second)
        burst_count = await self._redis.incr(f"traffic:burst:{key_id or ip}:{second_key}")
        await self._redis.expire(f"traffic:burst:{key_id or ip}:{second_key}", 30)

        if burst_count > 20:  # >20 req/s → block
            return TrafficDecision(TrafficAction.BLOCK, "burst_detected", retry_after=10)
        if burst_count > 10:  # >10 req/s → slow down
            return TrafficDecision(TrafficAction.SLOW_DOWN, "burst_warning", retry_after=2)

        # 4. Check for unknown key scan attack
        if key_id is None:
            unknown_count = await self._redis.incr(f"traffic:unknown_ip:{ip}:{minute_key}")
            await self._redis.expire(f"traffic:unknown_ip:{ip}:{minute_key}", 120)
            if unknown_count > 100:
                return TrafficDecision(
                    TrafficAction.BLOCK, "scan_attack_suspected", retry_after=300
                )

        return TrafficDecision(TrafficAction.ALLOW)

    async def record_error(self, key_id: str | None = None, status_code: int = 200):
        """Record response status code for error rate monitoring."""
        now = datetime.now(UTC)
        minute_key = now.strftime("%Y%m%d%H%M")

        if status_code >= 400:
            await self._redis.incr(f"traffic:error:{key_id or 'global'}:{minute_key}")
        await self._redis.incr(f"traffic:total:{key_id or 'global'}:{minute_key}")
        await self._redis.expire(f"traffic:error:{key_id or 'global'}:{minute_key}", 300)
        await self._redis.expire(f"traffic:total:{key_id or 'global'}:{minute_key}", 300)

    async def get_error_rate(self, key_id: str | None = None) -> float:
        """Get current error rate for a key or globally."""
        minute_key = datetime.now(UTC).strftime("%Y%m%d%H%M")
        errors = await self._redis.get(f"traffic:error:{key_id or 'global'}:{minute_key}") or 0
        total = await self._redis.get(f"traffic:total:{key_id or 'global'}:{minute_key}") or 1
        return int(errors) / max(int(total), 1)
