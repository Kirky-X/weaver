# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for traffic anomaly detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.middleware.traffic_anomaly import (
    TrafficAnomalyConfig,
    TrafficAnomalyDetector,
    TrafficAnomalyMiddleware,
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
    """Create a fake Redis client."""
    return FakeRedis()


@pytest.fixture
def config():
    """Create a TrafficAnomalyConfig with test values."""
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
    """Create a TrafficAnomalyDetector with fake Redis."""
    return TrafficAnomalyDetector(redis=fake_redis, config=config)


class TestTrafficDecision:
    """Tests for TrafficDecision dataclass."""

    def test_default_decision_is_allow(self):
        decision = TrafficDecision()
        assert decision.action == "allow"
        assert decision.reason == ""
        assert decision.retry_after == 0

    def test_block_decision(self):
        decision = TrafficDecision(action="block", reason="key_rate_exceeded", retry_after=60)
        assert decision.action == "block"
        assert decision.reason == "key_rate_exceeded"
        assert decision.retry_after == 60

    def test_slow_down_decision(self):
        decision = TrafficDecision(action="slow_down", reason="burst_detected", retry_after=5)
        assert decision.action == "slow_down"
        assert decision.reason == "burst_detected"


class TestTrafficAnomalyConfig:
    """Tests for TrafficAnomalyConfig defaults."""

    def test_default_config(self):
        config = TrafficAnomalyConfig()
        assert config.enabled is True
        assert config.default_key_rate_limit == 200
        assert config.ip_rate_limit == 200
        assert config.burst_threshold == 10
        assert config.ip_ban_duration_seconds == 900
        assert config.key_ttl_seconds == 120
        assert config.ip_ttl_seconds == 120
        assert config.burst_ttl_seconds == 5


class TestPerKeyRateDetection:
    """Tests for per-Key rate detection (task 24.1)."""

    @pytest.mark.asyncio
    async def test_allow_under_limit(self, detector, fake_redis):
        """Requests under the rate limit should be allowed."""
        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_block_over_limit(self, detector, fake_redis, config):
        """Requests exceeding rate_limit_per_min should return block."""
        # Simulate 100 requests (at the limit)
        for _ in range(config.default_key_rate_limit):
            await fake_redis.incr(f"traffic:key:key1:{int(__import__('time').time()) // 60}")

        # Next request should be blocked
        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "block"
        assert decision.reason == "key_rate_exceeded"
        assert decision.retry_after == 60

    @pytest.mark.asyncio
    async def test_slow_down_approaching_limit(self, detector, fake_redis, config):
        """Requests approaching 80% of limit should return slow_down."""
        # Simulate 81 requests (81% of 100)
        for _ in range(81):
            await fake_redis.incr(f"traffic:key:key1:{int(__import__('time').time()) // 60}")

        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "slow_down"
        assert decision.reason == "key_rate_approaching"

    @pytest.mark.asyncio
    async def test_custom_key_rate_limit(self, detector, fake_redis):
        """Custom key rate limit should override config default."""
        # Simulate 5 requests
        for _ in range(5):
            await fake_redis.incr(f"traffic:key:key1:{int(__import__('time').time()) // 60}")

        # With custom limit of 5, the 6th request should be blocked
        decision = await detector.check_request("key1", "1.2.3.4", key_rate_limit=5)
        assert decision.action == "block"
        assert decision.reason == "key_rate_exceeded"

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, detector, fake_redis, config):
        """Different keys should have independent rate limits."""
        # Exhaust key1
        for _ in range(config.default_key_rate_limit + 1):
            await fake_redis.incr(f"traffic:key:key1:{int(__import__('time').time()) // 60}")

        # key1 should be blocked
        decision1 = await detector.check_request("key1", "1.2.3.4")
        assert decision1.action == "block"

        # key2 should still be allowed
        decision2 = await detector.check_request("key2", "1.2.3.4")
        assert decision2.action == "allow"


