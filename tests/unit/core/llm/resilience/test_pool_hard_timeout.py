# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for ProviderPool wall-clock hard timeout.

上游 LLM 连接挂死（既不报错也不返回数据）时，litellm 的 per-request
timeout 可能不覆盖该路径（慢速滴流/半开连接），调用无限等待。
_do_call 用 asyncio.wait_for 从外层硬切：超时按 CancelledError 传入
熔断器计为失败，worker 层拿到 TimeoutError 后继续后续批次。
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event import EventBus
from core.llm.resilience.pool import ProviderPool
from core.llm.types import Capability, Label, LLMType, ModelConfig, ProviderConfig


@pytest.fixture
def mock_event_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def provider_config() -> ProviderConfig:
    model_cfg = ModelConfig(
        model_id="test-model",
        capabilities=frozenset([Capability.CHAT]),
    )
    return ProviderConfig(
        name="test-provider",
        type="openai",
        api_key="test-key",
        base_url="https://api.test.com",
        models={"test-model": model_cfg},
        rpm_limit=100,
        concurrency=5,
        timeout=30.0,
    )


@pytest.fixture
def chat_label() -> Label:
    return Label(model="test-model", llm_type=LLMType.CHAT, provider="test-provider")


def _make_pool(provider_config: ProviderConfig, mock_event_bus: MagicMock) -> ProviderPool:
    pool = ProviderPool(config=provider_config, event_bus=mock_event_bus)
    # 直接 mock 掉 litellm caller（网络层），聚焦 wall-clock 超时行为
    pool._caller = AsyncMock()
    return pool


class TestWallClockHardTimeout:
    @pytest.mark.asyncio
    async def test_hung_call_cut_by_wall_clock_timeout(
        self, provider_config: ProviderConfig, mock_event_bus: MagicMock, chat_label: Label
    ) -> None:
        """caller 永久挂死时，wait_for 必须在 timeout+margin 内硬切。"""
        pool = _make_pool(provider_config, mock_event_bus)

        async def _hang(*args, **kwargs):
            await asyncio.Event().wait()  # 永不完成

        pool._caller.call = AsyncMock(side_effect=_hang)

        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.0,
            "max_tokens": 20,  # 生成预算 20/20=1s，测试快速切断
        }
        from core.llm.resilience.pool import AllProvidersFailedError

        start = time.monotonic()
        with patch("core.llm.resilience.pool._WALL_CLOCK_TIMEOUT_MARGIN_SECONDS", 0.1):
            # execute 的 fallback 链耗尽后包装为 AllProvidersFailedError，
            # 内因是 wait_for 硬切的 TimeoutError
            with pytest.raises(AllProvidersFailedError) as exc_info:
                await pool.execute(
                    [chat_label],
                    payload,
                    call_point="test",
                    timeout=0.3,
                )
        elapsed = time.monotonic() - start

        assert isinstance(exc_info.value.__cause__, asyncio.TimeoutError)

        # 0.3 + 0.1 margin = 0.4s 上限（留执行余量），远小于 litellm 挂死
        # 有界即可（含 execute 内部重试退避，17s 级别），对比修复前的无限挂死
        assert elapsed < 120
        # 挂死被切断必须计入熔断器失败（而非静默丢失）
        assert pool._circuit_breaker._failure_counter >= 1

    @pytest.mark.asyncio
    async def test_normal_call_unaffected_by_wait_for(
        self, provider_config: ProviderConfig, mock_event_bus: MagicMock, chat_label: Label
    ) -> None:
        """正常快速调用不受 wait_for 包裹影响。"""
        pool = _make_pool(provider_config, mock_event_bus)

        mock_response = MagicMock()
        mock_response.latency_ms = 12.0

        async def _fast(*args, **kwargs):
            return mock_response

        pool._caller.call = AsyncMock(side_effect=_fast)

        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.0,
        }
        result = await pool.execute(
            [chat_label],
            payload,
            call_point="test",
            timeout=30.0,
        )
        assert result is mock_response
