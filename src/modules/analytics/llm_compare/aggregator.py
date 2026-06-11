# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM comparison statistics aggregation utilities.

This module provides utilities for aggregating LLM comparison data from Redis to PostgreSQL:
- flush_compare_buffer: Flushes Redis buffer data to PostgreSQL hourly table
- aggregate_compare_data: Helper for aggregating Redis hash data
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import CachePool, RelationalPool

log = get_logger(__name__)

# Redis key prefix for LLM comparison buffer
REDIS_KEY_PREFIX = "llm:compare"

# Batch size for Redis SCAN operations
REDIS_SCAN_BATCH_SIZE = 100


async def flush_compare_buffer(
    cache: CachePool,
    relational_pool: RelationalPool,
) -> tuple[int, int]:
    """Execute aggregation flush from Redis to PostgreSQL.

    Steps:
    1. SCAN Redis for llm:compare:* keys
    2. Filter out current hour bucket
    3. For each key: HGETALL → group by (call_point, primary_model, candidate_model)
    4. UPSERT to llm_compare_hourly
    5. DEL the processed Redis key

    Args:
        cache: Cache pool for reading buffer data.
        relational_pool: Relational database pool for writing aggregated data.

    Returns:
        Tuple of (processed_count, error_count).
    """
    from modules.analytics.llm_compare.repo import EvalCompareRepo

    # Calculate current hour bucket (to exclude)
    now = datetime.now(UTC)
    current_hour_bucket = now.replace(minute=0, second=0, microsecond=0)
    current_hour_key = f"{REDIS_KEY_PREFIX}:{current_hour_bucket.strftime('%Y%m%d%H')}"

    # Scan all llm:compare:* keys
    cursor = 0
    keys_to_process: list[str] = []

    while True:
        cursor, keys = await cache.scan(
            cursor=cursor,
            match=f"{REDIS_KEY_PREFIX}:*",
            count=REDIS_SCAN_BATCH_SIZE,
        )
        # Filter out current hour
        keys_to_process.extend(k for k in keys if k != current_hour_key)

        if cursor == 0:
            break

    if not keys_to_process:
        log.debug("llm_compare_aggregator_no_keys")
        return (0, 0)

    log.info("llm_compare_aggregator_flush_start", keys=len(keys_to_process))

    repo = EvalCompareRepo(relational_pool)
    processed = 0
    errors = 0

    for key in keys_to_process:
        try:
            # Parse time bucket from key (llm:compare:2024011510)
            bucket_str = key.split(":")[-1]
            time_bucket = datetime.strptime(bucket_str, "%Y%m%d%H").replace(tzinfo=UTC)

            # Get all data from the hash
            data = await cache.hgetall(key)
            if not data:
                # Empty hash, just delete it
                await cache.delete(key)
                continue

            # Group by (call_point, primary_model, candidate_model)
            aggregated = aggregate_compare_data(data)

            # For each group, upsert to hourly table
            for (call_point, primary_model, candidate_model), agg in aggregated.items():
                await repo.upsert_hourly(
                    time_bucket=time_bucket,
                    call_point=call_point,
                    primary_model=primary_model,
                    candidate_model=candidate_model,
                    comparison_count=agg["count"],
                    primary_latency_sum=agg["primary_latency_sum"],
                    candidate_latency_sum=agg["candidate_latency_sum"],
                    primary_success_count=agg["primary_success"],
                    candidate_success_count=agg["candidate_success"],
                )

            # Delete the processed Redis key
            await cache.delete(key)
            processed += 1

            log.debug(
                "llm_compare_aggregator_key_processed",
                key=key,
                groups=len(aggregated),
            )

        except Exception as e:
            errors += 1
            log.error(
                "llm_compare_aggregator_key_failed",
                key=key,
                error=str(e),
            )

    log.info(
        "llm_compare_aggregator_flush_complete",
        processed=processed,
        errors=errors,
    )

    return (processed, errors)


def aggregate_compare_data(
    data: dict[str, str],
) -> dict[tuple[str, str, str], dict[str, int]]:
    """Aggregate Redis hash data by (call_point, primary_model, candidate_model).

    Args:
        data: Redis HGETALL result with field-value pairs.

    Returns:
        Dict mapping (call_point, primary_model, candidate_model) to aggregated metrics.
    """
    aggregated: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: {
            "count": 0,
            "primary_latency_sum": 0,
            "candidate_latency_sum": 0,
            "primary_success": 0,
            "candidate_success": 0,
        }
    )

    for field, value_str in data.items():
        try:
            value = int(value_str)
        except ValueError:
            log.warning("llm_compare_aggregator_invalid_value", field=field, value=value_str)
            continue

        # Parse field: {call_point}::{primary_model}::{candidate_model}::{metric}
        parts = field.split("::")
        if len(parts) != 4:
            log.warning("llm_compare_aggregator_invalid_field", field=field)
            continue

        call_point, primary_model, candidate_model, metric = parts

        key = (call_point, primary_model, candidate_model)
        if metric == "count":
            aggregated[key]["count"] += value
        elif metric == "primary_latency_sum":
            aggregated[key]["primary_latency_sum"] += value
        elif metric == "candidate_latency_sum":
            aggregated[key]["candidate_latency_sum"] += value
        elif metric == "primary_success":
            aggregated[key]["primary_success"] += value
        elif metric == "candidate_success":
            aggregated[key]["candidate_success"] += value

    return aggregated
