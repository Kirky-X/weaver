# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Redis buffer for LLM comparison results.

Follows the same pattern as LLMUsageBuffer:
- Accumulates LLMCompareEvent to Redis HASH by hour bucket
- Supports TTL auto-expiration
- Aggregates to relational_pool via EvalCompareRepo
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from core.event.bus import LLMCompareEvent
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger("eval_compare_buffer")

# Redis key prefix
REDIS_KEY_PREFIX = "llm:compare"
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

        Uses pipeline for batch execution. Sets TTL on first write.
        All exceptions are caught and logged — does not block main path.
        """
        try:
            bucket_key = self._make_bucket_key(event.timestamp)
            prefix = f"{event.call_point}::{event.primary_model}::{event.candidate_model}"

            # Increment counters
            await self._cache.hincrby(bucket_key, f"{prefix}::count", 1)
            await self._cache.hincrby(
                bucket_key,
                f"{prefix}::primary_latency_sum",
                int(event.primary_latency),
            )
            await self._cache.hincrby(
                bucket_key,
                f"{prefix}::candidate_latency_sum",
                int(event.candidate_latency),
            )
            await self._cache.hincrby(
                bucket_key,
                f"{prefix}::primary_success",
                1 if event.primary_success else 0,
            )
            await self._cache.hincrby(
                bucket_key,
                f"{prefix}::candidate_success",
                1 if event.candidate_success else 0,
            )

            # Set TTL
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
