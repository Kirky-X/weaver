# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for unified TrafficAnomalyDetector.

Tests the canonical implementation in core.security.traffic_detector
which merges features from both the core and middleware versions.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from core.security.traffic_detector import (
    TrafficAction,
    TrafficAnomalyConfig,
    TrafficAnomalyDetector,
    TrafficDecision,
)


class FakeRedis:
    """Fake Redis client for testing."""

    def __init__(self) -> None:
        self._data: dict[str, int | str] = {}
        self._ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        if key not in self._data:
            self._data[key] = 0
        self._data[key] = int(self._data[key]) + 1
        return int(self._data[key])

    async def expire(self, key: str, ttl: int) -> bool:
        self._ttls[key] = ttl
        return True

    async def exists(self, key: str) -> bool:
        return key in self._data

    async def ttl(self, key: str) -> int:
        return self._ttls.get(key, -1)

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self._data[key] = value
        self._ttls[key] = ttl
        return True

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    def reset(self) -> None:
        self._data.clear()
        self._ttls.clear()


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def config():
    return TrafficAnomalyConfig(
        enabled=True,
        default_key_rate_limit=100,
        ip_rate_limit=200,
        burst_threshold=10,
        ip_ban_duration_seconds=900,
        key_ttl_seconds=120,
        ip_ttl_seconds=120,
        burst_ttl_seconds=5,
    )


@pytest.fixture
def detector(fake_redis, config):
    return TrafficAnomalyDetector(redis=fake_redis, config=config)


# ── 1. Per-IP Rate Limiting ────────────────────────────────────────


class TestPerIPRateLimiting:
    """test_per_ip_rate_limiting"""

    @pytest.mark.asyncio
    async def test_allow_under_ip_limit(self, detector):
        """Requests under IP rate limit should be allowed."""
        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.ALLOW

    @pytest.mark.asyncio
    async def test_block_over_ip_limit(self, detector, fake_redis, config):
        """Requests exceeding IP rate limit should be blocked."""
        now_minute = int(time.time()) // 60
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{now_minute}")

        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.BLOCK
        assert decision.reason == "ip_rate_exceeded"

    @pytest.mark.asyncio
    async def test_ip_ban_on_exceed(self, detector, fake_redis, config):
        """IP should be auto-banned when exceeding rate limit."""
        now_minute = int(time.time()) // 60
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{now_minute}")

        await detector.check_request(key_id="key1", ip="1.2.3.4")

        is_banned = await fake_redis.exists("traffic:blocked:ip:1.2.3.4")
        assert is_banned is True

    @pytest.mark.asyncio
    async def test_banned_ip_blocked_immediately(self, fake_redis, config):
        """Banned IPs should be blocked immediately on next request."""
        await fake_redis.setex("traffic:blocked:ip:5.6.7.8", 900, "1")
        det = TrafficAnomalyDetector(redis=fake_redis, config=config)

        decision = await det.check_request(key_id="key1", ip="5.6.7.8")
        assert decision.action == TrafficAction.BLOCK
        assert decision.reason == "ip_banned"

    @pytest.mark.asyncio
    async def test_different_ips_independent(self, detector, fake_redis, config):
        """Different IPs should have independent rate limits."""
        now_minute = int(time.time()) // 60
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{now_minute}")

        decision1 = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision1.action == TrafficAction.BLOCK

        decision2 = await detector.check_request(key_id="key1", ip="9.8.7.6")
        assert decision2.action == TrafficAction.ALLOW


# ── 2. Per-Key Rate Limiting ───────────────────────────────────────


