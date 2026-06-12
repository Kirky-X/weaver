# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test rate limit fail-close behavior with local token bucket fallback.

Validates GAP-M06 fix: When Redis is unavailable, rate limiting switches
to a local in-memory token bucket (fail-close) instead of pass-through.
"""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.middleware.rate_limit import (
    LocalTokenBucket,
    RateLimitMiddleware,
    TokenBucketRateLimiter,
)


class TestLocalTokenBucket:
    """Verify LocalTokenBucket in-memory token bucket implementation."""

    def test_allows_within_capacity(self) -> None:
        """Requests within bucket capacity should be allowed."""
        bucket = LocalTokenBucket(max_tokens=5, refill_rate=5)
        for _ in range(5):
            assert bucket.acquire() is True

    def test_rejects_when_exhausted(self) -> None:
        """Requests exceeding bucket capacity should be rejected."""
        bucket = LocalTokenBucket(max_tokens=3, refill_rate=1)
        for _ in range(3):
            assert bucket.acquire() is True
        assert bucket.acquire() is False

    def test_refills_over_time(self) -> None:
        """Tokens should refill based on elapsed time and refill rate."""
        bucket = LocalTokenBucket(max_tokens=5, refill_rate=10)
        # Exhaust all tokens
        for _ in range(5):
            bucket.acquire()
        assert bucket.acquire() is False

        # Get the last_time from the internal bucket state
        _, last_time = bucket._buckets["_default"]

        # Simulate time passing: 0.5s * 10 tokens/s = 5 tokens refilled
        with patch("api.middleware.rate_limit.time.monotonic", return_value=last_time + 0.5):
            assert bucket.acquire() is True

    def test_does_not_exceed_max_tokens(self) -> None:
        """Refill should not exceed max_tokens."""
        bucket = LocalTokenBucket(max_tokens=3, refill_rate=100)
        # First call initializes the bucket
        bucket.acquire()
        _, last_time = bucket._buckets["_default"]
        # Wait a long time — tokens should cap at max_tokens
        with patch("api.middleware.rate_limit.time.monotonic", return_value=last_time + 100):
            for _ in range(3):
                assert bucket.acquire() is True
            assert bucket.acquire() is False

    def test_per_key_isolation(self) -> None:
        """Different keys should have independent buckets."""
        bucket = LocalTokenBucket(max_tokens=2, refill_rate=1)
        assert bucket.acquire("key_a") is True
        assert bucket.acquire("key_a") is True
        assert bucket.acquire("key_a") is False  # key_a exhausted
        assert bucket.acquire("key_b") is True  # key_b still has tokens


class TestTokenBucketRateLimiterFailClose:
    """Verify TokenBucketRateLimiter fail-close behavior on Redis failure."""

    @pytest.mark.asyncio
    async def test_redis_normal_uses_redis(self) -> None:
        """When Redis is available, should use Redis token bucket."""
        redis_mock = MagicMock()
        script_mock = AsyncMock(return_value=[1, 999])
        redis_mock.register_script = MagicMock(return_value=script_mock)

        limiter = TokenBucketRateLimiter(redis=redis_mock)
        allowed, remaining = await limiter.acquire("client1")
        assert allowed is True
        assert remaining == 999
        # Redis script should have been called
        assert script_mock.call_count >= 1

    @pytest.mark.asyncio
    async def test_redis_error_falls_back_to_local(self) -> None:
        """When Redis raises an exception, should fall back to local bucket."""
        redis_mock = MagicMock()
        script_mock = AsyncMock(side_effect=Exception("Redis connection refused"))
        redis_mock.register_script = MagicMock(return_value=script_mock)

        limiter = TokenBucketRateLimiter(redis=redis_mock)
        allowed, remaining = await limiter.acquire("client1")
        # Fail-close: should still rate-limit via local bucket
        assert allowed is True  # first request should pass
        # The fallback flag should be set
        assert limiter._fallback_active is True

    @pytest.mark.asyncio
    async def test_local_bucket_exhaustion_returns_429(self) -> None:
        """When local bucket is exhausted, should return not-allowed."""
        redis_mock = MagicMock()
        script_mock = AsyncMock(side_effect=Exception("Redis down"))
        redis_mock.register_script = MagicMock(return_value=script_mock)

        limiter = TokenBucketRateLimiter(
            redis=redis_mock,
            global_max_tokens=2,
            global_refill_rate=1,
            per_key_max_tokens=100,
            per_key_refill_rate=100,
        )
        # Exhaust global bucket
        assert (await limiter.acquire("client1"))[0] is True
        assert (await limiter.acquire("client1"))[0] is True
        # Third request should be denied
        assert (await limiter.acquire("client1"))[0] is False

    @pytest.mark.asyncio
    async def test_no_redis_uses_local_bucket(self) -> None:
        """When redis is None, should use local bucket from the start."""
        limiter = TokenBucketRateLimiter(
            redis=None,
            global_max_tokens=3,
            global_refill_rate=1,
            per_key_max_tokens=100,
            per_key_refill_rate=100,
        )
        # Should allow within capacity
        for _ in range(3):
            assert (await limiter.acquire("client1"))[0] is True
        # Should deny when exhausted
        assert (await limiter.acquire("client1"))[0] is False

    @pytest.mark.asyncio
    async def test_redis_error_logs_critical(self) -> None:
        """Redis exception should trigger CRITICAL log."""
        redis_mock = MagicMock()
        script_mock = AsyncMock(side_effect=Exception("Redis connection refused"))
        redis_mock.register_script = MagicMock(return_value=script_mock)

        limiter = TokenBucketRateLimiter(redis=redis_mock)
        with patch("api.middleware.rate_limit.log") as mock_log:
            await limiter.acquire("client1")
            mock_log.critical.assert_called_once()
            call_kwargs = mock_log.critical.call_args[1]
            assert "client_ip" in call_kwargs or "client" in call_kwargs


class TestRateLimitMiddlewareFallbackHeader:
    """Verify X-RateLimit-Fallback header in middleware responses."""

    @staticmethod
    async def _simple_asgi_app(scope: dict, receive: Any, send: Any) -> None:
        """A minimal ASGI app that sends a 200 response."""
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [[b"content-type", b"application/json"]],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"status":"ok"}',
            }
        )

    @pytest.mark.asyncio
    async def test_fallback_header_present_on_redis_failure(self) -> None:
        """When using local fallback, response should include X-RateLimit-Fallback header."""
        redis_mock = MagicMock()
        script_mock = AsyncMock(side_effect=Exception("Redis down"))
        redis_mock.register_script = MagicMock(return_value=script_mock)

        limiter = TokenBucketRateLimiter(redis=redis_mock)
        middleware = RateLimitMiddleware(app=self._simple_asgi_app, rate_limiter=limiter)

        # First request triggers fallback
        await limiter.acquire("client1")

        # Build ASGI scope for a request
        scope = {
            "type": "http",
            "client": ("127.0.0.1", 12345),
            "headers": [],
        }
        sent_messages: list[dict] = []

        async def mock_send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, AsyncMock(), mock_send)

        # Check response headers for X-RateLimit-Fallback
        response_start = sent_messages[0]
        assert response_start["type"] == "http.response.start"
        headers = response_start["headers"]
        header_names = [h[0] for h in headers]
        assert b"x-ratelimit-fallback" in header_names

    @pytest.mark.asyncio
    async def test_no_fallback_header_when_redis_healthy(self) -> None:
        """When Redis is healthy, no X-RateLimit-Fallback header should be present."""
        redis_mock = MagicMock()
        script_mock = AsyncMock(return_value=[1, 999])
        redis_mock.register_script = MagicMock(return_value=script_mock)

        limiter = TokenBucketRateLimiter(redis=redis_mock)
        middleware = RateLimitMiddleware(app=self._simple_asgi_app, rate_limiter=limiter)

        scope = {
            "type": "http",
            "client": ("127.0.0.1", 12345),
            "headers": [],
        }
        sent_messages: list[dict] = []

        async def mock_send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, AsyncMock(), mock_send)

        response_start = sent_messages[0]
        headers = response_start["headers"]
        header_names = [h[0] for h in headers]
        assert b"x-ratelimit-fallback" not in header_names

    @pytest.mark.asyncio
    async def test_429_response_when_local_bucket_exhausted(self) -> None:
        """When local bucket is exhausted, should return HTTP 429."""
        redis_mock = MagicMock()
        script_mock = AsyncMock(side_effect=Exception("Redis down"))
        redis_mock.register_script = MagicMock(return_value=script_mock)

        limiter = TokenBucketRateLimiter(
            redis=redis_mock,
            global_max_tokens=1,
            global_refill_rate=1,
            per_key_max_tokens=100,
            per_key_refill_rate=100,
        )
        middleware = RateLimitMiddleware(app=self._simple_asgi_app, rate_limiter=limiter)

        scope = {
            "type": "http",
            "client": ("127.0.0.1", 12345),
            "headers": [],
        }

        # First request passes
        await middleware(scope, AsyncMock(), AsyncMock())

        # Second request should be 429
        sent_messages: list[dict] = []

        async def mock_send(message: dict) -> None:
            sent_messages.append(message)

        await middleware(scope, AsyncMock(), mock_send)
        response_start = sent_messages[0]
        assert response_start["status"] == 429
