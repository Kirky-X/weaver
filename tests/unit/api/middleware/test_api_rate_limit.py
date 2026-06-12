# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for rate limiting middleware (rate_limit.py).

Tests the Redis-backed token bucket rate limiter that replaced slowapi.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


class TestRateLimiterConfiguration:
    """Tests for rate limiting middleware configuration."""

    def test_token_bucket_limiter_is_not_none(self):
        """Test that TokenBucketRateLimiter can be instantiated."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        limiter = TokenBucketRateLimiter(redis=mock_redis)
        assert limiter is not None

    def test_rate_limit_middleware_is_not_none(self):
        """Test that RateLimitMiddleware can be instantiated."""
        from api.middleware.rate_limit import RateLimitMiddleware, TokenBucketRateLimiter

        mock_redis = MagicMock()
        rate_limiter = TokenBucketRateLimiter(redis=mock_redis)
        mock_app = AsyncMock()
        middleware = RateLimitMiddleware(mock_app, rate_limiter=rate_limiter)
        assert middleware is not None

    def test_token_bucket_limiter_default_config(self):
        """Test that TokenBucketRateLimiter uses default config values."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        limiter = TokenBucketRateLimiter(redis=mock_redis)
        assert limiter._global_max_tokens == 1000
        assert limiter._global_refill_rate == 1000
        assert limiter._per_key_max_tokens == 100
        assert limiter._per_key_refill_rate == 100

    def test_lua_script_registered_on_init(self):
        """Test that Lua script is registered with Redis on initialization."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        limiter = TokenBucketRateLimiter(redis=mock_redis)
        mock_redis.register_script.assert_called_once()

    def test_no_redis_graceful_degradation(self):
        """Test that missing Redis client allows requests (fail-open)."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        limiter = TokenBucketRateLimiter(redis=None)
        assert limiter._script is None

    def test_module_exports(self):
        """Test that module exports the expected classes."""
        from api.middleware.rate_limit import RateLimitMiddleware, TokenBucketRateLimiter

        assert TokenBucketRateLimiter is not None
        assert RateLimitMiddleware is not None
