# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Redis 缓冲层：LLM 用量事件累加器。

将 LLM 调用用量事件实时累加到 Redis HASH 中,
按小时聚合,支持 TTL 自动过期。

Redis Key 设计:
    Key:   llm:usage:{YYYYMMDDHH}    TTL: 7200s (2h)
    Field: {label}::{call_point}::{metric}
    Metric: count | input_tok | output_tok | total_tok | latency_ms | success | failure
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from core.constants import RedisKeys
from core.event import LLMUsageEvent
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger(__name__)

# Redis key 前缀（不带尾冒号；单一定义在 core.constants.RedisKeys）
REDIS_KEY_PREFIX = RedisKeys.LLM_USAGE_BUFFER_PREFIX
# 默认 TTL: 2 小时
DEFAULT_TTL_SECONDS = 7200
# 支持的指标列表
METRICS = (
    "count",
    "input_tok",
    "output_tok",
    "total_tok",
    "cached_tok",
    "reasoning_tok",
    "cost_cents",
    "latency_ms",
    "latency_min",
    "latency_max",
    "success",
    "failure",
)


def _parse_timestamp(ts: datetime | str) -> datetime:
    """Parse timestamp to datetime object.

    Args:
        ts: Either a datetime object or ISO format string.

    Returns:
        datetime object.
    """
    if isinstance(ts, datetime):
        return ts
    # Parse ISO format string
    from datetime import datetime as dt

    return dt.fromisoformat(ts)


class LLMUsageBuffer:
    """LLM 用量事件缓存缓冲层。

    将 LLMUsageEvent 累加到缓存 HASH 中,按小时分桶。
    支持自动 TTL 管理和故障容错。

    Implements: EventBuffer

    Attributes:
        _cache: 缓存池实例
        _ttl: Key 过期时间(秒)
    """

    def __init__(
        self,
        cache: CachePool,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """初始化缓冲层。

        Args:
            cache: 缓存池实例
            ttl_seconds: Key 过期时间(秒),默认 7200s (2h)
        """
        self._cache = cache
        self._ttl = ttl_seconds

    def _make_bucket_key(self, dt: datetime) -> str:
        """生成小时级桶的 Redis key。

        Args:
            dt: 时间戳

        Returns:
            格式为 llm:usage:{YYYYMMDDHH} 的 key
        """
        return f"{REDIS_KEY_PREFIX}:{dt.strftime('%Y%m%d%H')}"

    async def accumulate(self, event: LLMUsageEvent) -> None:
        """累加 LLMUsageEvent 到缓存 HASH。

        使用 pipeline 批量执行 HINCRBY 操作以保证原子性。
        首次写入时设置 TTL。
        所有异常被捕获并记录日志,不阻塞主链路。

        Args:
            event: LLM 用量事件
        """
        try:
            # Parse timestamp (handle both datetime and string)
            dt = _parse_timestamp(event.timestamp)
            bucket_key = self._make_bucket_key(dt)

            # 构建 field 前缀
            field_prefix = f"{event.label}::{event.call_point}"

            # 仅在首次写入时设置 TTL,避免每次事件重置 TTL 导致永不过期。
            # 必须在写入前判断:写入后 hash 必然非空,写后检查恒为非空导致
            # TTL 从不设置。写前检查的并发双 expire 是无害的
            # (写入相同的 TTL 值)。
            try:
                is_new = not await self._cache.hgetall(bucket_key)
            except Exception:
                is_new = False

            # 使用 pipeline 原子执行所有 HINCRBY 操作
            async with self._cache.pipeline() as pipe:
                pipe.hincrby(bucket_key, f"{field_prefix}::count", 1)
                pipe.hincrby(bucket_key, f"{field_prefix}::input_tok", event.tokens.input_tokens)
                pipe.hincrby(bucket_key, f"{field_prefix}::output_tok", event.tokens.output_tokens)
                pipe.hincrby(bucket_key, f"{field_prefix}::total_tok", event.tokens.total_tokens)
                pipe.hincrby(bucket_key, f"{field_prefix}::latency_ms", int(event.latency_ms))
                pipe.hincrby(bucket_key, f"{field_prefix}::success", 1 if event.success else 0)
                pipe.hincrby(bucket_key, f"{field_prefix}::failure", 0 if event.success else 1)
                pipe.hincrby(bucket_key, f"{field_prefix}::cached_tok", event.tokens.cached_tokens)
                pipe.hincrby(
                    bucket_key, f"{field_prefix}::reasoning_tok", event.tokens.reasoning_tokens
                )
                pipe.hincrby(bucket_key, f"{field_prefix}::cost_cents", int(event.cost_usd * 100))
                await pipe.execute()

            # latency_min/latency_max: 需要读-写,无法 pipeline
            latency_val = int(event.latency_ms)
            min_key = f"{field_prefix}::latency_min"
            max_key = f"{field_prefix}::latency_max"
            try:
                current_min = await self._cache.hget(bucket_key, min_key)
            except Exception as exc:
                # Read failure means the current min is unknown; blindly
                # writing could overwrite a smaller stored value.
                log.warning(
                    "llm_usage_latency_min_read_failed",
                    bucket_key=bucket_key,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            else:
                if current_min is None or latency_val < int(current_min):
                    await self._cache.hset(bucket_key, min_key, str(latency_val))
            try:
                current_max = await self._cache.hget(bucket_key, max_key)
            except Exception as exc:
                log.warning(
                    "llm_usage_latency_max_read_failed",
                    bucket_key=bucket_key,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            else:
                if current_max is None or latency_val > int(current_max):
                    await self._cache.hset(bucket_key, max_key, str(latency_val))

            # TTL 由写入前的 is_new 检查决定(见上),此处直接应用。
            if is_new:
                await self._cache.expire(bucket_key, self._ttl)

            log.debug(
                "llm_usage_buffered",
                bucket_key=bucket_key,
                label=event.label,
                call_point=event.call_point,
                success=event.success,
            )

        except Exception as exc:
            # 捕获所有异常,记录日志,不阻塞主链路
            log.error(
                "llm_usage_buffer_failed",
                label=event.label,
                call_point=event.call_point,
                error=str(exc),
                error_type=type(exc).__name__,
            )
