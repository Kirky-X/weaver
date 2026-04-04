# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB LLM usage repository for basic usage tracking.

Simplified version of LLMUsageRepo for DuckDB support.
Focuses on raw record insertion for testing purposes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from core.db.models import LLMUsageRaw
from core.event.bus import LLMUsageEvent
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.db.duckdb_pool import DuckDBPool

log = get_logger("duckdb_llm_usage_repo")


class DuckDBLLMUsageRepo:
    """DuckDB LLM usage repository.

    Simplified version focusing on raw record insertion.
    For production usage tracking, use PostgreSQL version.
    """

    def __init__(self, pool: DuckDBPool) -> None:
        """Initialize with DuckDB pool.

        Args:
            pool: DuckDB connection pool.
        """
        self._pool = pool

    async def insert_raw(self, event: LLMUsageEvent) -> None:
        """Insert a single LLM usage raw record.

        Args:
            event: The LLM usage event to persist.
        """
        async with self._pool.session() as session:
            session.add(
                LLMUsageRaw(
                    label=event.label,
                    call_point=event.call_point,
                    llm_type=event.llm_type,
                    provider=event.provider,
                    model=event.model,
                    input_tokens=event.tokens.input_tokens,
                    output_tokens=event.tokens.output_tokens,
                    total_tokens=event.tokens.total_tokens,
                    latency_ms=event.latency_ms,
                    success=event.success,
                    error_type=event.error_type,
                    article_id=event.article_id,
                    task_id=event.task_id,
                    created_at=event.timestamp,
                )
            )
            await session.commit()

        log.debug("llm_usage_raw_inserted", label=event.label, call_point=event.call_point)

    async def insert_raw_batch(self, events: list[LLMUsageEvent]) -> int:
        """Insert multiple LLM usage raw records in batch.

        Args:
            events: List of LLM usage events to persist.

        Returns:
            Number of records inserted.
        """
        if not events:
            return 0

        records = [
            LLMUsageRaw(
                label=event.label,
                call_point=event.call_point,
                llm_type=event.llm_type,
                provider=event.provider,
                model=event.model,
                input_tokens=event.tokens.input_tokens,
                output_tokens=event.tokens.output_tokens,
                total_tokens=event.tokens.total_tokens,
                latency_ms=event.latency_ms,
                success=event.success,
                error_type=event.error_type,
                article_id=event.article_id,
                task_id=event.task_id,
                created_at=event.timestamp,
            )
            for event in events
        ]

        async with self._pool.session() as session:
            session.add_all(records)
            await session.commit()

        log.debug("llm_usage_raw_batch_inserted", count=len(records))
        return len(records)

    async def get_latency_bounds(
        self,
        time_bucket: datetime,
        label: str,
        call_point: str,
    ) -> tuple[float, float]:
        """Query min/max latency from raw records.

        Args:
            time_bucket: The hour bucket.
            label: The label to filter by.
            call_point: The call point.

        Returns:
            Tuple of (min_latency, max_latency). Returns (0.0, 0.0) if no records.
        """
        from datetime import timedelta

        start_time = time_bucket
        end_time = time_bucket + timedelta(hours=1)

        stmt = select(
            func.min(LLMUsageRaw.latency_ms).label("min_latency"),
            func.max(LLMUsageRaw.latency_ms).label("max_latency"),
        ).where(
            LLMUsageRaw.label == label,
            LLMUsageRaw.call_point == call_point,
            LLMUsageRaw.created_at >= start_time,
            LLMUsageRaw.created_at < end_time,
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            row = result.first()

        if row is None or row.min_latency is None:
            return (0.0, 0.0)

        return (float(row.min_latency), float(row.max_latency))

    async def cleanup_raw_older_than(self, days: int = 2) -> int:
        """Delete raw records older than the specified number of days.

        Args:
            days: Number of days to retain.

        Returns:
            Number of rows deleted.
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.session() as session:
            result = await session.execute(
                delete(LLMUsageRaw).where(LLMUsageRaw.created_at < cutoff)
            )
            await session.commit()
            removed = result.rowcount

        log.info("llm_usage_raw_cleanup_done", days=days, removed=removed)
        return removed