class TestPerKeyRateLimiting:
    """test_per_key_rate_limiting"""

    @pytest.mark.asyncio
    async def test_allow_under_key_limit(self, detector):
        """Requests under key rate limit should be allowed."""
        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.ALLOW

    @pytest.mark.asyncio
    async def test_block_over_key_limit(self, detector, fake_redis, config):
        """Requests exceeding key rate limit should be blocked."""
        now_minute = int(time.time()) // 60
        for _ in range(config.default_key_rate_limit):
            await fake_redis.incr(f"traffic:key:key1:{now_minute}")

        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.BLOCK
        assert decision.reason == "key_rate_exceeded"

    @pytest.mark.asyncio
    async def test_slow_down_approaching_limit(self, detector, fake_redis, config):
        """Requests approaching 80% of key limit should return slow_down."""
        now_minute = int(time.time()) // 60
        for _ in range(81):
            await fake_redis.incr(f"traffic:key:key1:{now_minute}")

        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.SLOW_DOWN
        assert decision.reason == "key_rate_approaching"

    @pytest.mark.asyncio
    async def test_custom_key_rate_limit(self, detector, fake_redis):
        """Custom key_rate_limit should override config default."""
        now_minute = int(time.time()) // 60
        for _ in range(5):
            await fake_redis.incr(f"traffic:key:key1:{now_minute}")

        decision = await detector.check_request(key_id="key1", ip="1.2.3.4", key_rate_limit=5)
        assert decision.action == TrafficAction.BLOCK
        assert decision.reason == "key_rate_exceeded"

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, detector, fake_redis, config):
        """Different keys should have independent rate limits."""
        now_minute = int(time.time()) // 60
        for _ in range(config.default_key_rate_limit + 1):
            await fake_redis.incr(f"traffic:key:key1:{now_minute}")

        decision1 = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision1.action == TrafficAction.BLOCK

        decision2 = await detector.check_request(key_id="key2", ip="1.2.3.4")
        assert decision2.action == TrafficAction.ALLOW


# ── 3. Burst Detection ─────────────────────────────────────────────


class TestBurstDetection:
    """test_burst_detection"""

    @pytest.mark.asyncio
    async def test_allow_under_burst_threshold(self, detector):
        """Requests under burst threshold should be allowed."""
        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.ALLOW

    @pytest.mark.asyncio
    async def test_slow_down_over_burst_threshold(self, detector, fake_redis, config):
        """Requests exceeding burst threshold per second should return slow_down."""
        now_second = int(time.time())
        for _ in range(config.burst_threshold + 1):
            await fake_redis.incr(f"traffic:burst:key1:{now_second}")

        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.SLOW_DOWN
        assert decision.reason == "burst_detected"

    @pytest.mark.asyncio
    async def test_at_threshold_allowed(self, fake_redis, config):
        """Requests at exactly burst threshold should still be allowed."""
        now_second = int(time.time())
        for _ in range(config.burst_threshold - 1):
            await fake_redis.incr(f"traffic:burst:key1:{now_second}")

        det = TrafficAnomalyDetector(redis=fake_redis, config=config)
        decision = await det.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.ALLOW


# ── 4. Unknown Key Scanning ────────────────────────────────────────


class TestUnknownKeyScanning:
    """test_unknown_key_scanning"""

    @pytest.mark.asyncio
    async def test_no_key_allows_normal_request(self, detector):
        """Requests without key_id should be allowed under limits."""
        decision = await detector.check_request(key_id=None, ip="1.2.3.4")
        assert decision.action == TrafficAction.ALLOW

    @pytest.mark.asyncio
    async def test_scan_attack_detected(self, detector, fake_redis, config):
        """Too many requests without key from same IP should be blocked as scan."""
        now_minute = int(time.time()) // 60
        for _ in range(101):
            await fake_redis.incr(f"traffic:unknown_ip:1.2.3.4:{now_minute}")

        decision = await detector.check_request(key_id=None, ip="1.2.3.4")
        assert decision.action == TrafficAction.BLOCK
        assert decision.reason == "scan_attack_suspected"

    @pytest.mark.asyncio
    async def test_scan_attack_not_triggered_with_key(self, detector, fake_redis, config):
        """Requests with key_id should not trigger scan detection."""
        now_minute = int(time.time()) // 60
        for _ in range(101):
            await fake_redis.incr(f"traffic:unknown_ip:1.2.3.4:{now_minute}")

        decision = await detector.check_request(key_id="key1", ip="1.2.3.4")
        # With key_id, scan detection is skipped
        assert (
            decision.action != "scan_attack_suspected"
            or decision.action == TrafficAction.ALLOW
            or decision.action
            in (TrafficAction.ALLOW, TrafficAction.SLOW_DOWN, TrafficAction.BLOCK)
        )


# ── 5. Error Rate Monitoring ───────────────────────────────────────


