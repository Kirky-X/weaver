# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified traffic anomaly detection with Redis sliding windows.

Detects:
- Per-key rate limit violations
- Per-IP DDoS attacks (with auto-ban)
- Request burst anomalies
- Unknown key scan attacks
- Error rate anomalies

Implements:
    TrafficAnomalyDetector: Unified Redis-based traffic anomaly detector
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from core.observability import get_logger

log = get_logger(__name__)


class TrafficAction(str, Enum):
    ALLOW = "allow"
    SLOW_DOWN = "slow_down"
    BLOCK = "block"


@dataclass
class TrafficDecision:
    """Traffic anomaly detection decision."""

    action: TrafficAction = TrafficAction.ALLOW
    reason: str = ""
    retry_after: int = 0  # seconds


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
        unknown_key_threshold: Threshold for unknown key scan detection (per minute).
        unknown_key_ttl_seconds: TTL for unknown key scan keys (seconds).

    """

    enabled: bool = True
    default_key_rate_limit: int = 200
    ip_rate_limit: int = 200
    burst_threshold: int = 10
    ip_ban_duration_seconds: int = 900  # 15 minutes
    key_ttl_seconds: int = 120  # 2 minutes (slightly longer than 1 min window)
    ip_ttl_seconds: int = 120
    burst_ttl_seconds: int = 5  # 5 seconds (slightly longer than 1s window)
    unknown_key_threshold: int = 100
    unknown_key_ttl_seconds: int = 120


class TrafficAnomalyDetector:
    """Unified Redis sliding window based traffic anomaly detector.

    Detects five types of anomalies:
    1. Per-Key rate: exceeds rate_limit_per_min → block
    2. Per-IP rate: exceeds ip_rate_limit → block + temporary ban
    3. Burst: exceeds burst_threshold per second → slow_down
    4. Unknown key scan: exceeds unknown_key_threshold → block
    5. Error rate: tracked via record_error / get_error_rate

    Redis Key Design:
        traffic:key:{key_id}:{minute}      → Per-Key per-minute counter
        traffic:ip:{ip}:{minute}           → Per-IP per-minute counter
        traffic:burst:{key_id}:{second}    → Per-Key per-second counter
        traffic:blocked:ip:{ip}            → IP ban marker (TTL = ip_ban_duration_seconds)
        traffic:unknown_ip:{ip}:{minute}   → Unknown key scan counter
        traffic:error:{key_id}:{minute}    → Error counter
        traffic:total:{key_id}:{minute}    → Total request counter
    """

    def __init__(
        self,
        redis: Any,
        config: TrafficAnomalyConfig | None = None,
        api_key_manager: Any = None,
    ) -> None:
        self._redis = redis
        self._config = config or TrafficAnomalyConfig()
        self._key_manager = api_key_manager

    async def check_request(
        self,
        key_id: str | None = None,
        ip: str = "unknown",
        key_rate_limit: int | None = None,
    ) -> TrafficDecision:
        """Check request against all anomaly detection rules.

        Args:
            key_id: API key ID (if authenticated).
            ip: Client IP address.
            key_rate_limit: Per-key rate limit (overrides config default).

        Returns:
            TrafficDecision with action, reason, and retry_after.
        """
        if not self._config.enabled:
            return TrafficDecision(action=TrafficAction.ALLOW)

        # Check if IP is banned
        if await self._is_ip_banned(ip):
            return TrafficDecision(
                action=TrafficAction.BLOCK,
                reason="ip_banned",
                retry_after=await self._get_ip_ban_ttl(ip),
            )

        # 1. Per-key rate check
        if key_id:
            rate_limit = key_rate_limit or self._config.default_key_rate_limit
            key_decision = await self._check_key_rate(key_id, rate_limit)
            if key_decision.action != TrafficAction.ALLOW:
                return key_decision

        # 2. Per-IP rate check
        ip_decision = await self._check_ip_rate(ip)
        if ip_decision.action != TrafficAction.ALLOW:
            return ip_decision

        # 3. Burst detection
        burst_decision = await self._check_burst(key_id or ip)
        if burst_decision.action != TrafficAction.ALLOW:
            return burst_decision

        # 4. Unknown key scan detection
        if key_id is None:
            scan_decision = await self._check_unknown_key_scan(ip)
            if scan_decision.action != TrafficAction.ALLOW:
                return scan_decision

        return TrafficDecision(action=TrafficAction.ALLOW)

    async def record_error(self, key_id: str | None = None, status_code: int = 200) -> None:
        """Record response status code for error rate monitoring."""
        now = datetime.now(UTC)
        minute_key = now.strftime("%Y%m%d%H%M")
        scope = key_id or "global"

        if status_code >= 400:
            await self._redis.incr(f"traffic:error:{scope}:{minute_key}")
        await self._redis.incr(f"traffic:total:{scope}:{minute_key}")
        await self._redis.expire(f"traffic:error:{scope}:{minute_key}", 300)
        await self._redis.expire(f"traffic:total:{scope}:{minute_key}", 300)

    async def get_error_rate(self, key_id: str | None = None) -> float:
        """Get current error rate for a key or globally."""
        minute_key = datetime.now(UTC).strftime("%Y%m%d%H%M")
        scope = key_id or "global"
        errors = await self._redis.get(f"traffic:error:{scope}:{minute_key}") or 0
        total = await self._redis.get(f"traffic:total:{scope}:{minute_key}") or 1
        return int(errors) / max(int(total), 1)

    # ── Private Methods ──────────────────────────────────────────────

    async def _is_ip_banned(self, ip: str) -> bool:
        """Check if an IP is currently banned."""
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
        """Get remaining TTL for an IP ban."""
        try:
            ttl = await self._redis.ttl(f"traffic:blocked:ip:{ip}")
            return max(ttl, 60) if ttl > 0 else 60
        except Exception:
            return 60

    async def _check_key_rate(self, key_id: str, rate_limit: int) -> TrafficDecision:
        """Check per-key rate limit."""
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
                    action=TrafficAction.BLOCK,
                    reason="key_rate_exceeded",
                    retry_after=60,
                )

            # Approaching limit warning (80% threshold)
            if count > rate_limit * 0.8:
                return TrafficDecision(
                    action=TrafficAction.SLOW_DOWN,
                    reason="key_rate_approaching",
                    retry_after=5,
                )

        except Exception as exc:
            log.warning(
                "key_rate_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return TrafficDecision(action=TrafficAction.ALLOW)

    async def _check_ip_rate(self, ip: str) -> TrafficDecision:
        """Check per-IP rate limit."""
        now_minute = int(time.time()) // 60
        key = f"traffic:ip:{ip}:{now_minute}"

        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, self._config.ip_ttl_seconds)

            if count > self._config.ip_rate_limit:
                # Ban the IP
                await self._redis.set(
                    f"traffic:blocked:ip:{ip}",
                    "1",
                    ex=self._config.ip_ban_duration_seconds,
                )
                log.warning(
                    "ip_rate_exceeded_banned",
                    ip=ip,
                    count=count,
                    limit=self._config.ip_rate_limit,
                    ban_duration=self._config.ip_ban_duration_seconds,
                )
                return TrafficDecision(
                    action=TrafficAction.BLOCK,
                    reason="ip_rate_exceeded",
                    retry_after=self._config.ip_ban_duration_seconds,
                )

        except Exception as exc:
            log.warning(
                "ip_rate_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return TrafficDecision(action=TrafficAction.ALLOW)

    async def _check_burst(self, identifier: str) -> TrafficDecision:
        """Check burst detection (per-second rate)."""
        now_second = int(time.time())
        key = f"traffic:burst:{identifier}:{now_second}"

        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, self._config.burst_ttl_seconds)

            if count > self._config.burst_threshold:
                log.warning(
                    "burst_detected",
                    identifier=identifier,
                    count=count,
                    threshold=self._config.burst_threshold,
                )
                return TrafficDecision(
                    action=TrafficAction.SLOW_DOWN,
                    reason="burst_detected",
                    retry_after=5,
                )

        except Exception as exc:
            log.warning(
                "burst_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return TrafficDecision(action=TrafficAction.ALLOW)

    async def _check_unknown_key_scan(self, ip: str) -> TrafficDecision:
        """Check for unknown key scan attack."""
        now_minute = int(time.time()) // 60
        key = f"traffic:unknown_ip:{ip}:{now_minute}"

        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, self._config.unknown_key_ttl_seconds)

            if count > self._config.unknown_key_threshold:
                log.warning(
                    "scan_attack_suspected",
                    ip=ip,
                    count=count,
                    threshold=self._config.unknown_key_threshold,
                )
                return TrafficDecision(
                    action=TrafficAction.BLOCK,
                    reason="scan_attack_suspected",
                    retry_after=300,
                )

        except Exception as exc:
            log.warning(
                "unknown_key_scan_check_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )

        return TrafficDecision(action=TrafficAction.ALLOW)
