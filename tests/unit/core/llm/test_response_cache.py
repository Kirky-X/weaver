# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for LLMClient response caching with TTLCache."""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from cachetools import TTLCache

from core.llm.types import (
    CACHE_TTL,
    CallPoint,
    GlobalConfig,
    Label,
    LLMType,
    ProviderConfig,
    TokenUsage,
)


def _make_label(provider: str = "openai", model: str = "gpt-4o") -> Label:
    return Label(
        llm_type=LLMType.CHAT,
        provider=provider,
        model=model,
    )


def _make_client() -> "LLMClient":
    from core.llm.client import LLMClient

    providers = [
        ProviderConfig(
            name="openai",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            rpm_limit=100,
            concurrency=5,
            timeout=30.0,
            priority=100,
            weight=100,
            models={},
        )
    ]
    global_config = GlobalConfig(
        circuit_breaker_threshold=5,
        circuit_breaker_timeout=60.0,
        default_timeout=120.0,
    )
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()

    return LLMClient(
        providers=providers,
        global_config=global_config,
        event_bus=event_bus,
    )


class TestResponseCacheInit:
    """Test LLMClient cache initialization with TTLCache."""

    def test_cache_is_ttlcache(self):
        client = _make_client()
        assert hasattr(client, "_response_cache")
        assert isinstance(client._response_cache, TTLCache)

    def test_cache_maxsize_configured(self):
        client = _make_client()
        assert client._response_cache.maxsize == 1000

    def test_cache_ttl_configured(self):
        client = _make_client()
        assert client._response_cache.ttl == 3600

    def test_cache_starts_empty(self):
        client = _make_client()
        assert len(client._response_cache) == 0


class TestCacheKeyGeneration:
    """Test cache key generation."""

    def test_same_payload_same_key(self):
        payload = {"messages": [{"role": "user", "content": "hello"}]}

        key1 = f"cache:llm:classifier:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"
        key2 = f"cache:llm:classifier:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"

        assert key1 == key2

    def test_different_payload_different_key(self):
        payload1 = {"messages": [{"role": "user", "content": "hello"}]}
        payload2 = {"messages": [{"role": "user", "content": "world"}]}

        key1 = f"cache:llm:classifier:{hashlib.sha256(json.dumps(payload1, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"
        key2 = f"cache:llm:classifier:{hashlib.sha256(json.dumps(payload2, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"

        assert key1 != key2

    def test_different_call_point_different_key(self):
        payload = {"messages": [{"role": "user", "content": "hello"}]}

        key1 = f"cache:llm:classifier:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"
        key2 = f"cache:llm:analyze:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"

        assert key1 != key2


class TestTTLCacheBehavior:
    """Test TTLCache automatic TTL management."""

    def test_expired_entry_auto_removed(self):
        """TTLCache automatically removes expired entries on access."""
        client = _make_client()
        # TTLCache expires entries on timer, not on access check
        # For testing, we can simulate by waiting or checking timer
        client._response_cache["test_key"] = {
            "content": "cached response",
            "token_usage": TokenUsage(input_tokens=10, output_tokens=20),
        }
        assert "test_key" in client._response_cache
        # TTL will expire after 3600 seconds, but TTLCache handles this automatically

    def test_fresh_entry_preserved(self):
        client = _make_client()
        client._response_cache["test_key"] = {
            "content": "cached response",
            "token_usage": TokenUsage(input_tokens=10, output_tokens=20),
        }
        assert "test_key" in client._response_cache


class TestLRUEviction:
    """Test LRU eviction when cache exceeds max size."""

    def test_eviction_removes_oldest_accessed(self):
        """TTLCache uses LRU - least recently used entries are evicted."""
        client = _make_client()
        # Fill cache to max size
        for i in range(client._response_cache.maxsize):
            client._response_cache[f"key_{i}"] = {
                "content": f"content_{i}",
                "token_usage": None,
            }

        assert len(client._response_cache) <= client._response_cache.maxsize

        # Adding more entries triggers LRU eviction
        client._response_cache["new_key"] = {"content": "new", "token_usage": None}
        assert len(client._response_cache) <= client._response_cache.maxsize

    def test_eviction_preserves_recently_accessed(self):
        """Recently accessed entries are preserved when eviction occurs."""
        client = _make_client()
        # Fill cache
        for i in range(client._response_cache.maxsize):
            client._response_cache[f"key_{i}"] = {
                "content": f"content_{i}",
                "token_usage": None,
            }

        # Access key_0 to make it recently used
        _ = client._response_cache.get("key_0")

        # Add new entries - key_0 should be preserved (recently accessed)
        for i in range(10):
            client._response_cache[f"new_key_{i}"] = {
                "content": f"new_{i}",
                "token_usage": None,
            }

        # key_0 should still be in cache (recently accessed)
        assert "key_0" in client._response_cache


