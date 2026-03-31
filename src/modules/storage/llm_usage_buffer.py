# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Redis 缓冲层：LLM 用量事件累加器。

将 LLM 调用用量事件实时累加到 Redis HASH 中,
按小时聚合,支持 TTL 自动过期。

Redis Key 设计:
    Key:   llm:usage:{YYYYMMDDHH}    TTL: 7200s (2h)
    Field: {label}::{call_point}::{metric}
    Metric: count | input_tok | output_tok | total_tok | latency_ms | success | failure
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.event.bus import LLMUsageEvent
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.cache.redis import RedisClient

log = get_logger("llm_usage_buffer")

# Redis key 前缀
REDIS_KEY_PREFIX = "llm:usage"
# 默认 TTL: 2 小时
DEFAULT_TTL_SECONDS = 7200
# 支持的指标列表
METRICS = ("count", "input_tok", "output_tok", "total_tok", "latency_ms", "success", "failure")


class LLMUsageBuffer:
    """LLM 用量事件 Redis 缓冲层。

    将 LLMUsageEvent 累加到 Redis HASH 中,按小时分桶。
    支持自动 TTL 管理和故障容错。

    Attributes:
        _redis: Redis 客户端实例
        _ttl: Key 过期时间(秒)
    """

    def __init__(
        self,
        redis_client: RedisClient,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """初始化缓冲层。

        Args:
            redis_client: Redis 客户端实例
            ttl_seconds: Key 过期时间(秒),默认 7200s (2h)
        """
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _make_bucket_key(self, dt: datetime) -> str:
        """生成小时级桶的 Redis key。

        Args:
            dt: 时间戳

        Returns:
            格式为 llm:usage:{YYYYMMDDHH} 的 key
        """
        return f"{REDIS_KEY_PREFIX}:{dt.strftime('%Y%m%d%H')}"

    def _make_field_name(self, label: str, call_point: str, metric: str) -> str:
        """生成 HASH field 名称。

        Args:
            label: 调用标签
            call_point: 调用点标识
            metric: 指标名称

        Returns:
            格式为 {label}::{call_point}::{metric} 的 field
        """
        return f"{label}::{call_point}::{metric}"

    async def accumulate(self, event: LLMUsageEvent) -> None:
        """累加 LLMUsageEvent 到 Redis HASH。

        使用 Redis pipeline 批量执行 HINCRBY 操作。
        首次写入时设置 TTL。
        所有异常被捕获并记录日志,不阻塞主链路。

        Args:
            event: LLM 用量事件
        """
        try:
            # 计算当前小时的 bucket key
            bucket_key = self._make_bucket_key(event.timestamp)

            # 构建 field 前缀
            field_prefix = f"{event.label}::{event.call_point}"

            # 获取 Redis client(用于创建 pipeline)
            client = self._redis.client

            # 构建 pipeline 批量操作
            async with client.pipeline(transaction=False) as pipe:
                # HINCRBY 各指标
                # count: +1
                pipe.hincrby(bucket_key, f"{field_prefix}::count", 1)

                # input_tok: +event.tokens.input_tokens
                pipe.hincrby(
                    bucket_key,
                    f"{field_prefix}::input_tok",
                    event.tokens.input_tokens,
                )

                # output_tok: +event.tokens.output_tokens
                pipe.hincrby(
                    bucket_key,
                    f"{field_prefix}::output_tok",
                    event.tokens.output_tokens,
                )

                # total_tok: +event.tokens.total_tokens
                pipe.hincrby(
                    bucket_key,
                    f"{field_prefix}::total_tok",
                    event.tokens.total_tokens,
                )

                # latency_ms: +event.latency_ms(取整)
                pipe.hincrby(
                    bucket_key,
                    f"{field_prefix}::latency_ms",
                    int(event.latency_ms),
                )

                # success: +1 if event.success else 0
                pipe.hincrby(
                    bucket_key,
                    f"{field_prefix}::success",
                    1 if event.success else 0,
                )

                # failure: +0 if event.success else 1
                pipe.hincrby(
                    bucket_key,
                    f"{field_prefix}::failure",
                    0 if event.success else 1,
                )

                # 设置 TTL(使用 EXPIRE,如果 key 已存在则刷新过期时间)
                pipe.expire(bucket_key, self._ttl)

                # 执行 pipeline
                await pipe.execute()

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

    async def get_bucket_data(self, bucket_key: str) -> dict[str, str]:
        """获取指定桶的所有数据。

        用于测试和调试目的。

        Args:
            bucket_key: 桶的 Redis key

        Returns:
            HASH 中的所有 field-value 对
        """
        try:
            return await self._redis.client.hgetall(bucket_key)
        except Exception as exc:
            log.error(
                "llm_usage_buffer_get_failed",
                bucket_key=bucket_key,
                error=str(exc),
            )
            return {}

    async def get_current_bucket_key(self) -> str:
        """获取当前小时的桶 key。

        Returns:
            当前小时的桶 key
        """
        return self._make_bucket_key(datetime.now(UTC))
