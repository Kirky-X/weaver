# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for LLM cache key v2 grayscale integration (Task 11)."""

import hashlib
import json
import os
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
    resp.cache_usage = None
    return resp


class TestCacheKeyV2Grayscale:
    """Test LLM_CACHE_KEY_V2_ENABLED grayscale switch (Task 11)."""

    @pytest.mark.asyncio
    async def test_v2_disabled_uses_old_key_format(self):
        """LLM_CACHE_KEY_V2_ENABLED=false 时使用旧版 cache key 格式."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload = {"content": "test content"}

        with patch.dict(os.environ, {"LLM_CACHE_KEY_V2_ENABLED": "false"}):
            with patch.object(
                client._pools["openai"],
                "execute",
                new=AsyncMock(return_value=_make_mock_response()),
            ):
                await client.call("chat.openai.gpt-4o", payload, call_point="classifier")

        # 验证 Redis.get 收到的是旧版 key（无 v2 前缀）
        cache_key_used = mock_redis.get.call_args[0][0]
        assert cache_key_used.startswith("cache:llm:classifier:")
        assert ":v2:" not in cache_key_used
        # 旧版使用完整 sha256（64 字符）
        hash_part = cache_key_used.split(":")[-1]
        assert len(hash_part) == 64

    @pytest.mark.asyncio
    async def test_v2_enabled_uses_new_key_format(self):
        """LLM_CACHE_KEY_V2_ENABLED=true 时使用 v2 cache key 格式."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload = {"content": "test content"}

        with patch.dict(os.environ, {"LLM_CACHE_KEY_V2_ENABLED": "true"}):
            with patch.object(
                client._pools["openai"],
                "execute",
                new=AsyncMock(return_value=_make_mock_response()),
            ):
                await client.call("chat.openai.gpt-4o", payload, call_point="classifier")

        # 验证 Redis.get 收到的是 v2 key
        cache_key_used = mock_redis.get.call_args[0][0]
        assert cache_key_used.startswith("cache:llm:v2:classifier:")
        # v2 使用 16 字符 hash
        hash_part = cache_key_used.split(":")[-1]
        assert len(hash_part) == 16

    @pytest.mark.asyncio
    async def test_v2_not_set_uses_old_key_format(self):
        """LLM_CACHE_KEY_V2_ENABLED 未设置时默认使用旧版 cache key."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload = {"content": "test content"}

        # 确保环境变量未设置
        env_without_v2 = {k: v for k, v in os.environ.items() if k != "LLM_CACHE_KEY_V2_ENABLED"}
        with patch.dict(os.environ, env_without_v2, clear=True):
            with patch.object(
                client._pools["openai"],
                "execute",
                new=AsyncMock(return_value=_make_mock_response()),
            ):
                await client.call("chat.openai.gpt-4o", payload, call_point="classifier")

        cache_key_used = mock_redis.get.call_args[0][0]
        assert cache_key_used.startswith("cache:llm:classifier:")
        assert ":v2:" not in cache_key_used

    @pytest.mark.asyncio
    async def test_v2_enabled_excludes_non_semantic_fields(self):
        """v2 启用时排除非语义字段（article_id 变化不影响 key）."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload1 = {"content": "test", "article_id": "art-001"}
        payload2 = {"content": "test", "article_id": "art-002"}

        with patch.dict(os.environ, {"LLM_CACHE_KEY_V2_ENABLED": "true"}):
            with patch.object(
                client._pools["openai"],
                "execute",
                new=AsyncMock(return_value=_make_mock_response()),
            ):
                await client.call("chat.openai.gpt-4o", payload1, call_point="classifier")
                key1 = mock_redis.get.call_args[0][0]

                await client.call("chat.openai.gpt-4o", payload2, call_point="classifier")
                key2 = mock_redis.get.call_args[0][0]

        assert key1 == key2, "v2 key should be same when only article_id differs"

    @pytest.mark.asyncio
    async def test_v2_disabled_includes_all_fields(self):
        """v2 禁用时 article_id 变化会影响 key（旧版行为）."""
        client = _make_client()
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        client._redis = mock_redis

        payload1 = {"content": "test", "article_id": "art-001"}
        payload2 = {"content": "test", "article_id": "art-002"}

        with patch.dict(os.environ, {"LLM_CACHE_KEY_V2_ENABLED": "false"}):
            with patch.object(
                client._pools["openai"],
                "execute",
                new=AsyncMock(return_value=_make_mock_response()),
            ):
                await client.call("chat.openai.gpt-4o", payload1, call_point="classifier")
                key1 = mock_redis.get.call_args[0][0]

                await client.call("chat.openai.gpt-4o", payload2, call_point="classifier")
                key2 = mock_redis.get.call_args[0][0]

        assert key1 != key2, "old key should differ when article_id differs"
