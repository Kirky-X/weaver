# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM usage statistics repository for raw records and hourly aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.types import Integer

from core.db.models import LLMUsageHourly, LLMUsageRaw
from core.event.bus import LLMUsageEvent
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.db.postgres import PostgresPool

log = get_logger("llm_usage_repo")


class LLMUsageRepo:
    """Repository for LLM usage statistics.

    Provides methods for:
    - Inserting raw usage records
    - Querying latency bounds for aggregation
    - Upserting hourly aggregated records
    - Querying aggregated statistics
    - Cleaning up old raw records

    Args:
        pool: PostgreSQL connection pool.
    """

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    # ── Raw Record Operations ─────────────────────────────────────

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
                )
            )
            await session.commit()

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

    async def query_raw(
        self,
        start_time: datetime,
        end_time: datetime,
        provider: str | None = None,
        model: str | None = None,
        llm_type: str | None = None,
        call_point: str | None = None,
        success: bool | None = None,
        limit: int = 1000,
    ) -> list[LLMUsageRaw]:
        """Query raw usage records with filters.

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            provider: Filter by provider name.
            model: Filter by model name.
            llm_type: Filter by LLM type (chat/embedding/rerank).
            call_point: Filter by call point.
            success: Filter by success status.
            limit: Maximum records to return (default 1000, max 10000).

        Returns:
            List of matching LLMUsageRaw records.
        """
        limit = min(limit, 10000)

        stmt = (
            select(LLMUsageRaw)
            .where(
                and_(
                    LLMUsageRaw.created_at >= start_time,
                    LLMUsageRaw.created_at <= end_time,
                )
            )
            .order_by(LLMUsageRaw.created_at.desc())
            .limit(limit)
        )

        if provider:
            stmt = stmt.where(LLMUsageRaw.provider == provider)
        if model:
            stmt = stmt.where(LLMUsageRaw.model == model)
        if llm_type:
            stmt = stmt.where(LLMUsageRaw.llm_type == llm_type)
        if call_point:
            stmt = stmt.where(LLMUsageRaw.call_point == call_point)
        if success is not None:
            stmt = stmt.where(LLMUsageRaw.success == success)

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Aggregation Operations ────────────────────────────────────

    async def get_latency_bounds(
        self,
        time_bucket: datetime,
        label: str,
        call_point: str,
    ) -> tuple[float, float]:
        """Query min/max latency from raw records for a specific hour/label/call_point.

        Args:
            time_bucket: The hour bucket (e.g., 2024-01-15 10:00:00).
            label: The label to filter by.
            call_point: The call point to filter by.

        Returns:
            Tuple of (min_latency, max_latency). Returns (0.0, 0.0) if no records.
        """
        # Calculate hour range
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
    ) -> None:
        """Upsert an hourly aggregated record.

        Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE for idempotency.

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
            latency_sum: Sum of latency (for avg calculation).
            latency_min: Minimum latency.
            latency_max: Maximum latency.
            success_count: Count of successful calls.
            failure_count: Count of failed calls.
        """
        latency_avg = latency_sum / call_count if call_count > 0 else 0.0

        async with self._pool.session() as session:
            stmt = insert(LLMUsageHourly).values(
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
                latency_avg_ms=latency_avg,
                latency_min_ms=latency_min,
                latency_max_ms=latency_max,
                success_count=success_count,
                failure_count=failure_count,
            )

            # ON CONFLICT DO UPDATE
            stmt = stmt.on_conflict_do_update(
                constraint="uq_llm_usage_hourly",
                set_={
                    "call_count": call_count,
                    "input_tokens_sum": input_tokens_sum,
                    "output_tokens_sum": output_tokens_sum,
                    "total_tokens_sum": total_tokens_sum,
                    "latency_avg_ms": latency_avg,
                    "latency_min_ms": latency_min,
                    "latency_max_ms": latency_max,
                    "success_count": success_count,
                    "failure_count": failure_count,
                },
            )

            await session.execute(stmt)
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

        Args:
            start_time: Start of time range.
            end_time: End of time range.
            granularity: Time granularity - "hourly", "daily", or "monthly".
            provider: Filter by provider name.
            model: Filter by model name.
            llm_type: Filter by LLM type.
            call_point: Filter by call point.

        Returns:
            List of aggregated usage records with:
            - time_bucket: ISO timestamp
            - call_count: Total calls
            - input_tokens_sum: Total input tokens
            - output_tokens_sum: Total output tokens
            - total_tokens_sum: Total tokens
            - latency_avg_ms: Average latency
            - success_count: Successful calls
            - failure_count: Failed calls
        """
        # Build time truncation expression based on granularity
        if granularity == "daily":
            date_trunc = func.date_trunc("day", LLMUsageHourly.time_bucket)
        elif granularity == "monthly":
            date_trunc = func.date_trunc("month", LLMUsageHourly.time_bucket)
        else:  # hourly (default)
            date_trunc = func.date_trunc("hour", LLMUsageHourly.time_bucket)

        # Build query
        stmt = (
            select(
                date_trunc.label("time_bucket"),
                func.sum(LLMUsageHourly.call_count).label("call_count"),
                func.sum(LLMUsageHourly.input_tokens_sum).label("input_tokens_sum"),
                func.sum(LLMUsageHourly.output_tokens_sum).label("output_tokens_sum"),
                func.sum(LLMUsageHourly.total_tokens_sum).label("total_tokens_sum"),
                func.avg(LLMUsageHourly.latency_avg_ms).label("latency_avg_ms"),
                func.min(LLMUsageHourly.latency_min_ms).label("latency_min_ms"),
                func.max(LLMUsageHourly.latency_max_ms).label("latency_max_ms"),
                func.sum(LLMUsageHourly.success_count).label("success_count"),
                func.sum(LLMUsageHourly.failure_count).label("failure_count"),
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
            Summary dictionary with:
            - total_calls: Total number of calls
            - total_input_tokens: Total input tokens
            - total_output_tokens: Total output tokens
            - total_tokens: Total tokens
            - avg_latency_ms: Average latency
            - max_latency_ms: Maximum latency
            - min_latency_ms: Minimum latency
            - success_rate: Success rate (0.0 to 1.0)
            - error_types: Dict of error type -> count
        """
        # Build base query conditions
        conditions = [
            LLMUsageRaw.created_at >= start_time,
            LLMUsageRaw.created_at <= end_time,
        ]
        if provider:
            conditions.append(LLMUsageRaw.provider == provider)
        if model:
            conditions.append(LLMUsageRaw.model == model)
        if llm_type:
            conditions.append(LLMUsageRaw.llm_type == llm_type)
        if call_point:
            conditions.append(LLMUsageRaw.call_point == call_point)

        # Main summary query
        summary_stmt = select(
            func.count().label("total_calls"),
            func.sum(LLMUsageRaw.input_tokens).label("total_input_tokens"),
            func.sum(LLMUsageRaw.output_tokens).label("total_output_tokens"),
            func.sum(LLMUsageRaw.total_tokens).label("total_tokens"),
            func.avg(LLMUsageRaw.latency_ms).label("avg_latency_ms"),
            func.max(LLMUsageRaw.latency_ms).label("max_latency_ms"),
            func.min(LLMUsageRaw.latency_ms).label("min_latency_ms"),
            func.sum(cast(LLMUsageRaw.success, Integer)).label("success_count"),
        ).where(and_(*conditions))

        # Error type breakdown
        error_stmt = (
            select(
                LLMUsageRaw.error_type,
                func.count().label("count"),
            )
            .where(and_(*conditions, LLMUsageRaw.success == False))  # noqa: E712
            .group_by(LLMUsageRaw.error_type)
        )

        async with self._pool.session() as session:
            summary_result = await session.execute(summary_stmt)
            summary_row = summary_result.first()

            error_result = await session.execute(error_stmt)
            error_rows = error_result.all()

        total_calls = summary_row.total_calls or 0
        success_count = summary_row.success_count or 0

        error_types = {row.error_type or "unknown": row.count for row in error_rows}

        return {
            "total_calls": total_calls,
            "total_input_tokens": summary_row.total_input_tokens or 0,
            "total_output_tokens": summary_row.total_output_tokens or 0,
            "total_tokens": summary_row.total_tokens or 0,
            "avg_latency_ms": float(summary_row.avg_latency_ms or 0),
            "max_latency_ms": float(summary_row.max_latency_ms or 0),
            "min_latency_ms": float(summary_row.min_latency_ms or 0),
            "success_rate": success_count / total_calls if total_calls > 0 else 1.0,
            "error_types": error_types,
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
                func.avg(LLMUsageHourly.latency_avg_ms).label("avg_latency_ms"),
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
            List of provider statistics with:
            - provider: Provider name
            - call_count: Total calls
            - total_tokens: Total tokens
            - avg_latency_ms: Average latency
            - success_rate: Success rate
        """
        conditions = [
            LLMUsageRaw.created_at >= start_time,
            LLMUsageRaw.created_at <= end_time,
        ]
        if llm_type:
            conditions.append(LLMUsageRaw.llm_type == llm_type)

        stmt = (
            select(
                LLMUsageRaw.provider,
                func.count().label("call_count"),
                func.sum(LLMUsageRaw.total_tokens).label("total_tokens"),
                func.avg(LLMUsageRaw.latency_ms).label("avg_latency_ms"),
                func.sum(cast(LLMUsageRaw.success, Integer)).label("success_count"),
            )
            .where(and_(*conditions))
            .group_by(LLMUsageRaw.provider)
            .order_by(func.sum(LLMUsageRaw.total_tokens).desc())
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "provider": row.provider,
                "call_count": row.call_count or 0,
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
            List of model statistics with:
            - model: Model name
            - provider: Provider name
            - call_count: Total calls
            - total_tokens: Total tokens
            - avg_latency_ms: Average latency
            - success_rate: Success rate
        """
        conditions = [
            LLMUsageRaw.created_at >= start_time,
            LLMUsageRaw.created_at <= end_time,
        ]
        if provider:
            conditions.append(LLMUsageRaw.provider == provider)

        stmt = (
            select(
                LLMUsageRaw.model,
                LLMUsageRaw.provider,
                func.count().label("call_count"),
                func.sum(LLMUsageRaw.total_tokens).label("total_tokens"),
                func.avg(LLMUsageRaw.latency_ms).label("avg_latency_ms"),
                func.sum(cast(LLMUsageRaw.success, Integer)).label("success_count"),
            )
            .where(and_(*conditions))
            .group_by(LLMUsageRaw.model, LLMUsageRaw.provider)
            .order_by(func.sum(LLMUsageRaw.total_tokens).desc())
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "model": row.model,
                "provider": row.provider,
                "call_count": row.call_count or 0,
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
                LLMUsageRaw.call_point,
                func.count().label("call_count"),
                func.sum(LLMUsageRaw.total_tokens).label("total_tokens"),
                func.avg(LLMUsageRaw.latency_ms).label("avg_latency_ms"),
                func.sum(cast(LLMUsageRaw.success, Integer)).label("success_count"),
            )
            .where(
                and_(
                    LLMUsageRaw.created_at >= start_time,
                    LLMUsageRaw.created_at <= end_time,
                )
            )
            .group_by(LLMUsageRaw.call_point)
            .order_by(func.sum(LLMUsageRaw.total_tokens).desc())
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
            days: Number of days to retain. Defaults to 2 (48h).

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

    async def cleanup_hourly_older_than(self, days: int = 365) -> int:
        """Delete hourly aggregated records older than the specified number of days.

        Args:
            days: Number of days to retain. Defaults to 365 (1 year).

        Returns:
            Number of rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.session() as session:
            result = await session.execute(
                delete(LLMUsageHourly).where(LLMUsageHourly.time_bucket < cutoff)
            )
            await session.commit()
            removed = result.rowcount

        log.info("llm_usage_hourly_cleanup_done", days=days, removed=removed)
        return removed
