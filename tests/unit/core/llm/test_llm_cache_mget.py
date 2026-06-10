# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for LLMClient batch_call using Redis MGET/MSET."""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _make_client(redis_mock: AsyncMock | None = None) -> "LLMClient":
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
        cache_client=redis_mock,
    )


def _cache_key(call_point: str, payload: dict) -> str:
    """Generate cache key matching LLMClient's logic."""
    return f"cache:llm:{call_point}:{hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}"


class TestBatchCallUsesMget:
    """batch_call uses MGET for cache lookup."""

    @pytest.mark.asyncio
    async def test_batch_call_uses_mget(self):
        """batch_call uses MGET to check cache for all payloads at once."""
        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None, None])

        client = _make_client(redis_mock=redis)

        payloads = [
            {"body": "hello"},
            {"body": "world"},
        ]

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "response"
            results = await client.batch_call(
                label="chat.openai.gpt-4o",
                payloads=payloads,
                call_point=CallPoint.CLASSIFIER,
            )

        # MGET should have been called once with both cache keys
        assert redis.mget.call_count == 1
        called_keys = redis.mget.call_args[0][0]
        assert len(called_keys) == 2

    @pytest.mark.asyncio
    async def test_mget_returns_cached_and_uncached(self):
        """Partial hit/miss: cached items returned from cache, uncached trigger LLM."""
        redis = AsyncMock()

        payload1 = {"body": "cached"}
        payload2 = {"body": "uncached"}
        key1 = _cache_key("classifier", payload1)
        key2 = _cache_key("classifier", payload2)

        # First payload is cached, second is not
        cached_data = json.dumps({"content": "cached_response", "token_usage": {}})
        redis.mget = AsyncMock(
            return_value=[
                cached_data.encode() if isinstance(cached_data, str) else cached_data,
                None,
            ]
        )

        client = _make_client(redis_mock=redis)

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "uncached_response"
            results = await client.batch_call(
                label="chat.openai.gpt-4o",
                payloads=[payload1, payload2],
                call_point=CallPoint.CLASSIFIER,
            )

        # First result from cache, second from LLM call
        assert results[0] == "cached_response"
        assert results[1] == "uncached_response"
        # Only uncached item should trigger LLM call
        assert mock_call.call_count == 1

    @pytest.mark.asyncio
    async def test_mget_cache_miss_triggers_llm_call(self):
        """Uncached items trigger LLM call."""
        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None, None])

        client = _make_client(redis_mock=redis)

        payloads = [
            {"body": "first"},
            {"body": "second"},
        ]

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = ["response1", "response2"]
            results = await client.batch_call(
                label="chat.openai.gpt-4o",
                payloads=payloads,
                call_point=CallPoint.CLASSIFIER,
            )

        # Both items missed cache, both should trigger LLM call
        assert mock_call.call_count == 2
        assert results == ["response1", "response2"]

    @pytest.mark.asyncio
    async def test_mget_stores_results_in_batch(self):
        """Results stored via MSET after LLM calls."""
        redis = AsyncMock()
        redis.mget = AsyncMock(return_value=[None, None])
        redis.mset = AsyncMock()

        client = _make_client(redis_mock=redis)

        payloads = [
            {"body": "first"},
            {"body": "second"},
        ]

        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = ["response1", "response2"]
            results = await client.batch_call(
                label="chat.openai.gpt-4o",
                payloads=payloads,
                call_point=CallPoint.CLASSIFIER,
            )

        # MSET should have been called to store results
        assert redis.mset.call_count == 1
        stored = redis.mset.call_args[0][0]
        assert len(stored) == 2
