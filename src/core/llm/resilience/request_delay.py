# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Request delay controller for LLM clients."""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict

from core.observability.logging import get_logger

log = get_logger(__name__)


class RequestDelay:
    """LLM请求延迟控制器.

    在每次LLM请求前添加随机时间间隔,避免请求过于集中.
    参考fetcher模块的HostRateLimiter实现,适配LLM调用场景.

    Args:
        enabled: 是否启用延迟
        delay_min: 最小延迟时间（秒）
        delay_max: 最大延迟时间（秒）
    """

    def __init__(
        self,
        enabled: bool = False,
        delay_min: float = 1.0,
        delay_max: float = 2.0,
    ) -> None:
        """初始化延迟控制器.

        Args:
            enabled: 是否启用延迟
            delay_min: 最小延迟时间（秒）
            delay_max: 最大延迟时间（秒）
        """
        self._enabled = enabled
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._last_request_time: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, provider: str) -> float:
        """在请求前调用此方法,等待必要的延迟时间.

        Args:
            provider: Provider名称

        Returns:
            实际等待时间（秒）,如果未启用或无需等待则返回0.0
        """
        # 如果未启用,直接返回
        if not self._enabled:
            return 0.0

        # 获取provider特定的锁
        async with self._locks[provider]:
            # 计算距离上次请求的时间
            now = time.monotonic()
            last_time = self._last_request_time[provider]
            elapsed = now - last_time

            # 生成随机延迟
            delay = random.uniform(self._delay_min, self._delay_max)

            # 如果距离上次请求时间小于延迟,则等待
            if elapsed < delay:
                wait_time = delay - elapsed
                log.debug(
                    "request_delay_wait",
                    provider=provider,
                    wait_seconds=round(wait_time, 2),
                    elapsed=round(elapsed, 2),
                    target_delay=round(delay, 2),
                )
                await asyncio.sleep(wait_time)
                self._last_request_time[provider] = time.monotonic()
                return wait_time

            # 无需等待,更新时间戳
            self._last_request_time[provider] = now
            return 0.0
