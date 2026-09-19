# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""DuckDB LLM usage repository for usage tracking.

Subclasses the PostgreSQL ``LLMUsageRepo`` and overrides only the write
paths with real dialect differences: ``insert_raw`` (explicit created_at),
``upsert_hourly`` (DELETE + INSERT — DuckDB lacks ON CONFLICT) and
``cleanup_raw_older_than``. All query/aggregation methods are inherited
unchanged: both backends query the same SQLAlchemy ORM models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from core.db import LLMUsageHourly, LLMUsageRaw
from core.event import LLMUsageEvent
from core.observability import get_logger
from modules.analytics.llm_usage.repo import LLMUsageRepo


if TYPE_CHECKING:
    from core.db.duckdb_pool import DuckDBPool

log = get_logger(__name__)

# The string_agg dimension delimiter (AGG_DELIMITER, ASCII unit separator)
# is inherited from the PG repo, whose single source is core.constants.


class DuckDBLLMUsageRepo(LLMUsageRepo):
    """DuckDB LLM usage repository.

    DuckDB-compatible implementation mirroring LLMUsageRepo's public API.
    Uses DELETE + INSERT for upsert (no ON CONFLICT) and string_agg for
    distinct value aggregation (no array_agg(distinct ...)).
    """

    def __init__(self, pool: DuckDBPool) -> None:
        """Initialize with DuckDB pool.

        Args:
            pool: DuckDB connection pool.
        """
        super().__init__(pool)

    # ── Raw Record Operations ─────────────────────────────────────

    async def insert_raw(self, event: LLMUsageEvent) -> None:
        """Insert a single LLM usage raw record.

        Args:
            event: The LLM usage event to persist.
        """
        article_id = uuid.UUID(event.article_id) if event.article_id else None
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
                    cached_tokens=event.tokens.cached_tokens,
                    reasoning_tokens=event.tokens.reasoning_tokens,
                    cost_usd=event.cost_usd,
                    latency_ms=event.latency_ms,
                    success=event.success,
                    error_type=event.error_type,
                    article_id=article_id,
                    task_id=event.task_id,
                    created_at=event.timestamp,
                )
            )
            await session.commit()

        log.debug("llm_usage_raw_inserted", label=event.label, call_point=event.call_point)

    # ── Aggregation Operations ────────────────────────────────────

    async def upsert_hourly(
        self,
        time_bucket: datetime,
        label: str,
        call_point: str,
        llm_type: str,
        provider: str,
        model: str,
        call_count: int,
        input_tokens_sum: int,
        output_tokens_sum: int,
        total_tokens_sum: int,
        latency_sum: float,
        latency_min: float,
        latency_max: float,
        success_count: int,
        failure_count: int,
        cached_tokens_sum: int = 0,
        reasoning_tokens_sum: int = 0,
        cost_usd_sum: float = 0.0,
    ) -> None:
        """Upsert an hourly aggregated record using DELETE + INSERT.

        DuckDB lacks PostgreSQL's ON CONFLICT clause, so we delete any
        existing row matching (time_bucket, label, call_point) before
        inserting the new record. This achieves idempotent upsert.

        Args:
            time_bucket: The hour bucket.
            label: The label.
            call_point: The call point.
            llm_type: LLM type (chat/embedding/rerank).
            provider: Provider name.
            model: Model name.
            call_count: Total call count.
            input_tokens_sum: Sum of input tokens.
            output_tokens_sum: Sum of output tokens.
            total_tokens_sum: Sum of total tokens.
            cached_tokens_sum: Sum of cached tokens.
            reasoning_tokens_sum: Sum of reasoning tokens.
            cost_usd_sum: Sum of cost in USD.
            latency_sum: Sum of latency (for avg calculation).
            latency_min: Minimum latency.
            latency_max: Maximum latency.
            success_count: Count of successful calls.
            failure_count: Count of failed calls.
        """
        latency_avg = latency_sum / call_count if call_count > 0 else 0.0

        async with self._pool.session() as session:
            # Delete existing record matching the unique key
            await session.execute(
                delete(LLMUsageHourly).where(
                    LLMUsageHourly.time_bucket == time_bucket,
                    LLMUsageHourly.label == label,
                    LLMUsageHourly.call_point == call_point,
                )
            )

            session.add(
                LLMUsageHourly(
                    time_bucket=time_bucket,
                    label=label,
                    call_point=call_point,
                    llm_type=llm_type,
                    provider=provider,
                    model=model,
                    call_count=call_count,
                    input_tokens_sum=input_tokens_sum,
                    output_tokens_sum=output_tokens_sum,
                    total_tokens_sum=total_tokens_sum,
                    cached_tokens_sum=cached_tokens_sum,
                    reasoning_tokens_sum=reasoning_tokens_sum,
                    cost_usd_sum=cost_usd_sum,
                    latency_avg_ms=latency_avg,
                    latency_min_ms=latency_min,
                    latency_max_ms=latency_max,
                    success_count=success_count,
                    failure_count=failure_count,
                )
            )
            await session.commit()

    # ── Query Operations ──────────────────────────────────────────

    # ── Cleanup Operations ────────────────────────────────────────

    async def cleanup_raw_older_than(self, days: int = 2) -> int:
        """Delete raw records older than the specified number of days.

        Args:
            days: Number of days to retain.

        Returns:
            Number of rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.session() as session:
            # DuckDB returns -1 for DELETE rowcount: measure via
            # before/after COUNT instead of trusting rowcount.
            before = (
                await session.execute(
                    select(func.count())
                    .select_from(LLMUsageRaw)
                    .where(LLMUsageRaw.created_at < cutoff)
                )
            ).scalar() or 0
            result = await session.execute(
                delete(LLMUsageRaw).where(LLMUsageRaw.created_at < cutoff)
            )
            await session.commit()
            if result.rowcount and result.rowcount > 0:
                removed = result.rowcount
            else:
                after = (
                    await session.execute(
                        select(func.count())
                        .select_from(LLMUsageRaw)
                        .where(LLMUsageRaw.created_at < cutoff)
                    )
                ).scalar() or 0
                removed = max(0, before - after)

        log.info("llm_usage_raw_cleanup_done", days=days, removed=removed)
        return removed
