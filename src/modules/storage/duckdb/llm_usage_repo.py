# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""DuckDB LLM usage repository for usage tracking.

DuckDB-compatible version of LLMUsageRepo. Uses DELETE + INSERT pattern
for upsert (DuckDB lacks PostgreSQL's ON CONFLICT clause) and string_agg
instead of array_agg (DuckDB lacks array_agg(distinct ...) support).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, delete, func, select

from core.db import LLMUsageHourly, LLMUsageRaw
from core.event import LLMUsageEvent
from core.observability import get_logger

if TYPE_CHECKING:
    from core.db.duckdb_pool import DuckDBPool

log = get_logger(__name__)


class DuckDBLLMUsageRepo:
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
        self._pool = pool

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
                cached_tokens=event.tokens.cached_tokens,
                reasoning_tokens=event.tokens.reasoning_tokens,
                cost_usd=event.cost_usd,
                latency_ms=event.latency_ms,
                success=event.success,
                error_type=event.error_type,
                article_id=uuid.UUID(event.article_id) if event.article_id else None,
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

    async def get_hourly_stats(
        self,
        start_time: datetime,
        end_time: datetime,
        label: str | None = None,
        call_point: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query hourly aggregated statistics.

        Args:
            start_time: Start of the time range.
            end_time: End of the time range.
            label: Optional label filter.
            call_point: Optional call point filter.
            provider: Optional provider filter.

        Returns:
            List of hourly stat dictionaries.
        """
        stmt = select(LLMUsageHourly).where(
            LLMUsageHourly.time_bucket >= start_time,
            LLMUsageHourly.time_bucket < end_time,
        )

        if label:
            stmt = stmt.where(LLMUsageHourly.label == label)
        if call_point:
            stmt = stmt.where(LLMUsageHourly.call_point == call_point)
        if provider:
            stmt = stmt.where(LLMUsageHourly.provider == provider)

        stmt = stmt.order_by(LLMUsageHourly.time_bucket.desc())

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            records = result.scalars().all()

        return [
            {
                "time_bucket": r.time_bucket.isoformat(),
                "label": r.label,
                "call_point": r.call_point,
                "llm_type": r.llm_type,
                "provider": r.provider,
                "model": r.model,
                "call_count": r.call_count,
                "input_tokens_sum": r.input_tokens_sum,
                "output_tokens_sum": r.output_tokens_sum,
                "total_tokens_sum": r.total_tokens_sum,
                "latency_avg_ms": r.latency_avg_ms,
                "latency_min_ms": r.latency_min_ms,
                "latency_max_ms": r.latency_max_ms,
                "success_count": r.success_count,
                "failure_count": r.failure_count,
            }
            for r in records
        ]

    async def query_hourly(
        self,
        start_time: datetime,
        end_time: datetime,
        granularity: str = "hourly",
        provider: str | None = None,
        model: str | None = None,
        llm_type: str | None = None,
        call_point: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query aggregated usage data with time granularity.

        Uses string_agg instead of array_agg for DuckDB compatibility.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            granularity: Time granularity - "hourly", "daily", or "monthly".
            provider: Filter by provider name.
            model: Filter by model name.
            llm_type: Filter by LLM type.
            call_point: Filter by call point.

        Returns:
            List of aggregated usage records.
        """
        # Build time truncation expression based on granularity
        if granularity == "daily":
            date_trunc = func.date_trunc("day", LLMUsageHourly.time_bucket)
        elif granularity == "monthly":
            date_trunc = func.date_trunc("month", LLMUsageHourly.time_bucket)
        else:  # hourly (default)
            date_trunc = func.date_trunc("hour", LLMUsageHourly.time_bucket)

        # Build query - use string_agg instead of array_agg for DuckDB compat
        stmt = (
            select(
                date_trunc.label("time_bucket"),
                func.sum(LLMUsageHourly.call_count).label("call_count"),
                func.sum(LLMUsageHourly.input_tokens_sum).label("input_tokens_sum"),
                func.sum(LLMUsageHourly.output_tokens_sum).label("output_tokens_sum"),
                func.sum(LLMUsageHourly.total_tokens_sum).label("total_tokens_sum"),
                case(
                    (
                        func.sum(LLMUsageHourly.call_count) > 0,
                        func.sum(LLMUsageHourly.latency_avg_ms * LLMUsageHourly.call_count)
                        / func.sum(LLMUsageHourly.call_count),
                    ),
                    else_=0.0,
                ).label("latency_avg_ms"),
                func.min(LLMUsageHourly.latency_min_ms).label("latency_min_ms"),
                func.max(LLMUsageHourly.latency_max_ms).label("latency_max_ms"),
                func.sum(LLMUsageHourly.success_count).label("success_count"),
                func.sum(LLMUsageHourly.failure_count).label("failure_count"),
                func.string_agg(func.distinct(LLMUsageHourly.label), ",").label("labels"),
                func.string_agg(func.distinct(LLMUsageHourly.call_point), ",").label("call_points"),
                func.string_agg(func.distinct(LLMUsageHourly.llm_type), ",").label("llm_types"),
                func.string_agg(func.distinct(LLMUsageHourly.provider), ",").label("providers"),
                func.string_agg(func.distinct(LLMUsageHourly.model), ",").label("models"),
            )
            .where(
                and_(
                    LLMUsageHourly.time_bucket >= start_time,
                    LLMUsageHourly.time_bucket <= end_time,
                )
            )
            .group_by(date_trunc)
            .order_by(date_trunc)
        )

        if provider:
            stmt = stmt.where(LLMUsageHourly.provider == provider)
        if model:
            stmt = stmt.where(LLMUsageHourly.model == model)
        if llm_type:
            stmt = stmt.where(LLMUsageHourly.llm_type == llm_type)
        if call_point:
            stmt = stmt.where(LLMUsageHourly.call_point == call_point)

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "time_bucket": row.time_bucket.isoformat() if row.time_bucket else None,
                "call_count": row.call_count or 0,
                "input_tokens_sum": row.input_tokens_sum or 0,
                "output_tokens_sum": row.output_tokens_sum or 0,
                "total_tokens_sum": row.total_tokens_sum or 0,
                "latency_avg_ms": float(row.latency_avg_ms or 0),
                "latency_min_ms": float(row.latency_min_ms or 0),
                "latency_max_ms": float(row.latency_max_ms or 0),
                "success_count": row.success_count or 0,
                "failure_count": row.failure_count or 0,
                "label": ", ".join(sorted(set(row.labels.split(",")))) if row.labels else "",
                "call_point": (
                    ", ".join(sorted(set(row.call_points.split(",")))) if row.call_points else ""
                ),
                "llm_type": (
                    ", ".join(sorted(set(row.llm_types.split(",")))) if row.llm_types else ""
                ),
                "provider": (
                    ", ".join(sorted(set(row.providers.split(",")))) if row.providers else ""
                ),
                "model": ", ".join(sorted(set(row.models.split(",")))) if row.models else "",
            }
            for row in rows
        ]

    async def get_summary(
        self,
        start_time: datetime,
        end_time: datetime,
        provider: str | None = None,
        model: str | None = None,
        llm_type: str | None = None,
        call_point: str | None = None,
    ) -> dict[str, Any]:
        """Get summary statistics for a time range.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            provider: Filter by provider name.
            model: Filter by model name.
            llm_type: Filter by LLM type.
            call_point: Filter by call point.

        Returns:
            Summary dictionary with totals, latency, and success rate.
        """
        conditions = [
            LLMUsageHourly.time_bucket >= start_time,
            LLMUsageHourly.time_bucket <= end_time,
        ]
        if provider:
            conditions.append(LLMUsageHourly.provider == provider)
        if model:
            conditions.append(LLMUsageHourly.model == model)
        if llm_type:
            conditions.append(LLMUsageHourly.llm_type == llm_type)
        if call_point:
            conditions.append(LLMUsageHourly.call_point == call_point)

        summary_stmt = select(
            func.sum(LLMUsageHourly.call_count).label("total_calls"),
            func.sum(LLMUsageHourly.input_tokens_sum).label("total_input_tokens"),
            func.sum(LLMUsageHourly.output_tokens_sum).label("total_output_tokens"),
            func.sum(LLMUsageHourly.total_tokens_sum).label("total_tokens"),
            case(
                (
                    func.sum(LLMUsageHourly.call_count) > 0,
                    func.sum(LLMUsageHourly.latency_avg_ms * LLMUsageHourly.call_count)
                    / func.sum(LLMUsageHourly.call_count),
                ),
                else_=0.0,
            ).label("avg_latency_ms"),
            func.max(LLMUsageHourly.latency_max_ms).label("max_latency_ms"),
            func.min(LLMUsageHourly.latency_min_ms).label("min_latency_ms"),
            func.sum(LLMUsageHourly.success_count).label("success_count"),
        ).where(and_(*conditions))

        async with self._pool.session() as session:
            summary_result = await session.execute(summary_stmt)
            summary_row = summary_result.first()

        total_calls = summary_row.total_calls or 0
        success_count = summary_row.success_count or 0

        return {
            "total_calls": total_calls,
            "total_input_tokens": summary_row.total_input_tokens or 0,
            "total_output_tokens": summary_row.total_output_tokens or 0,
            "total_tokens": summary_row.total_tokens or 0,
            "avg_latency_ms": float(summary_row.avg_latency_ms or 0),
            "max_latency_ms": float(summary_row.max_latency_ms or 0),
            "min_latency_ms": float(summary_row.min_latency_ms or 0),
            "success_rate": success_count / total_calls if total_calls > 0 else 1.0,
            "error_types": {},
        }

    async def get_summary_stats(
        self,
        start_time: datetime,
        end_time: datetime,
        group_by: str = "label",
    ) -> list[dict[str, Any]]:
        """Query aggregated summary statistics grouped by specified dimension.

        Args:
            start_time: Start of the time range.
            end_time: End of the time range.
            group_by: Dimension to group by (label, call_point, provider, model).

        Returns:
            List of summary stat dictionaries.
        """
        group_column = {
            "label": LLMUsageHourly.label,
            "call_point": LLMUsageHourly.call_point,
            "provider": LLMUsageHourly.provider,
            "model": LLMUsageHourly.model,
        }.get(group_by, LLMUsageHourly.label)

        stmt = (
            select(
                group_column.label("group_key"),
                func.sum(LLMUsageHourly.call_count).label("total_calls"),
                func.sum(LLMUsageHourly.input_tokens_sum).label("total_input_tokens"),
                func.sum(LLMUsageHourly.output_tokens_sum).label("total_output_tokens"),
                func.sum(LLMUsageHourly.total_tokens_sum).label("total_tokens"),
                case(
                    (
                        func.sum(LLMUsageHourly.call_count) > 0,
                        func.sum(LLMUsageHourly.latency_avg_ms * LLMUsageHourly.call_count)
                        / func.sum(LLMUsageHourly.call_count),
                    ),
                    else_=0.0,
                ).label("avg_latency_ms"),
                func.sum(LLMUsageHourly.success_count).label("total_success"),
                func.sum(LLMUsageHourly.failure_count).label("total_failure"),
            )
            .where(
                LLMUsageHourly.time_bucket >= start_time,
                LLMUsageHourly.time_bucket < end_time,
            )
            .group_by(group_column)
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "group": row.group_key,
                "total_calls": row.total_calls or 0,
                "total_input_tokens": row.total_input_tokens or 0,
                "total_output_tokens": row.total_output_tokens or 0,
                "total_tokens": row.total_tokens or 0,
                "avg_latency_ms": float(row.avg_latency_ms) if row.avg_latency_ms else 0.0,
                "total_success": row.total_success or 0,
                "total_failure": row.total_failure or 0,
            }
            for row in rows
        ]

    async def get_by_provider(
        self,
        start_time: datetime,
        end_time: datetime,
        llm_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get usage statistics grouped by provider.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            llm_type: Filter by LLM type.

        Returns:
            List of provider statistics.
        """
        conditions = [
            LLMUsageHourly.time_bucket >= start_time,
            LLMUsageHourly.time_bucket <= end_time,
        ]
        if llm_type:
            conditions.append(LLMUsageHourly.llm_type == llm_type)

        stmt = (
            select(
                LLMUsageHourly.provider,
                func.sum(LLMUsageHourly.call_count).label("call_count"),
                func.sum(LLMUsageHourly.input_tokens_sum).label("input_tokens"),
                func.sum(LLMUsageHourly.output_tokens_sum).label("output_tokens"),
                func.sum(LLMUsageHourly.total_tokens_sum).label("total_tokens"),
                case(
                    (
                        func.sum(LLMUsageHourly.call_count) > 0,
                        func.sum(LLMUsageHourly.latency_avg_ms * LLMUsageHourly.call_count)
                        / func.sum(LLMUsageHourly.call_count),
                    ),
                    else_=0.0,
                ).label("avg_latency_ms"),
                func.sum(LLMUsageHourly.success_count).label("success_count"),
            )
            .where(and_(*conditions))
            .group_by(LLMUsageHourly.provider)
            .order_by(func.sum(LLMUsageHourly.total_tokens_sum).desc())
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "provider": row.provider,
                "call_count": row.call_count or 0,
                "input_tokens": row.input_tokens or 0,
                "output_tokens": row.output_tokens or 0,
                "total_tokens": row.total_tokens or 0,
                "avg_latency_ms": float(row.avg_latency_ms or 0),
                "success_rate": (row.success_count or 0) / (row.call_count or 1),
            }
            for row in rows
        ]

    async def get_by_model(
        self,
        start_time: datetime,
        end_time: datetime,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get usage statistics grouped by model.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            provider: Filter by provider name.

        Returns:
            List of model statistics.
        """
        conditions = [
            LLMUsageHourly.time_bucket >= start_time,
            LLMUsageHourly.time_bucket <= end_time,
        ]
        if provider:
            conditions.append(LLMUsageHourly.provider == provider)

        stmt = (
            select(
                LLMUsageHourly.model,
                LLMUsageHourly.provider,
                func.sum(LLMUsageHourly.call_count).label("call_count"),
                func.sum(LLMUsageHourly.input_tokens_sum).label("input_tokens"),
                func.sum(LLMUsageHourly.output_tokens_sum).label("output_tokens"),
                func.sum(LLMUsageHourly.total_tokens_sum).label("total_tokens"),
                case(
                    (
                        func.sum(LLMUsageHourly.call_count) > 0,
                        func.sum(LLMUsageHourly.latency_avg_ms * LLMUsageHourly.call_count)
                        / func.sum(LLMUsageHourly.call_count),
                    ),
                    else_=0.0,
                ).label("avg_latency_ms"),
                func.sum(LLMUsageHourly.success_count).label("success_count"),
            )
            .where(and_(*conditions))
            .group_by(LLMUsageHourly.model, LLMUsageHourly.provider)
            .order_by(func.sum(LLMUsageHourly.total_tokens_sum).desc())
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "model": row.model,
                "provider": row.provider,
                "call_count": row.call_count or 0,
                "input_tokens": row.input_tokens or 0,
                "output_tokens": row.output_tokens or 0,
                "total_tokens": row.total_tokens or 0,
                "avg_latency_ms": float(row.avg_latency_ms or 0),
                "success_rate": (row.success_count or 0) / (row.call_count or 1),
            }
            for row in rows
        ]

    async def get_by_call_point(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Get usage statistics grouped by call point.

        Args:
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            List of call point statistics.
        """
        stmt = (
            select(
                LLMUsageHourly.call_point,
                func.sum(LLMUsageHourly.call_count).label("call_count"),
                func.sum(LLMUsageHourly.total_tokens_sum).label("total_tokens"),
                case(
                    (
                        func.sum(LLMUsageHourly.call_count) > 0,
                        func.sum(LLMUsageHourly.latency_avg_ms * LLMUsageHourly.call_count)
                        / func.sum(LLMUsageHourly.call_count),
                    ),
                    else_=0.0,
                ).label("avg_latency_ms"),
                func.sum(LLMUsageHourly.success_count).label("success_count"),
            )
            .where(
                and_(
                    LLMUsageHourly.time_bucket >= start_time,
                    LLMUsageHourly.time_bucket <= end_time,
                )
            )
            .group_by(LLMUsageHourly.call_point)
            .order_by(func.sum(LLMUsageHourly.total_tokens_sum).desc())
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "call_point": row.call_point,
                "call_count": row.call_count or 0,
                "total_tokens": row.total_tokens or 0,
                "avg_latency_ms": float(row.avg_latency_ms or 0),
                "success_rate": (row.success_count or 0) / (row.call_count or 1),
            }
            for row in rows
        ]

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
            result = await session.execute(
                delete(LLMUsageRaw).where(LLMUsageRaw.created_at < cutoff)
            )
            await session.commit()
            removed = result.rowcount

        log.info("llm_usage_raw_cleanup_done", days=days, removed=removed)
        return removed
