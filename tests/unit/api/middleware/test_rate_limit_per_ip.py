# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for per-IP rate limiting.

TDD Phase 1: Write tests first, then implement.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.middleware.rate_limit import (
    _GLOBAL_BUCKET_PREFIX,
    _PER_IP_BUCKET_PREFIX,
    _PER_KEY_BUCKET_PREFIX,
    LocalTokenBucket,
    RateLimitMiddleware,
    TokenBucketRateLimiter,
)

# ── Per-IP Token Bucket Configuration ──────────────────────────────


class TestPerIPConfiguration:
    """Test per-IP rate limiter configuration."""

    def test_default_per_ip_config(self) -> None:
        """Default per-IP config should be 3000 tokens, 50/s refill."""
        limiter = TokenBucketRateLimiter(redis=None)
        assert limiter._per_ip_max_tokens == 3000
        assert limiter._per_ip_refill_rate == 50

    def test_custom_per_ip_config(self) -> None:
        """Custom per-IP config should be accepted."""
        limiter = TokenBucketRateLimiter(
            redis=None,
            per_ip_max_tokens=5000,
            per_ip_refill_rate=100,
        )
        assert limiter._per_ip_max_tokens == 5000
        assert limiter._per_ip_refill_rate == 100


class TestPerIPLocalBucket:
    """Test per-IP limiting with local token bucket (Redis unavailable)."""

    def test_per_ip_bucket_independent_of_per_key(self) -> None:
        """Per-IP bucket should be independent from per-key bucket."""
        # With very small per-IP limit, should be blocked quickly
        limiter = TokenBucketRateLimiter(
            redis=None,
            per_ip_max_tokens=2,
            per_ip_refill_rate=1,
            per_key_max_tokens=100,
            per_key_refill_rate=100,
        )
        # Consume 2 tokens for same IP
        allowed1, _ = limiter._acquire_local(client_key="1.2.3.4", api_key=None)
        allowed2, _ = limiter._acquire_local(client_key="1.2.3.4", api_key=None)
        allowed3, _ = limiter._acquire_local(client_key="1.2.3.4", api_key=None)

        assert allowed1 is True
        assert allowed2 is True
        assert allowed3 is False  # per-IP exhausted

    def test_same_ip_multiple_api_keys_per_ip_limit(self) -> None:
        """Same IP with different API keys should still hit per-IP limit."""
        limiter = TokenBucketRateLimiter(
            redis=None,
            per_ip_max_tokens=2,
            per_ip_refill_rate=1,
            per_key_max_tokens=100,
            per_key_refill_rate=100,
        )
        # Same IP, different API keys
        allowed1, _ = limiter._acquire_local(client_key="1.2.3.4", api_key="key-a")
        allowed2, _ = limiter._acquire_local(client_key="1.2.3.4", api_key="key-b")
        allowed3, _ = limiter._acquire_local(client_key="1.2.3.4", api_key="key-c")

        assert allowed1 is True
        assert allowed2 is True
        assert allowed3 is False  # per-IP exhausted despite different API keys

    def test_different_ips_independent(self) -> None:
        """Different IPs should have independent per-IP buckets."""
        limiter = TokenBucketRateLimiter(
            redis=None,
            per_ip_max_tokens=1,
            per_ip_refill_rate=1,
            per_key_max_tokens=100,
            per_key_refill_rate=100,
        )
        # Different IPs
        allowed1, _ = limiter._acquire_local(client_key="1.2.3.4", api_key=None)
        allowed2, _ = limiter._acquire_local(client_key="5.6.7.8", api_key=None)

        assert allowed1 is True
        assert allowed2 is True

    def test_per_ip_limit_with_api_key(self) -> None:
        """Per-IP limit should still apply when API key is present."""
        limiter = TokenBucketRateLimiter(
            redis=None,
            per_ip_max_tokens=1,
            per_ip_refill_rate=1,
            per_key_max_tokens=100,
            per_key_refill_rate=100,
        )
        allowed1, _ = limiter._acquire_local(client_key="1.2.3.4", api_key="my-key")
        allowed2, _ = limiter._acquire_local(client_key="1.2.3.4", api_key="my-key")

        assert allowed1 is True
        assert allowed2 is False  # per-IP exhausted


class TestPerIPRedisBucket:
    """Test per-IP limiting with Redis Lua script."""

    @pytest.mark.asyncio
    async def test_acquire_checks_per_ip_bucket(self) -> None:
        """acquire() should check per-IP bucket between global and per-key."""
        mock_script = AsyncMock(return_value=[1, 100])
        mock_redis = MagicMock()
        mock_redis.register_script = MagicMock(return_value=mock_script)

        limiter = TokenBucketRateLimiter(
            redis=mock_redis,
            per_ip_max_tokens=3000,
            per_ip_refill_rate=50,
        )

        allowed, remaining = await limiter.acquire(
            client_key="1.2.3.4",
            api_key="my-key",
        )

        assert allowed is True
        # Script should be called 3 times: global, per-IP, per-key
        assert mock_script.call_count == 3

        # Second call should be per-IP
        second_call_keys = (
            mock_script.call_args_list[1][1].get("keys") or mock_script.call_args_list[1][0][0]
            if mock_script.call_args_list[1][0]
            else None
        )
        # Check the per-IP key format
        per_ip_call = mock_script.call_args_list[1]
        keys_arg = per_ip_call[1].get("keys") or per_ip_call.kwargs.get("keys")
        if keys_arg:
            assert _PER_IP_BUCKET_PREFIX in keys_arg[0]

    @pytest.mark.asyncio
    async def test_acquire_per_ip_blocked(self) -> None:
        """When per-IP bucket is empty, request should be blocked."""
        call_count = 0

        async def mock_script_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [1, 100]  # global allowed
            elif call_count == 2:
                return [0, 0]  # per-IP blocked
            return [1, 100]

        mock_redis = MagicMock()
        mock_script = mock_script_fn
        mock_redis.register_script = MagicMock(return_value=mock_script)

        limiter = TokenBucketRateLimiter(
            redis=mock_redis,
            per_ip_max_tokens=3000,
            per_ip_refill_rate=50,
        )

        allowed, remaining = await limiter.acquire(
            client_key="1.2.3.4",
            api_key="my-key",
        )

        assert allowed is False
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_acquire_per_ip_no_api_key(self) -> None:
        """Without API key, per-IP should still be checked."""
        mock_script = AsyncMock(return_value=[1, 100])
        mock_redis = MagicMock()
        mock_redis.register_script = MagicMock(return_value=mock_script)

        limiter = TokenBucketRateLimiter(
            redis=mock_redis,
            per_ip_max_tokens=3000,
            per_ip_refill_rate=50,
        )

        allowed, remaining = await limiter.acquire(
            client_key="1.2.3.4",
            api_key=None,
        )

        assert allowed is True
        # Should still be 3 calls: global, per-IP, per-key (using IP as key)
        assert mock_script.call_count == 3


class TestPerIPKeyPrefixes:
    """Test Redis key prefixes for per-IP buckets."""

    def test_per_ip_prefix_exists(self) -> None:
        """Per-IP bucket prefix should be defined."""
        assert _PER_IP_BUCKET_PREFIX == "ratelimit:ip"

    def test_per_ip_prefix_distinct_from_per_key(self) -> None:
        """Per-IP prefix should be distinct from per-key prefix."""
        assert _PER_IP_BUCKET_PREFIX != _PER_KEY_BUCKET_PREFIX