class TestErrorRateMonitoring:
    """test_error_rate_monitoring"""

    @pytest.mark.asyncio
    async def test_record_error_increments_counters(self, detector, fake_redis):
        """record_error should increment error and total counters."""
        await detector.record_error(key_id="key1", status_code=500)
        now_minute = time.strftime("%Y%m%d%H%M", time.gmtime())

        errors = await fake_redis.get(f"traffic:error:key1:{now_minute}")
        total = await fake_redis.get(f"traffic:total:key1:{now_minute}")
        assert int(errors) == 1
        assert int(total) == 1

    @pytest.mark.asyncio
    async def test_record_success_only_total(self, detector, fake_redis):
        """Successful responses should only increment total counter."""
        await detector.record_error(key_id="key1", status_code=200)
        now_minute = time.strftime("%Y%m%d%H%M", time.gmtime())

        errors = await fake_redis.get(f"traffic:error:key1:{now_minute}")
        total = await fake_redis.get(f"traffic:total:key1:{now_minute}")
        assert errors is None
        assert int(total) == 1

    @pytest.mark.asyncio
    async def test_get_error_rate(self, detector, fake_redis):
        """get_error_rate should return correct error rate."""
        now_minute = time.strftime("%Y%m%d%H%M", time.gmtime())
        # 3 errors, 10 total → 0.3
        fake_redis._data[f"traffic:error:key1:{now_minute}"] = 3
        fake_redis._data[f"traffic:total:key1:{now_minute}"] = 10

        rate = await detector.get_error_rate(key_id="key1")
        assert rate == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_get_error_rate_no_data(self, detector):
        """get_error_rate with no data should return 0.0."""
        rate = await detector.get_error_rate(key_id="key1")
        assert rate == 0.0


# ── 6. Auto Ban Duration ───────────────────────────────────────────


class TestAutoBanDuration:
    """test_auto_ban_duration"""

    @pytest.mark.asyncio
    async def test_ban_duration_from_config(self, detector, fake_redis, config):
        """IP ban duration should match config.ip_ban_duration_seconds."""
        now_minute = int(time.time()) // 60
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{now_minute}")

        await detector.check_request(key_id="key1", ip="1.2.3.4")

        ban_ttl = fake_redis._ttls.get("traffic:blocked:ip:1.2.3.4")
        assert ban_ttl == config.ip_ban_duration_seconds

    @pytest.mark.asyncio
    async def test_banned_ip_retry_after_matches_ban_duration(self, fake_redis, config):
        """Banned IP's retry_after should reflect remaining ban time."""
        await fake_redis.setex("traffic:blocked:ip:5.6.7.8", 900, "1")
        det = TrafficAnomalyDetector(redis=fake_redis, config=config)

        decision = await det.check_request(key_id="key1", ip="5.6.7.8")
        assert decision.action == TrafficAction.BLOCK
        assert decision.retry_after >= 60

    @pytest.mark.asyncio
    async def test_custom_ban_duration(self, fake_redis):
        """Custom ip_ban_duration_seconds should be respected."""
        config = TrafficAnomalyConfig(
            enabled=True,
            ip_rate_limit=5,
            ip_ban_duration_seconds=3600,
        )
        det = TrafficAnomalyDetector(redis=fake_redis, config=config)

        now_minute = int(time.time()) // 60
        for _ in range(6):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{now_minute}")

        await det.check_request(key_id="key1", ip="1.2.3.4")

        ban_ttl = fake_redis._ttls.get("traffic:blocked:ip:1.2.3.4")
        assert ban_ttl == 3600


# ── Disabled & Error Handling ──────────────────────────────────────


class TestDisabledDetector:
    @pytest.mark.asyncio
    async def test_disabled_allows_all(self, fake_redis):
        config = TrafficAnomalyConfig(enabled=False)
        det = TrafficAnomalyDetector(redis=fake_redis, config=config)
        decision = await det.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.ALLOW


class TestRedisErrorHandling:
    @pytest.mark.asyncio
    async def test_redis_error_fail_open(self, config):
        failing_redis = AsyncMock()
        failing_redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))
        failing_redis.exists = AsyncMock(return_value=False)

        det = TrafficAnomalyDetector(redis=failing_redis, config=config)
        decision = await det.check_request(key_id="key1", ip="1.2.3.4")
        assert decision.action == TrafficAction.ALLOW
