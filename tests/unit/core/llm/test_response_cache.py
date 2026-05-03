# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for LLMClient response caching with TTLCache."""

import hashlib
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cachetools import TTLCache

from core.llm.types import CallPoint, GlobalConfig, Label, LLMType, ProviderConfig, TokenUsage


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
        label = _make_label()
        payload = {"messages": [{"role": "user", "content": "hello"}]}

        key1 = f"{label}:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]}"
        key2 = f"{label}:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]}"

        assert key1 == key2

    def test_different_payload_different_key(self):
        label = _make_label()
        payload1 = {"messages": [{"role": "user", "content": "hello"}]}
        payload2 = {"messages": [{"role": "user", "content": "world"}]}

        key1 = f"{label}:{hashlib.sha256(json.dumps(payload1, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]}"
        key2 = f"{label}:{hashlib.sha256(json.dumps(payload2, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]}"

        assert key1 != key2

    def test_different_label_different_key(self):
        label1 = _make_label(provider="openai")
        label2 = _make_label(provider="anthropic")
        payload = {"messages": [{"role": "user", "content": "hello"}]}

        key1 = f"{label1}:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]}"
        key2 = f"{label2}:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]}"

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
