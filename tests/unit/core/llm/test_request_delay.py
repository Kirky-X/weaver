# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for RequestDelay class."""

from __future__ import annotations

import pytest

from core.llm.resilience.request_delay import RequestDelay


class TestRequestDelay:
    """测试RequestDelay类."""

    @pytest.mark.asyncio
    async def test_disabled_delay_returns_zero(self) -> None:
        """测试禁用状态下不延迟."""
        delay = RequestDelay(enabled=False)
        wait_time = await delay.acquire("test_provider")
        assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_first_request_no_wait(self) -> None:
        """测试第一次请求无需等待."""
        delay = RequestDelay(enabled=True, delay_min=1.0, delay_max=2.0)
        wait_time = await delay.acquire("test_provider")
        assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_second_request_waits(self) -> None:
        """测试第二次请求会等待."""
        delay = RequestDelay(enabled=True, delay_min=1.0, delay_max=2.0)

        # 第一次请求
        await delay.acquire("test_provider")

        # 立即第二次请求（应该等待）
        import asyncio

        loop = asyncio.get_event_loop()
        start = loop.time()
        wait_time = await delay.acquire("test_provider")
        elapsed = loop.time() - start

        assert wait_time > 0.0
        assert elapsed >= 1.0  # 至少等待1秒

    @pytest.mark.asyncio
    async def test_delay_within_range(self) -> None:
        """测试延迟在指定范围内."""
        delay = RequestDelay(enabled=True, delay_min=1.0, delay_max=2.0)

        wait_times = []
        for _ in range(5):
            await delay.acquire("test_provider")
            import asyncio

            loop = asyncio.get_event_loop()
            start = loop.time()
            wait_time = await delay.acquire("test_provider")
            elapsed = loop.time() - start
            wait_times.append(wait_time)
            # 确保实际等待时间也在合理范围内
            assert 0.9 <= elapsed <= 2.2  # 允许少量误差

        # 验证所有延迟都在范围内
        for wt in wait_times:
            assert 0.9 <= wt <= 2.1  # 允许少量误差

    @pytest.mark.asyncio
    async def test_concurrent_different_providers(self) -> None:
        """测试不同provider并发执行."""
        delay = RequestDelay(enabled=True, delay_min=0.05, delay_max=0.05)

        import asyncio

        results = await asyncio.gather(
            delay.acquire("provider1"),
            delay.acquire("provider2"),
        )

        # 不同provider之间不应该等待
        assert all(wt == 0.0 for wt in results)

    @pytest.mark.asyncio
    async def test_concurrent_same_provider_serialized(self) -> None:
        """测试同一provider并发请求串行化."""
        delay = RequestDelay(enabled=True, delay_min=0.05, delay_max=0.05)

        import asyncio

        start = asyncio.get_event_loop().time()
        await asyncio.gather(
            delay.acquire("provider1"),
            delay.acquire("provider1"),
        )
        elapsed = asyncio.get_event_loop().time() - start

        # 两个请求至少需要 0.05 秒（被串行化）
        assert elapsed >= 0.04

    @pytest.mark.asyncio
    async def test_elapsed_time_exceeds_delay(self) -> None:
        """测试已过时间超过延迟时不等待."""
        delay = RequestDelay(enabled=True, delay_min=0.1, delay_max=0.2)

        # 第一次请求
        await delay.acquire("test_provider")

        # 等待超过延迟时间
        import asyncio

        await asyncio.sleep(0.3)

        # 第二次请求应该不等待
        wait_time = await delay.acquire("test_provider")
        assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_multiple_providers_independent(self) -> None:
        """测试多个provider的延迟控制相互独立."""
        delay = RequestDelay(enabled=True, delay_min=0.1, delay_max=0.1)

        # 对provider1发送两次请求
        await delay.acquire("provider1")
        wait_time_1 = await delay.acquire("provider1")
        assert wait_time_1 > 0.0

        # 对provider2发送请求，应该不受provider1影响
        wait_time_2 = await delay.acquire("provider2")
        assert wait_time_2 == 0.0
