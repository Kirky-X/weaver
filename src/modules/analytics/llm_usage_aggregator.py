# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Independent daemon threads for LLM usage statistics aggregation and cleanup.

This module provides two background threads:
1. LLMUsageAggregatorThread: Flushes Redis buffer data to PostgreSQL hourly table
2. LLMUsageRawCleanupThread: Cleans up old raw records based on retention policy
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.constants import RedisKeys
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.cache.redis import RedisClient
    from core.db.postgres import PostgresPool

log = get_logger("llm_usage_aggregator")

# Redis key prefix for LLM usage buffer (from RedisKeys.LLM_USAGE_PREFIX)
REDIS_KEY_PREFIX = RedisKeys.LLM_USAGE_PREFIX.rstrip(":")


class LLMUsageAggregatorThread:
    """Daemon thread that aggregates LLM usage data from Redis to PostgreSQL.

    Periodically scans Redis for completed hour buckets (not the current hour),
    aggregates the data by (label, call_point), and upserts to llm_usage_hourly table.

    Flow:
    1. SCAN Redis for llm:usage:* keys
    2. Filter out current hour bucket
    3. For each key: HGETALL → group by (label, call_point)
    4. Query min/max latency from llm_usage_raw
    5. UPSERT to llm_usage_hourly
    6. DEL the processed Redis key
    """

    def __init__(
        self,
        redis_client: RedisClient,
        postgres_pool: PostgresPool,
        interval_minutes: int = 5,
    ) -> None:
        """Initialize the aggregator thread.

        Args:
            redis_client: Redis client for reading buffer data.
            postgres_pool: PostgreSQL connection pool for writing aggregated data.
            interval_minutes: Flush interval in minutes (default 5).
        """
        self._redis = redis_client
        self._postgres = postgres_pool
        self._interval = interval_minutes * 60
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the aggregator thread. Runs flush once immediately, then loops."""
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="llm-usage-aggregator",
        )
        self._thread.start()
        log.info("llm_usage_aggregator_thread_started", interval_minutes=self._interval // 60)

    def _run(self) -> None:
        """Thread target: own event loop, run flush immediately then loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Immediate flush on startup
            self._execute_flush(loop)
            # Then loop: sleep interval between runs
            # Defensive: ensure interval is a valid numeric value (handles mock in tests)
            interval = self._interval if isinstance(self._interval, (int, float)) else 300
            while not self._stop_event.wait(interval):
                # Each iteration gets a fresh loop to avoid loop-state corruption
                # if the postgres pool was closed by container.shutdown().
                loop.close()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._execute_flush(loop)
        finally:
            loop.close()
            log.info("llm_usage_aggregator_thread_stopped")

    def _execute_flush(self, loop: asyncio.AbstractEventLoop) -> None:
        """Run one flush cycle on the given loop, catching loop/pool errors."""
        try:
            loop.run_until_complete(self._flush())
        except RuntimeError as e:
            # Raised when the loop is already closed (container shut down mid-sleep).
            log.debug("llm_usage_aggregator_loop_closed", error=str(e))
        except Exception as e:
            # Raised when asyncpg connection is already closed (pool shut down).
            log.warning("llm_usage_aggregator_flush_error", error=str(e))

    async def _flush(self) -> None:
        """Execute aggregation flush from Redis to PostgreSQL.

        Steps:
        1. SCAN Redis for llm:usage:* keys
        2. Filter out current hour bucket
        3. For each key: HGETALL → group by (label, call_point)
        4. Query min/max latency from llm_usage_raw
        5. UPSERT to llm_usage_hourly
        6. DEL the processed Redis key
        """
        from modules.storage.llm_usage_repo import LLMUsageRepo

        # Calculate current hour bucket (to exclude)
        now = datetime.now(UTC)
        current_hour_bucket = now.replace(minute=0, second=0, microsecond=0)
        current_hour_key = f"{REDIS_KEY_PREFIX}:{current_hour_bucket.strftime('%Y%m%d%H')}"

        # Scan all llm:usage:* keys
        cursor = 0
        keys_to_process: list[str] = []

        while True:
            cursor, keys = await self._redis.scan(
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
            return

        log.info("llm_usage_aggregator_flush_start", keys=len(keys_to_process))

        repo = LLMUsageRepo(self._postgres)
        processed = 0
        errors = 0

        for key in keys_to_process:
            try:
                # Parse time bucket from key (llm:usage:2024011510)
                bucket_str = key.split(":")[-1]
                time_bucket = datetime.strptime(bucket_str, "%Y%m%d%H").replace(tzinfo=UTC)

                # Get all data from the hash
                data = await self._redis.client.hgetall(key)
                if not data:
                    # Empty hash, just delete it
                    await self._redis.delete(key)
                    continue

                # Group by (label, call_point)
                aggregated = self._aggregate_data(data)

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
                await self._redis.delete(key)
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

    def _aggregate_data(self, data: dict[str, str]) -> dict[tuple[str, str], dict[str, Any]]:
        """Aggregate Redis hash data by (label, call_point).

        Redis hash field format: {label}::{call_point}::{metric}
        Metrics: count, input_tok, output_tok, total_tok, latency_ms, success, failure

        Args:
            data: Redis HGETALL result (field -> value).

        Returns:
            Dict mapping (label, call_point) to aggregated metrics.
        """
        # Group data by (label, call_point)
        # We need to also extract llm_type, provider, model from the label
        # Label format: "{llm_type}::{provider}::{model}"
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
            try:
                # Parse field: {label}::{call_point}::{metric}
                parts = field.rsplit("::", 2)
                if len(parts) != 3:
                    log.warning("llm_usage_aggregator_invalid_field", field=field)
                    continue

                label, call_point, metric = parts
                key = (label, call_point)

                # Parse label to extract llm_type, provider, model
                # Label format: "{llm_type}::{provider}::{model}" or just "{provider}::{model}"
                label_parts = label.split("::")
                if len(label_parts) == 3:
                    llm_type, provider, model = label_parts
                elif len(label_parts) == 2:
                    llm_type = "chat"  # Default
                    provider, model = label_parts
                else:
                    llm_type = "chat"
                    provider = "unknown"
                    model = label

                result[key]["llm_type"] = llm_type
                result[key]["provider"] = provider
                result[key]["model"] = model

                # Parse value and aggregate
                int_value = int(value)

                if metric == "count":
                    result[key]["count"] += int_value
                elif metric == "input_tok":
                    result[key]["input_tok"] += int_value
                elif metric == "output_tok":
                    result[key]["output_tok"] += int_value
                elif metric == "total_tok":
                    result[key]["total_tok"] += int_value
                elif metric == "latency_ms":
                    result[key]["latency_ms"] += float(int_value)
                elif metric == "success":
                    result[key]["success"] += int_value
                elif metric == "failure":
                    result[key]["failure"] += int_value

            except (ValueError, IndexError) as e:
                log.warning(
                    "llm_usage_aggregator_parse_failed",
                    field=field,
                    value=value,
                    error=str(e),
                )
                continue

        return dict(result)

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to terminate."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)


class LLMUsageRawCleanupThread:
    """Daemon thread that cleans up old raw LLM usage records.

    Runs cleanup on start (closing the startup vacuum gap), then every 6 hours.
    Thread-safe: creates its own asyncio event loop.
    """

    def __init__(
        self,
        postgres_pool: PostgresPool,
        retention_days: int = 2,
        interval_hours: int = 6,
    ) -> None:
        """Initialize the cleanup thread.

        Args:
            postgres_pool: PostgreSQL connection pool.
            retention_days: Number of days to retain raw records (default 2 = 48h).
            interval_hours: Cleanup interval in hours (default 6).
        """
        self._postgres = postgres_pool
        self._retention_days = retention_days
        self._interval = interval_hours * 3600
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the cleanup thread. Runs cleanup once immediately, then loops."""
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="llm-usage-raw-cleanup",
        )
        self._thread.start()
        log.info(
            "llm_usage_raw_cleanup_thread_started",
            retention_days=self._retention_days,
            interval_hours=self._interval // 3600,
        )

    def _run(self) -> None:
        """Thread target: own event loop, run cleanup immediately then loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Immediate cleanup on startup
            self._execute_cleanup(loop)
            # Then loop: sleep interval between runs
            # Defensive: ensure interval is a valid numeric value (handles mock in tests)
            interval = self._interval if isinstance(self._interval, (int, float)) else 21600
            while not self._stop_event.wait(interval):
                # Each iteration gets a fresh loop to avoid loop-state corruption
                loop.close()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._execute_cleanup(loop)
        finally:
            loop.close()
            log.info("llm_usage_raw_cleanup_thread_stopped")

    def _execute_cleanup(self, loop: asyncio.AbstractEventLoop) -> None:
        """Run one cleanup cycle on the given loop, catching loop/pool errors."""
        try:
            loop.run_until_complete(self._cleanup())
        except RuntimeError as e:
            # Raised when the loop is already closed (container shut down mid-sleep).
            log.debug("llm_usage_raw_cleanup_loop_closed", error=str(e))
        except Exception as e:
            # Raised when asyncpg connection is already closed (pool shut down).
            log.warning("llm_usage_raw_cleanup_error", error=str(e))

    async def _cleanup(self) -> None:
        """Execute cleanup of old raw records."""
        from modules.storage.llm_usage_repo import LLMUsageRepo

        repo = LLMUsageRepo(self._postgres)
        deleted = await repo.cleanup_raw_older_than(self._retention_days)

        log.info("llm_usage_raw_cleanup_complete", deleted=deleted)

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to terminate."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
