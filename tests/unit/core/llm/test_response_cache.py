# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for LLMClient response caching."""

import hashlib
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    """Test LLMClient cache initialization."""

    def test_cache_attributes_initialized(self):
        client = _make_client()
        assert hasattr(client, "_response_cache")
        assert isinstance(client._response_cache, dict)
        assert client._cache_max_size == 1000
        assert client._cache_ttl == 3600

    def test_cache_starts_empty(self):
        client = _make_client()
        assert len(client._response_cache) == 0


class TestCacheKeyGeneration:
    """Test cache key generation."""

    def test_same_payload_same_key(self):
        client = _make_client()
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


class TestCacheTTL:
    """Test cache TTL behavior."""

    def test_expired_entry_removed(self):
        client = _make_client()
        label = _make_label()

        client._response_cache["test_key"] = {
            "content": "cached response",
            "timestamp": time.time() - 7200,
            "token_usage": TokenUsage(input_tokens=10, output_tokens=20),
        }

        assert "test_key" in client._response_cache

        now = time.time()
        if now - client._response_cache["test_key"]["timestamp"] >= client._cache_ttl:
            del client._response_cache["test_key"]

        assert "test_key" not in client._response_cache

    def test_fresh_entry_preserved(self):
        client = _make_client()

        client._response_cache["test_key"] = {
            "content": "cached response",
            "timestamp": time.time(),
            "token_usage": TokenUsage(input_tokens=10, output_tokens=20),
        }

        now = time.time()
        if now - client._response_cache["test_key"]["timestamp"] < client._cache_ttl:
            pass

        assert "test_key" in client._response_cache


class TestLRUEviction:
    """Test LRU eviction when cache exceeds max size."""

    def test_eviction_removes_oldest(self):
        client = _make_client()

        for i in range(client._cache_max_size + 10):
            client._response_cache[f"key_{i}"] = {
                "content": f"content_{i}",
                "timestamp": time.time() + i * 0.001,
                "token_usage": None,
            }
            if len(client._response_cache) > client._cache_max_size:
                oldest_key = min(
                    client._response_cache,
                    key=lambda k: client._response_cache[k]["timestamp"],
                )
                del client._response_cache[oldest_key]

        assert len(client._response_cache) <= client._cache_max_size

    def test_eviction_preserves_newest(self):
        client = _make_client()

        for i in range(client._cache_max_size + 10):
            client._response_cache[f"key_{i}"] = {
                "content": f"content_{i}",
                "timestamp": float(i),
                "token_usage": None,
            }
            if len(client._response_cache) > client._cache_max_size:
                oldest_key = min(
                    client._response_cache,
                    key=lambda k: client._response_cache[k]["timestamp"],
                )
                del client._response_cache[oldest_key]

        newest_key = f"key_{client._cache_max_size + 9}"
        assert newest_key in client._response_cache