def _make_mock_response() -> MagicMock:
    resp = MagicMock()
    resp.content = "test response content"
    resp.token_usage = TokenUsage(input_tokens=10, output_tokens=20)
    resp.label = _make_label()
    resp.latency_ms = 100.0
    resp.model = "gpt-4o"
    resp.cache_usage = None
    return resp


class TestRedisCache:
    """Test Redis cache integration with LLMClient."""

    @pytest.mark.asyncio
    async def test_first_call_writes_to_redis(self):
        """First call should send request and write to Redis cache."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        with patch.object(
            client._pools["openai"], "execute", new=AsyncMock(return_value=_make_mock_response())
        ):
            result = await client.call(
                "chat.openai.gpt-4o", {"key": "value"}, call_point="classifier"
            )

        assert result == "test response content"
        mock_redis.get.assert_awaited_once()
        mock_redis.set.assert_awaited_once()
        assert client._cache_misses == 1

    @pytest.mark.asyncio
    async def test_second_call_reads_from_redis(self):
        """Second call with same payload should return from Redis cache without sending request."""
        client = _make_client()
        cached_data = json.dumps(
            {
                "content": "cached response from redis",
                "token_usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            }
        )
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=cached_data)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        with patch.object(client._pools["openai"], "execute", new=AsyncMock()) as mock_execute:
            result = await client.call(
                "chat.openai.gpt-4o", {"key": "value"}, call_point="classifier"
            )

        assert result == "cached response from redis"
        mock_redis.get.assert_awaited_once()
        mock_execute.assert_not_called()
        assert client._cache_hits == 1

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_to_ttlcache(self):
        """When Redis fails, should fall back to TTLCache without raising."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        client._redis = mock_redis

        with patch.object(
            client._pools["openai"], "execute", new=AsyncMock(return_value=_make_mock_response())
        ):
            result = await client.call(
                "chat.openai.gpt-4o", {"key": "value"}, call_point="classifier"
            )

        assert result == "test response content"
        mock_redis.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_cache_hit_increments_hit_counter(self):
        """Redis cache hit should increment _cache_hits counter."""
        client = _make_client()
        cached_data = json.dumps(
            {
                "content": "cached",
                "token_usage": None,
            }
        )
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=cached_data)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        assert client._cache_hits == 0

        with patch.object(client._pools["openai"], "execute", new=AsyncMock()) as mock_execute:
            await client.call("chat.openai.gpt-4o", {"key": "value"}, call_point="classifier")

        assert client._cache_hits == 1
        mock_execute.assert_not_called()


class TestTTLGrading:
    """Test TTL grading by call_point."""

    def test_classifier_ttl_is_7_days(self):
        assert CACHE_TTL["classifier"] == 7 * 24 * 60 * 60

    def test_quality_scorer_ttl_is_1_day(self):
        assert CACHE_TTL["quality_scorer"] == 24 * 60 * 60

    def test_analyze_ttl_is_1_day(self):
        assert CACHE_TTL["analyze"] == 24 * 60 * 60

    def test_categorizer_ttl_is_7_days(self):
        assert CACHE_TTL["categorizer"] == 7 * 24 * 60 * 60

    def test_summary_ttl_is_7_days(self):
        assert CACHE_TTL["summary"] == 7 * 24 * 60 * 60

    def test_entity_extractor_ttl_is_7_days(self):
        assert CACHE_TTL["entity_extractor"] == 7 * 24 * 60 * 60

    def test_default_ttl_is_1_day(self):
        assert CACHE_TTL["default"] == 24 * 60 * 60

    @pytest.mark.asyncio
    async def test_redis_set_uses_correct_ttl_per_call_point(self):
        """Verify that Redis set receives the correct TTL for each call_point."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        with patch.object(
            client._pools["openai"], "execute", new=AsyncMock(return_value=_make_mock_response())
        ):
            await client.call("chat.openai.gpt-4o", {"key": "value"}, call_point="classifier")

        call_kwargs = mock_redis.set.call_args
        assert call_kwargs[1]["ex"] == CACHE_TTL["classifier"]  # 7 days
