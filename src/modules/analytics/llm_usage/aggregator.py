# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM usage statistics aggregation utilities.

This module provides utilities for aggregating LLM usage data from Redis to PostgreSQL:
- flush_usage_buffer: Flushes Redis buffer data to PostgreSQL hourly table
- aggregate_usage_data: Helper for aggregating Redis hash data
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.constants import RedisKeys
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import CachePool, RelationalPool

log = get_logger("llm_usage_aggregator")

# Redis key prefix for LLM usage buffer (from RedisKeys.LLM_USAGE_PREFIX)
REDIS_KEY_PREFIX = RedisKeys.LLM_USAGE_PREFIX.rstrip(":")


async def flush_usage_buffer(
    cache: CachePool,
    relational_pool: RelationalPool,
) -> tuple[int, int]:
    """Execute aggregation flush from Redis to PostgreSQL.

    Steps:
    1. SCAN Redis for llm:usage:* keys
    2. Filter out current hour bucket
    3. For each key: HGETALL → group by (label, call_point)
    4. Query min/max latency from llm_usage_raw
    5. UPSERT to llm_usage_hourly
    6. DEL the processed Redis key

    Args:
        cache: Cache pool for reading buffer data.
        relational_pool: Relational database pool for writing aggregated data.

    Returns:
        Tuple of (processed_count, error_count).
    """
    from modules.analytics.llm_usage.repo import LLMUsageRepo

    # Calculate current hour bucket (to exclude)
    now = datetime.now(UTC)
    current_hour_bucket = now.replace(minute=0, second=0, microsecond=0)
    current_hour_key = f"{REDIS_KEY_PREFIX}:{current_hour_bucket.strftime('%Y%m%d%H')}"

    # Scan all llm:usage:* keys
    cursor = 0
    keys_to_process: list[str] = []

    while True:
        cursor, keys = await cache.scan(
            cursor=cursor,
            match=f"{REDIS_KEY_PREFIX}:*",
            count=100,
        )
        # Filter out current hour
        keys_to_process.extend(k for k in keys if k != current_hour_key)

        if cursor == 0:
            break

    if not keys_to_process:
        log.debug("llm_usage_aggregator_no_keys")
        return (0, 0)

    log.info("llm_usage_aggregator_flush_start", keys=len(keys_to_process))

    repo = LLMUsageRepo(relational_pool)
    processed = 0
    errors = 0

    for key in keys_to_process:
        try:
            # Parse time bucket from key (llm:usage:2024011510)
            bucket_str = key.split(":")[-1]
            time_bucket = datetime.strptime(bucket_str, "%Y%m%d%H").replace(tzinfo=UTC)

            # Get all data from the hash
            data = await cache.hgetall(key)
            if not data:
                # Empty hash, just delete it
                await cache.delete(key)
                continue

            # Group by (label, call_point)
            aggregated = aggregate_usage_data(data)

            # For each group, upsert to hourly table
            for (label, call_point), agg in aggregated.items():
                # Query min/max latency from raw records
                latency_min, latency_max = await repo.get_latency_bounds(
                    time_bucket, label, call_point
                )

                await repo.upsert_hourly(
                    time_bucket=time_bucket,
                    label=label,
                    call_point=call_point,
                    llm_type=agg["llm_type"],
                    provider=agg["provider"],
                    model=agg["model"],
                    call_count=agg["count"],
                    input_tokens_sum=agg["input_tok"],
                    output_tokens_sum=agg["output_tok"],
                    total_tokens_sum=agg["total_tok"],
                    latency_sum=agg["latency_ms"],
                    latency_min=latency_min,
                    latency_max=latency_max,
                    success_count=agg["success"],
                    failure_count=agg["failure"],
                )

            # Delete the processed Redis key
            await cache.delete(key)
            processed += 1

            log.debug(
                "llm_usage_aggregator_key_processed",
                key=key,
                groups=len(aggregated),
            )

        except Exception as e:
            errors += 1
            log.error(
                "llm_usage_aggregator_key_failed",
                key=key,
                error=str(e),
            )

    log.info(
        "llm_usage_aggregator_flush_complete",
        processed=processed,
        errors=errors,
    )

    return (processed, errors)


def _parse_field(field: str) -> tuple[str, str, str] | None:
    """Parse a Redis hash field into label, call_point, metric.

    Args:
        field: Field string in format "{label}::{call_point}::{metric}".

    Returns:
        Tuple of (label, call_point, metric) or None if invalid.
    """
    parts = field.rsplit("::", 2)
    if len(parts) != 3:
        log.warning("llm_usage_aggregator_invalid_field", field=field)
        return None
    return tuple(parts)  # type: ignore[return-value]


def _parse_label(label: str) -> tuple[str, str, str]:
    """Parse a label into llm_type, provider, model.

    Label format: "{llm_type}::{provider}::{model}" or "{provider}::{model}"

    Args:
        label: Label string to parse.

    Returns:
        Tuple of (llm_type, provider, model).
    """
    label_parts = label.split("::")
    if len(label_parts) == 3:
        return tuple(label_parts)  # type: ignore[return-value]
    elif len(label_parts) == 2:
        return ("chat", label_parts[0], label_parts[1])
    else:
        return ("chat", "unknown", label)


def _aggregate_metric(agg: dict[str, Any], metric: str, value: int) -> None:
    """Aggregate a single metric value into the aggregation dict.

    Args:
        agg: Aggregation dictionary to update.
        metric: Metric name (count, input_tok, etc.).
        value: Integer value to add.
    """
    if metric == "count":
        agg["count"] += value
    elif metric == "input_tok":
        agg["input_tok"] += value
    elif metric == "output_tok":
        agg["output_tok"] += value
    elif metric == "total_tok":
        agg["total_tok"] += value
    elif metric == "latency_ms":
        agg["latency_ms"] += float(value)
    elif metric == "success":
        agg["success"] += value
    elif metric == "failure":
        agg["failure"] += value


def aggregate_usage_data(data: dict[str, str]) -> dict[tuple[str, str], dict[str, Any]]:
    """Aggregate Redis hash data by (label, call_point).

    Redis hash field format: {label}::{call_point}::{metric}
    Metrics: count, input_tok, output_tok, total_tok, latency_ms, success, failure

    Args:
        data: Redis HGETALL result (field -> value).

    Returns:
        Dict mapping (label, call_point) to aggregated metrics.
    """
    result: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "input_tok": 0,
            "output_tok": 0,
            "total_tok": 0,
            "latency_ms": 0.0,
            "success": 0,
            "failure": 0,
            "llm_type": "",
            "provider": "",
            "model": "",
        }
    )

    for field, value in data.items():
        # Parse field using helper
        parsed = _parse_field(field)
        if parsed is None:
            continue

        label, call_point, metric = parsed
        key = (label, call_point)

        # Parse label using helper
        llm_type, provider, model = _parse_label(label)
        result[key]["llm_type"] = llm_type
        result[key]["provider"] = provider
        result[key]["model"] = model

        # Aggregate metric using helper
        try:
            int_value = int(value)
            _aggregate_metric(result[key], metric, int_value)
        except ValueError:
            log.warning(
                "llm_usage_aggregator_parse_failed",
                field=field,
                value=value,
                error="invalid integer value",
            )

    return dict(result)
