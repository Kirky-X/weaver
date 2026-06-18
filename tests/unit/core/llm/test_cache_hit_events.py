# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for TTLCache hit event suppression.

Test 5.2: When a TTLCache hit occurs in LLMClient.chat(), _emit_usage_event is NOT called.
"""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.types import (
    CallPoint,
    GlobalConfig,
    Label,
    LLMType,
    ProviderConfig,
    TokenUsage,
)


def _make_label(provider: str = "openai", model: str = "gpt-4o") -> Label:
    return Label(llm_type=LLMType.CHAT, provider=provider, model=model)


def _make_client():
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


def _cache_key(payload: dict, call_point: str = "classifier") -> str:
    """Compute cache key the same way LLMClient.call does."""
    return (
        f"cache:llm:{call_point}:"
        f"{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"
    )


@pytest.mark.asyncio
class TestTTLCacheHitNoEvent:
    """Verify that TTLCache hits do NOT emit usage events."""

    async def test_ttlcache_hit_skips_emit_usage_event(self):
        """When TTLCache has the key, _emit_usage_event must NOT be called."""
        client = _make_client()
        payload = {"key": "value"}
        key = _cache_key(payload)

        client._response_cache[key] = {
            "content": "cached response",
            "token_usage": TokenUsage(input_tokens=10, output_tokens=20),
        }

        mock_emit = AsyncMock()
        with patch.object(type(client), "_emit_usage_event", mock_emit):
            result = await client.call(
                "chat.openai.gpt-4o",
                payload,
                call_point="classifier",
            )

        assert result == "cached response"
        mock_emit.assert_not_awaited()

    async def test_ttlcache_hit_no_pool_execute(self):
        """TTLCache hit should bypass pool.execute entirely."""
        client = _make_client()
        payload = {"key": "value"}
        key = _cache_key(payload)

        client._response_cache[key] = {
            "content": "from cache",
            "token_usage": TokenUsage(input_tokens=5, output_tokens=10),
        }

        pool_execute = AsyncMock()
        with patch.object(client._pools["openai"], "execute", pool_execute):
            result = await client.call(
                "chat.openai.gpt-4o",
                payload,
                call_point="classifier",
            )

        assert result == "from cache"
        pool_execute.assert_not_called()

    async def test_ttlcache_hit_increments_cache_hits(self):
        """TTLCache hit should increment _cache_hits counter."""
        client = _make_client()
        payload = {"key": "value"}
        key = _cache_key(payload)

        client._response_cache[key] = {
            "content": "cached",
            "token_usage": TokenUsage(),
        }

        initial_hits = client._cache_hits

        mock_emit = AsyncMock()
        with patch.object(type(client), "_emit_usage_event", mock_emit):
            await client.call(
                "chat.openai.gpt-4o",
                payload,
                call_point="classifier",
            )

        assert client._cache_hits == initial_hits + 1

    async def test_ttlcache_miss_then_hit_emits_event_only_once(self):
        """First call misses cache and emits event; second call hits cache and emits nothing."""
        client = _make_client()
        payload = {"key": "value"}

        mock_response = MagicMock()
        mock_response.content = "llm response"
        mock_response.token_usage = TokenUsage(input_tokens=100, output_tokens=50)
        mock_response.label = _make_label()
        mock_response.latency_ms = 200.0
        mock_response.model = "gpt-4o"

        mock_emit = AsyncMock()
        with patch.object(
            client._pools["openai"], "execute", new_callable=AsyncMock, return_value=mock_response
        ):
            with patch.object(type(client), "_emit_usage_event", mock_emit):
                # First call: cache miss -> should emit
                result1 = await client.call(
                    "chat.openai.gpt-4o",
                    payload,
                    call_point="classifier",
                )
                assert result1 == "llm response"
                assert mock_emit.await_count == 1

                # Second call: cache hit -> should NOT emit
                mock_emit.reset_mock()
                result2 = await client.call(
                    "chat.openai.gpt-4o",
                    payload,
                    call_point="classifier",
                )
                assert result2 == "llm response"
                mock_emit.assert_not_awaited()

    async def test_redis_hit_also_skips_emit_event(self):
        """Redis cache hit should also skip _emit_usage_event."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(
            return_value=json.dumps(
                {
                    "content": "redis cached",
                    "token_usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                }
            )
        )
        client._redis = mock_redis

        mock_emit = AsyncMock()
        with patch.object(type(client), "_emit_usage_event", mock_emit):
            result = await client.call(
                "chat.openai.gpt-4o",
                {"key": "value"},
                call_point="classifier",
            )

        assert result == "redis cached"
        mock_emit.assert_not_awaited()

    async def test_cache_miss_emits_event(self):
        """Cache miss should call _emit_usage_event."""
        client = _make_client()

        mock_response = MagicMock()
        mock_response.content = "new response"
        mock_response.token_usage = TokenUsage(input_tokens=50, output_tokens=25)
        mock_response.label = _make_label()
        mock_response.latency_ms = 150.0
        mock_response.model = "gpt-4o"

        mock_emit = AsyncMock()
        with patch.object(
            client._pools["openai"], "execute", new_callable=AsyncMock, return_value=mock_response
        ):
            with patch.object(type(client), "_emit_usage_event", mock_emit):
                result = await client.call(
                    "chat.openai.gpt-4o",
                    {"key": "value"},
                    call_point="classifier",
                )

        assert result == "new response"
        mock_emit.assert_awaited_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs["success"] is True
        assert call_kwargs["token_usage"] == TokenUsage(input_tokens=50, output_tokens=25)
