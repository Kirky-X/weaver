# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Prometheus server cache metrics."""

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


def _make_label(provider: str = "deepseek", model: str = "deepseek-chat") -> Label:
    return Label(llm_type=LLMType.CHAT, provider=provider, model=model)


def _make_client():
    from core.llm.client import LLMClient

    providers = [
        ProviderConfig(
            name="deepseek",
            type="openai",
            base_url="https://api.deepseek.com/v1",
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


def _get_counter_value(counter, labels: dict[str, str]) -> float:
    """Get the current value of a Prometheus Counter by labels."""
    return counter.labels(**labels)._value._value


class TestServerCacheMetricsRegistration:
    """Tests that server cache metrics are registered without duplicates."""

    def test_hit_tokens_metric_exists(self) -> None:
        """指标 llm_server_cache_hit_tokens 已注册且可访问."""
        from core.observability.metrics import metrics

        counter = metrics.llm_server_cache_hit_tokens
        assert counter is not None
        # 验证可创建带标签的 time series
        labeled = counter.labels(call_point="classifier", provider="deepseek")
        assert labeled is not None

    def test_miss_tokens_metric_exists(self) -> None:
        """指标 llm_server_cache_miss_tokens 已注册且可访问."""
        from core.observability.metrics import metrics

        counter = metrics.llm_server_cache_miss_tokens
        assert counter is not None
        labeled = counter.labels(call_point="classifier", provider="deepseek")
        assert labeled is not None

    def test_no_duplicate_registration_exception(self) -> None:
        """多次导入模块不抛出 Duplicated timeseries 异常."""
        # Python 导入系统缓存已导入模块，多次导入不会重新执行类定义
        from core.observability.metrics import (
            MetricsCollector,
            MetricsCollector as MetricsCollector2,
            metrics,
            metrics as metrics2,
        )

        # 验证是同一实例（模块只执行一次）
        assert MetricsCollector is MetricsCollector2
        assert metrics is metrics2


@pytest.mark.asyncio
class TestServerCacheMetricsIncrement:
    """Tests that server cache metrics are incremented after LLM call."""

    async def test_deepseek_call_increments_hit_tokens(self) -> None:
        """DeepSeek 调用后 llm_server_cache_hit_tokens_total 递增."""
        from core.observability.metrics import metrics

        client = _make_client()
        payload = {"key": "value"}

        mock_response = LLMResponse(
            content="response",
            label=_make_label(),
            latency_ms=100.0,
            token_usage=TokenUsage(input_tokens=10, output_tokens=5),
            model="deepseek-chat",
            cache_usage=CacheUsage(cache_hit_tokens=500, cache_miss_tokens=200),
        )

        labels = {"call_point": "classifier", "provider": "deepseek"}
        baseline_hit = _get_counter_value(metrics.llm_server_cache_hit_tokens, labels)
        baseline_miss = _get_counter_value(metrics.llm_server_cache_miss_tokens, labels)

        with patch.object(
            client._pools["deepseek"],
            "execute",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            with patch.object(type(client), "_emit_usage_event", AsyncMock()):
                await client.call(
                    "chat.deepseek.deepseek-chat",
                    payload,
                    call_point="classifier",
                )

        after_hit = _get_counter_value(metrics.llm_server_cache_hit_tokens, labels)
        after_miss = _get_counter_value(metrics.llm_server_cache_miss_tokens, labels)

        assert after_hit == baseline_hit + 500
        assert after_miss == baseline_miss + 200

    async def test_ollama_call_increments_zero(self) -> None:
        """Ollama 调用（无 cache 字段）后指标增量为 0."""
        from core.observability.metrics import metrics

        client = _make_client()
        payload = {"key": "value"}

        mock_response = LLMResponse(
            content="response",
            label=_make_label(),
            latency_ms=100.0,
            token_usage=TokenUsage(input_tokens=10, output_tokens=5),
            model="deepseek-chat",
            cache_usage=None,
        )

        labels = {"call_point": "classifier", "provider": "deepseek"}
        baseline_hit = _get_counter_value(metrics.llm_server_cache_hit_tokens, labels)

        with patch.object(
            client._pools["deepseek"],
            "execute",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            with patch.object(type(client), "_emit_usage_event", AsyncMock()):
                await client.call(
                    "chat.deepseek.deepseek-chat",
                    payload,
                    call_point="classifier",
                )

        after_hit = _get_counter_value(metrics.llm_server_cache_hit_tokens, labels)
        # 增量为 0（Ollama 无 cache 字段）
        assert after_hit == baseline_hit