class TestPerIPRateDetection:
    """Tests for per-IP rate detection (task 24.3)."""

    @pytest.mark.asyncio
    async def test_allow_under_ip_limit(self, detector, fake_redis):
        """Requests under IP rate limit should be allowed."""
        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_block_over_ip_limit(self, detector, fake_redis, config):
        """Requests exceeding IP rate limit should return block and ban IP."""
        # Simulate 200 requests from same IP (at the limit)
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{int(__import__('time').time()) // 60}")

        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "block"
        assert decision.reason == "ip_rate_exceeded"

    @pytest.mark.asyncio
    async def test_ip_ban_on_exceed(self, detector, fake_redis, config):
        """IP should be banned when exceeding rate limit."""
        # Simulate exceeding IP rate limit
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{int(__import__('time').time()) // 60}")

        await detector.check_request("key1", "1.2.3.4")

        # Verify IP is banned
        is_banned = await fake_redis.exists("traffic:blocked:ip:1.2.3.4")
        assert is_banned is True

    @pytest.mark.asyncio
    async def test_banned_ip_blocked(self, detector, fake_redis):
        """Banned IPs should be blocked immediately."""
        # Manually ban an IP
        await fake_redis.setex("traffic:blocked:ip:5.6.7.8", 900, "1")

        decision = await detector.check_request("key1", "5.6.7.8")
        assert decision.action == "block"
        assert decision.reason == "ip_banned"

    @pytest.mark.asyncio
    async def test_different_ips_independent(self, detector, fake_redis, config):
        """Different IPs should have independent rate limits."""
        # Exhaust IP1
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{int(__import__('time').time()) // 60}")

        # IP1 should be blocked
        decision1 = await detector.check_request("key1", "1.2.3.4")
        assert decision1.action == "block"

        # IP2 should still be allowed
        decision2 = await detector.check_request("key1", "9.8.7.6")
        assert decision2.action == "allow"


class TestBurstDetection:
    """Tests for burst detection (task 24.4)."""

    @pytest.mark.asyncio
    async def test_allow_under_burst_threshold(self, detector, fake_redis):
        """Requests under burst threshold should be allowed."""
        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_slow_down_over_burst_threshold(self, detector, fake_redis, config):
        """Requests exceeding burst threshold per second should return slow_down."""
        # Simulate 11 requests in the same second (burst_threshold=10)
        for _ in range(config.burst_threshold + 1):
            await fake_redis.incr(f"traffic:burst:key1:{int(__import__('time').time())}")

        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "slow_down"
        assert decision.reason == "burst_detected"
        assert decision.retry_after == 5

    @pytest.mark.asyncio
    async def test_burst_at_threshold_allowed(self, detector, fake_redis, config):
        """Requests at exactly burst threshold should be allowed."""
        # Simulate exactly 10 requests (at threshold)
        for _ in range(config.burst_threshold):
            await fake_redis.incr(f"traffic:burst:key1:{int(__import__('time').time())}")

        decision = await detector.check_request("key1", "1.2.3.4")
        # The 11th request (this one) pushes it over threshold
        # Actually, the check_request itself also increments, so at threshold=10,
        # the 10th increment + this one = 11 > 10 → slow_down
        # Let's test with 9 pre-existing requests
        fake_redis2 = FakeRedis()
        detector2 = TrafficAnomalyDetector(redis=fake_redis2, config=config)
        for _ in range(config.burst_threshold - 1):
            await fake_redis2.incr(f"traffic:burst:key1:{int(__import__('time').time())}")

        decision = await detector2.check_request("key1", "1.2.3.4")
        # The 10th request (this one) = threshold, should still be allowed
        assert decision.action == "allow"


class TestRedisKeyDesign:
    """Tests for Redis key design (task 24.5)."""

    @pytest.mark.asyncio
    async def test_key_rate_redis_key_format(self, detector, fake_redis):
        """Per-Key rate Redis key should follow traffic:key:{key_id}:{minute}."""
        import time

        now_minute = int(time.time()) // 60
        expected_key = f"traffic:key:test_key:{now_minute}"

        await detector.check_request("test_key", "1.2.3.4")

        assert expected_key in fake_redis._data

    @pytest.mark.asyncio
    async def test_ip_rate_redis_key_format(self, detector, fake_redis):
        """Per-IP rate Redis key should follow traffic:ip:{ip}:{minute}."""
        import time

        now_minute = int(time.time()) // 60
        expected_key = f"traffic:ip:1.2.3.4:{now_minute}"

        await detector.check_request("key1", "1.2.3.4")

        assert expected_key in fake_redis._data

    @pytest.mark.asyncio
    async def test_burst_redis_key_format(self, detector, fake_redis):
        """Burst detection Redis key should follow traffic:burst:{key_id}:{second}."""
        import time

        now_second = int(time.time())
        expected_key = f"traffic:burst:key1:{now_second}"

        await detector.check_request("key1", "1.2.3.4")

        assert expected_key in fake_redis._data

    @pytest.mark.asyncio
    async def test_blocked_ip_redis_key_format(self, detector, fake_redis, config):
        """Blocked IP Redis key should follow traffic:blocked:ip:{ip}."""
        # Simulate exceeding IP rate limit to trigger ban
        for _ in range(config.ip_rate_limit + 1):
            await fake_redis.incr(f"traffic:ip:1.2.3.4:{int(__import__('time').time()) // 60}")

        await detector.check_request("key1", "1.2.3.4")

        expected_key = "traffic:blocked:ip:1.2.3.4"
        assert expected_key in fake_redis._data

    @pytest.mark.asyncio
    async def test_redis_keys_have_ttl(self, detector, fake_redis):
        """Redis keys should have TTL set to prevent memory leaks."""
        await detector.check_request("key1", "1.2.3.4")

        # At least some keys should have TTLs set
        assert len(fake_redis._ttls) > 0


class TestTrafficAnomalyDetectorDisabled:
    """Tests for disabled detector."""

    @pytest.mark.asyncio
    async def test_disabled_allows_all(self, fake_redis):
        """When disabled, all requests should be allowed."""
        config = TrafficAnomalyConfig(enabled=False)
        detector = TrafficAnomalyDetector(redis=fake_redis, config=config)

        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "allow"


class TestTrafficAnomalyDetectorErrorHandling:
    """Tests for Redis error handling."""

    @pytest.mark.asyncio
    async def test_redis_error_allows_request(self, config):
        """When Redis fails, requests should be allowed (fail-open)."""
        failing_redis = AsyncMock()
        failing_redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))
        failing_redis.exists = AsyncMock(return_value=False)

        detector = TrafficAnomalyDetector(redis=failing_redis, config=config)
        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "allow"

    @pytest.mark.asyncio
    async def test_redis_exists_error_allows_request(self, config):
        """When Redis exists check fails, requests should be allowed."""
        failing_redis = AsyncMock()
        failing_redis.exists = AsyncMock(side_effect=ConnectionError("Redis down"))

        detector = TrafficAnomalyDetector(redis=failing_redis, config=config)
        decision = await detector.check_request("key1", "1.2.3.4")
        assert decision.action == "allow"


class TestTrafficAnomalyMiddleware:
    """Tests for TrafficAnomalyMiddleware."""

    def _create_app(self, detector):
        """Create a FastAPI app with the middleware."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(TrafficAnomalyMiddleware, detector=detector)

        @app.get("/test")
        async def test_endpoint():
            return {"message": "success"}

        @app.get("/health")
        async def health_endpoint():
            return {"status": "healthy"}

        @app.get("/metrics")
        async def metrics_endpoint():
            return {"metrics": "data"}

        return TestClient(app)

    def test_allowed_request_passes_through(self, detector):
        """Allowed requests should pass through normally."""
        client = self._create_app(detector)
        response = client.get("/test")
        assert response.status_code == 200

    def test_skip_paths_not_checked(self, detector):
        """Health and metrics endpoints should skip traffic checks."""
        client = self._create_app(detector)
        response = client.get("/health")
        assert response.status_code == 200

        response = client.get("/metrics")
        assert response.status_code == 200

    def test_blocked_request_returns_429(self, fake_redis, config):
        """Blocked requests should return 429 with Retry-After header."""
        # Pre-fill key rate counter to exceed limit
        import time

        now_minute = int(time.time()) // 60
        for _ in range(config.default_key_rate_limit + 1):
            fake_redis._data[f"traffic:key:anonymous:{now_minute}"] = (
                config.default_key_rate_limit + 1
            )

        detector = TrafficAnomalyDetector(redis=fake_redis, config=config)
        client = self._create_app(detector)

        response = client.get("/test")
        assert response.status_code == 429
        assert "Retry-After" in response.headers
