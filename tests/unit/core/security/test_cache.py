# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for URLSecurityCache."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.security.cache import URLSecurityCache
from core.security.models import URLRisk


class TestURLSecurityCache:
    """Tests for URL security caching."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create mock Redis client."""
        redis = MagicMock()
        redis.get = AsyncMock()
        redis.setex = AsyncMock()
        redis.delete = AsyncMock()
        redis.keys = AsyncMock(return_value=[])
        return redis

    @pytest.fixture
    def cache(self, mock_redis: MagicMock) -> URLSecurityCache:
        """Create cache instance with mock Redis."""
        return URLSecurityCache(
            redis_client=mock_redis,
            safe_ttl=21600,
            malicious_ttl=900,
            enabled=True,
        )

    @pytest.fixture
    def disabled_cache(self, mock_redis: MagicMock) -> URLSecurityCache:
        """Create disabled cache instance."""
        return URLSecurityCache(
            redis_client=mock_redis,
            safe_ttl=21600,
            malicious_ttl=900,
            enabled=False,
        )

    @pytest.fixture
    def memory_cache(self) -> URLSecurityCache:
        """Create in-memory cache (no Redis)."""
        return URLSecurityCache(
            redis_client=None,
            safe_ttl=21600,
            malicious_ttl=900,
            enabled=True,
        )

    # ── Get Operations ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_cached_safe(self, cache: URLSecurityCache, mock_redis: MagicMock) -> None:
        """Get cached safe URL result."""
        mock_redis.get.return_value = '{"risk": "safe", "is_safe": true}'

        result = await cache.get("https://example.com")

        assert result is not None
        assert result["risk"] == "safe"
        assert result["is_safe"] is True

    @pytest.mark.asyncio
    async def test_get_cached_malicious(
        self, cache: URLSecurityCache, mock_redis: MagicMock
    ) -> None:
        """Get cached malicious URL result."""
        mock_redis.get.return_value = '{"risk": "blocked", "is_safe": false}'

        result = await cache.get("https://malicious.example.com")

        assert result is not None
        assert result["is_safe"] is False

    @pytest.mark.asyncio
    async def test_get_not_cached(self, cache: URLSecurityCache, mock_redis: MagicMock) -> None:
        """Get URL not in cache."""
        mock_redis.get.return_value = None

        result = await cache.get("https://unknown.example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_disabled_returns_none(self, disabled_cache: URLSecurityCache) -> None:
        """Disabled cache should return None."""
        result = await disabled_cache.get("https://example.com")

        assert result is None

    # ── Set Operations ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_set_safe_result(self, cache: URLSecurityCache, mock_redis: MagicMock) -> None:
        """Set safe URL result with longer TTL."""
        await cache.set(
            url="https://example.com",
            result={"risk": "safe", "is_safe": True},
            risk="safe",
        )

        mock_redis.setex.assert_called_once()
        # Check that safe TTL is used
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 21600  # safe_ttl

    @pytest.mark.asyncio
    async def test_set_malicious_result(
        self, cache: URLSecurityCache, mock_redis: MagicMock
    ) -> None:
        """Set malicious URL result with shorter TTL."""
        await cache.set(
            url="https://malicious.example.com",
            result={"risk": "blocked", "is_safe": False},
            risk="blocked",
        )

        mock_redis.setex.assert_called_once()
        # Check that malicious TTL is used
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 900  # malicious_ttl

    @pytest.mark.asyncio
    async def test_set_high_risk_uses_malicious_ttl(
        self, cache: URLSecurityCache, mock_redis: MagicMock
    ) -> None:
        """High risk URL should use malicious TTL."""
        await cache.set(
            url="https://example.com",
            result={"risk": "high"},
            risk="high",
        )

        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 900  # malicious_ttl

    @pytest.mark.asyncio
    async def test_set_disabled_noop(self, disabled_cache: URLSecurityCache) -> None:
        """Disabled cache should not set."""
        # Should not raise
        await disabled_cache.set(
            url="https://example.com",
            result={"risk": "safe", "is_safe": True},
            risk="safe",
        )

    # ── In-Memory Cache (No Redis) ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_memory_cache_returns_none(self, memory_cache: URLSecurityCache) -> None:
        """In-memory cache without Redis should return None on get."""
        result = await memory_cache.get("https://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_memory_cache_set_noop(self, memory_cache: URLSecurityCache) -> None:
        """In-memory cache without Redis should silently ignore set."""
        # Should not raise
        await memory_cache.set(
            url="https://example.com",
            result={"risk": "safe"},
            risk="safe",
        )

    # ── Delete Operations ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_cached(self, cache: URLSecurityCache, mock_redis: MagicMock) -> None:
        """Delete cached URL."""
        await cache.delete("https://example.com")

        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_disabled_noop(self, disabled_cache: URLSecurityCache) -> None:
        """Disabled cache delete should be noop."""
        await disabled_cache.delete("https://example.com")
        # Should not raise

    # ── Edge Cases ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_invalid_json(self, cache: URLSecurityCache, mock_redis: MagicMock) -> None:
        """Invalid JSON in cache should return None."""
        mock_redis.get.return_value = "not valid json"

        result = await cache.get("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_different_risks_different_ttls(
        self, cache: URLSecurityCache, mock_redis: MagicMock
    ) -> None:
        """Different risk levels should use different TTLs."""
        # Safe - long TTL
        await cache.set("https://safe.example.com", {"risk": "safe"}, "safe")
        safe_call = mock_redis.setex.call_args
        safe_ttl = safe_call[0][1]

        # Blocked - short TTL
        await cache.set("https://blocked.example.com", {"risk": "blocked"}, "blocked")
        blocked_call = mock_redis.setex.call_args
        blocked_ttl = blocked_call[0][1]

        assert safe_ttl > blocked_ttl

    @pytest.mark.asyncio
    async def test_redis_error_handled(
        self, cache: URLSecurityCache, mock_redis: MagicMock
    ) -> None:
        """Redis errors should be handled gracefully."""
        mock_redis.get.side_effect = Exception("Redis connection error")

        result = await cache.get("https://example.com")

        assert result is None  # Should return None on error, not raise
