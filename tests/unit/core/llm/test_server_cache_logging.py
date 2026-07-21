# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for LLMClient server cache info logging on cache miss."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.types import (
    CacheUsage,
    GlobalConfig,
    Label,
    LLMResponse,
    LLMType,
    ProviderConfig,
    TokenUsage,
)


def _make_label(provider: str = "agnes", model: str = "agnes-2.0-flash") -> Label:
    return Label(llm_type=LLMType.CHAT, provider=provider, model=model)


def _make_client():
    from core.llm.client import LLMClient

    providers = [
        ProviderConfig(
            name="agnes",
            type="openai",
            base_url="https://apihub.agnes-ai.com/v1",
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


def _make_response(
    content: str = "response",
    cache_hit: int = 0,
    cache_miss: int = 0,
    provider: str = "agnes",
    model: str = "agnes-2.0-flash",
) -> LLMResponse:
    cache_usage = None
    if cache_hit > 0 or cache_miss > 0:
        cache_usage = CacheUsage(cache_hit_tokens=cache_hit, cache_miss_tokens=cache_miss)
    return LLMResponse(
        content=content,
        label=_make_label(provider=provider, model=model),
        latency_ms=100.0,
        token_usage=TokenUsage(input_tokens=10, output_tokens=5),
        model=model,
        cache_usage=cache_usage,
    )


@pytest.mark.asyncio
class TestServerCacheInfoLogging:
    """Tests that LLMClient.call() logs server cache info on cache miss."""

    async def test_agnes_cache_miss_logs_server_cache_info(self) -> None:
        """Agnes 调用后 cache miss 日志包含 server_cache_hit 字段."""
        client = _make_client()
        payload = {"key": "value"}

        mock_response = _make_response(
            content="agnes response",
            cache_hit=500,
            cache_miss=200,
        )

        with patch.object(
            client._pools["agnes"],
            "execute",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            with patch.object(type(client), "_emit_usage_event", AsyncMock()):
                with patch("core.llm.client.log") as mock_log:
                    await client.call(
                        "chat.agnes.agnes-2.0-flash",
                        payload,
                        call_point="classifier",
                    )

        # 查找 llm_cache_miss_with_server_info 日志调用
        debug_calls = mock_log.debug.call_args_list
        info_calls = mock_log.info.call_args_list
        all_calls = debug_calls + info_calls

        server_info_calls = [
            c for c in all_calls if c.args and c.args[0] == "llm_cache_miss_with_server_info"
        ]
        assert len(server_info_calls) == 1, (
            f"Expected 1 llm_cache_miss_with_server_info log, found {len(server_info_calls)}"
        )

        call_kwargs = server_info_calls[0].kwargs
        assert call_kwargs["server_cache_hit"] == 500
        assert call_kwargs["server_cache_miss"] == 200
        assert call_kwargs["server_hit_rate"] == pytest.approx(500 / 700)

    async def test_ollama_no_cache_fields_logs_zero(self) -> None:
        """Ollama 响应（无 cache 字段）日志 server_cache_hit=0."""
        client = _make_client()
        payload = {"key": "value"}

        mock_response = _make_response(
            content="ollama response",
            cache_hit=0,
            cache_miss=0,
            provider="agnes",  # 使用已配置的 provider
        )

        with patch.object(
            client._pools["agnes"],
            "execute",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            with patch.object(type(client), "_emit_usage_event", AsyncMock()):
                with patch("core.llm.client.log") as mock_log:
                    await client.call(
                        "chat.agnes.agnes-2.0-flash",
                        payload,
                        call_point="classifier",
                    )

        debug_calls = mock_log.debug.call_args_list
        info_calls = mock_log.info.call_args_list
        all_calls = debug_calls + info_calls

        server_info_calls = [
            c for c in all_calls if c.args and c.args[0] == "llm_cache_miss_with_server_info"
        ]
        assert len(server_info_calls) == 1

        call_kwargs = server_info_calls[0].kwargs
        assert call_kwargs["server_cache_hit"] == 0
        assert call_kwargs["server_cache_miss"] == 0
        assert call_kwargs["server_hit_rate"] == 0.0

    async def test_cache_hit_does_not_log_server_info(self) -> None:
        """客户端缓存命中时不记录 llm_cache_miss_with_server_info."""
        client = _make_client()
        payload = {"key": "value"}

        # 预填充缓存（使用生产代码的缓存键生成方法，确保灰度开关兼容）
        cache_key = client._build_cache_key("classifier", payload)
        client._response_cache[cache_key] = {
            "content": "cached",
            "token_usage": TokenUsage(),
        }

        with patch.object(type(client), "_emit_usage_event", AsyncMock()):
            with patch("core.llm.client.log") as mock_log:
                await client.call(
                    "chat.agnes.agnes-2.0-flash",
                    payload,
                    call_point="classifier",
                )

        debug_calls = mock_log.debug.call_args_list
        info_calls = mock_log.info.call_args_list
        all_calls = debug_calls + info_calls

        server_info_calls = [
            c for c in all_calls if c.args and c.args[0] == "llm_cache_miss_with_server_info"
        ]
        assert len(server_info_calls) == 0
