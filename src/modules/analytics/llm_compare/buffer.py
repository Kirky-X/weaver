# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Redis buffer for LLM comparison results.

Follows the same pattern as LLMUsageBuffer:
- Accumulates LLMCompareEvent to Redis HASH by hour bucket
- Supports TTL auto-expiration
- Aggregates to relational_pool via EvalCompareRepo
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from core.constants import RedisKeys
from core.event import LLMCompareEvent
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger(__name__)

# Redis key prefix（不带尾冒号；单一定义在 core.constants.RedisKeys）
REDIS_KEY_PREFIX = RedisKeys.LLM_COMPARE_PREFIX
# Default TTL: 24 hours
DEFAULT_TTL_SECONDS = 86400
# Supported metrics
METRICS = (
    "count",
    "primary_latency_sum",
    "candidate_latency_sum",
    "primary_success",
    "candidate_success",
)


class EvalCompareBuffer:
    """LLM comparison event buffer.

    Accumulates LLMCompareEvent to Redis HASH by hour bucket.
    Fields: {primary_model}::{candidate_model}::{call_point}::{metric}
    """

    def __init__(
        self,
        cache: CachePool,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """Initialize the comparison buffer.

        Args:
            cache: Cache pool instance.
            ttl_seconds: Key TTL in seconds.
        """
        self._cache = cache
        self._ttl = ttl_seconds

    def _make_bucket_key(self, dt: datetime) -> str:
        """Generate hour-level bucket Redis key."""
        return f"{REDIS_KEY_PREFIX}:{dt.strftime('%Y%m%d%H')}"

    def _make_field_name(
        self,
        call_point: str,
        primary_model: str,
        candidate_model: str,
        metric: str,
    ) -> str:
        """Generate HASH field name."""
        return f"{call_point}::{primary_model}::{candidate_model}::{metric}"

    async def accumulate(self, event: LLMCompareEvent) -> None:
        """Accumulate LLMCompareEvent to Redis HASH.

                Uses a pipeline for batch execution of the counter increments (one
                round-trip instead of five), matching ``LLMUsageBuffer.accumulate``
        . Sets TTL only on the first write to the hour-bucket key: an
                unconditional ``expire`` on every event would push the TTL forward
                indefinitely under sustained load. All exceptions are caught and
                logged — does not block main path.
        """
        try:
            bucket_key = self._make_bucket_key(event.timestamp)

            # Check before writing: after the hincrby calls below the hash is
            # guaranteed non-empty, so a post-write check can never detect a
            # newly-created key.
            is_new = not await self._cache.hgetall(bucket_key)

            # Latencies are rounded instead of truncated: int() biases the
            # cumulative sums (and hence hourly averages) downward by up to
            # 1 ms per event.
            async with self._cache.pipeline() as pipe:
                pipe.hincrby(
                    bucket_key,
                    self._make_field_name(
                        event.call_point, event.primary_model, event.candidate_model, "count"
                    ),
                    1,
                )
                pipe.hincrby(
                    bucket_key,
                    self._make_field_name(
                        event.call_point,
                        event.primary_model,
                        event.candidate_model,
                        "primary_latency_sum",
                    ),
                    round(event.primary_latency),
                )
                pipe.hincrby(
                    bucket_key,
                    self._make_field_name(
                        event.call_point,
                        event.primary_model,
                        event.candidate_model,
                        "candidate_latency_sum",
                    ),
                    round(event.candidate_latency),
                )
                pipe.hincrby(
                    bucket_key,
                    self._make_field_name(
                        event.call_point,
                        event.primary_model,
                        event.candidate_model,
                        "primary_success",
                    ),
                    1 if event.primary_success else 0,
                )
                pipe.hincrby(
                    bucket_key,
                    self._make_field_name(
                        event.call_point,
                        event.primary_model,
                        event.candidate_model,
                        "candidate_success",
                    ),
                    1 if event.candidate_success else 0,
                )
                await pipe.execute()

            # Set TTL only when this event created the bucket key
            if is_new:
                await self._cache.expire(bucket_key, self._ttl)

            log.debug(
                "eval_comparison_buffered",
                bucket_key=bucket_key,
                call_point=event.call_point,
                primary=event.primary_model,
                candidate=event.candidate_model,
            )

        except Exception as exc:
            log.error(
                "eval_comparison_buffer_failed",
                call_point=event.call_point,
                error=str(exc),
            )
