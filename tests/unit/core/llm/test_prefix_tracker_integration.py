# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for PrefixHashTracker integration into LLMClient (Task 13)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.types import (
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


def _make_mock_response() -> MagicMock:
    resp = MagicMock()
    resp.content = "test response content"
    resp.token_usage = TokenUsage(input_tokens=10, output_tokens=20)
    resp.label = _make_label()
    resp.latency_ms = 100.0
    resp.model = "gpt-4o"
    resp.cache_hit_tokens = 0
    resp.cache_miss_tokens = 0
    return resp


class TestPrefixHashTrackerIntegration:
    """Test PrefixHashTracker integration in LLMClient (Task 13)."""

    def test_client_has_prefix_tracker(self):
        """LLMClient 初始化时创建 PrefixHashTracker."""
        client = _make_client()
        assert hasattr(client, "_prefix_tracker")
        from core.llm.prefix_shape import PrefixHashTracker

        assert isinstance(client._prefix_tracker, PrefixHashTracker)

    @pytest.mark.asyncio
    async def test_first_call_no_diagnostic_log(self):
        """首次调用不记录 llm_cache_miss_diagnosed 日志（无变化）."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload = {
            "messages": [
                {"role": "system", "content": "You are a classifier"},
                {"role": "user", "content": "test"},
            ]
        }

        with patch("core.llm.client.log") as mock_log:
            with patch.object(
                client._pools["openai"],
                "execute",
                new=AsyncMock(return_value=_make_mock_response()),
            ):
                await client.call("chat.openai.gpt-4o", payload, call_point="classifier")

        # 首次调用不应有 llm_cache_miss_diagnosed 日志
        diagnosed_calls = [
            c for c in mock_log.info.call_args_list if c.args[0] == "llm_cache_miss_diagnosed"
        ]
        assert len(diagnosed_calls) == 0

    @pytest.mark.asyncio
    async def test_system_prompt_change_logs_diagnosed(self):
        """system prompt 变化时记录 llm_cache_miss_diagnosed 日志."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload1 = {
            "messages": [
                {"role": "system", "content": "You are a classifier"},
                {"role": "user", "content": "test"},
            ]
        }
        payload2 = {
            "messages": [
                {"role": "system", "content": "You are an entity extractor"},
                {"role": "user", "content": "test"},
            ]
        }

        with patch("core.llm.client.log") as mock_log:
            with patch.object(
                client._pools["openai"],
                "execute",
                new=AsyncMock(return_value=_make_mock_response()),
            ):
                # First call - no history
                await client.call("chat.openai.gpt-4o", payload1, call_point="classifier")
                # Second call - system prompt changed
                await client.call("chat.openai.gpt-4o", payload2, call_point="classifier")

        # Should have llm_cache_miss_diagnosed log with "system" in change_reasons
        diagnosed_calls = [
            c for c in mock_log.info.call_args_list if c.args[0] == "llm_cache_miss_diagnosed"
        ]
        assert len(diagnosed_calls) >= 1
        # Verify change_reasons contains "system"
        last_diagnosed = diagnosed_calls[-1]
        change_reasons = last_diagnosed.kwargs.get("change_reasons", [])
        assert "system" in change_reasons

    @pytest.mark.asyncio
    async def test_does_not_affect_cache_logic(self):
        """诊断模块不影响缓存逻辑（cache hit 仍正常工作）."""
        client = _make_client()
        cached_data = json.dumps(
            {
                "content": "cached response",
                "token_usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            }
        )
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=cached_data)
        mock_redis.setex = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload = {
            "messages": [
                {"role": "system", "content": "You are a classifier"},
                {"role": "user", "content": "test"},
            ]
        }

        with patch.object(client._pools["openai"], "execute", new=AsyncMock()) as mock_execute:
            result = await client.call("chat.openai.gpt-4o", payload, call_point="classifier")

        # Cache hit should work - no execute call
        assert result == "cached response"
        mock_execute.assert_not_called()
        assert client._cache_hits == 1
