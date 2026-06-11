# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Repository for LLM comparison statistics aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from core.db import LLMCompareHourly
from core.event import LLMCompareEvent
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)


class EvalCompareRepo:
    """Repository for LLM comparison statistics.

    Provides methods for:
    - Inserting raw comparison events
    - Upserting hourly aggregated comparison records
    - Querying aggregated comparison statistics
    - Cleaning up old comparison records
    """

    def __init__(self, pool: RelationalPool) -> None:
        """Initialize the repository.

        Args:
            pool: Relational database connection pool.
        """
        self._pool = pool

    async def insert_raw(self, event: LLMCompareEvent) -> None:
        """Insert a single comparison event.

        Args:
            event: The LLM comparison event to persist.
        """
        async with self._pool.session() as session:
            session.add(
                LLMCompareHourly(
                    time_bucket=event.timestamp.replace(minute=0, second=0, microsecond=0),
                    call_point=event.call_point,
                    primary_model=event.primary_model,
                    candidate_model=event.candidate_model,
                    comparison_count=1,
                    primary_latency_sum=event.primary_latency,
                    candidate_latency_sum=event.candidate_latency,
                    primary_success_count=1 if event.primary_success else 0,
                    candidate_success_count=1 if event.candidate_success else 0,
                )
            )
            await session.commit()

    async def upsert_hourly(
        self,
        time_bucket: datetime,
        call_point: str,
        primary_model: str,
        candidate_model: str,
        comparison_count: int,
        primary_latency_sum: float,
        candidate_latency_sum: float,
        primary_success_count: int,
        candidate_success_count: int,
    ) -> None:
        """Upsert an hourly aggregated comparison record.

        Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE for idempotency.

        Args:
            time_bucket: The hour bucket.
            call_point: The call point.
            primary_model: Primary model label.
            candidate_model: Candidate model label.
            comparison_count: Total comparison count.
            primary_latency_sum: Sum of primary latencies.
            candidate_latency_sum: Sum of candidate latencies.
            primary_success_count: Primary success count.
            candidate_success_count: Candidate success count.
        """
        async with self._pool.session() as session:
            stmt = insert(LLMCompareHourly).values(
                time_bucket=time_bucket,
                call_point=call_point,
                primary_model=primary_model,
                candidate_model=candidate_model,
                comparison_count=comparison_count,
                primary_latency_sum=primary_latency_sum,
                candidate_latency_sum=candidate_latency_sum,
                primary_success_count=primary_success_count,
                candidate_success_count=candidate_success_count,
            )

            stmt = stmt.on_conflict_do_update(
                constraint="uq_llm_compare_hourly",
                set_={
                    "comparison_count": comparison_count,
                    "primary_latency_sum": primary_latency_sum,
                    "candidate_latency_sum": candidate_latency_sum,
                    "primary_success_count": primary_success_count,
                    "candidate_success_count": candidate_success_count,
                },
            )

            await session.execute(stmt)
            await session.commit()

    async def get_comparison_stats(
        self,
        call_point: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Get aggregated comparison statistics.

        Args:
            call_point: The call point to query.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            List of comparison stat dictionaries.
        """
        stmt = (
            select(
                LLMCompareHourly.primary_model,
                LLMCompareHourly.candidate_model,
                func.sum(LLMCompareHourly.comparison_count).label("total_comparisons"),
                func.avg(
                    LLMCompareHourly.primary_latency_sum / LLMCompareHourly.comparison_count
                ).label("avg_primary_latency"),
                func.avg(
                    LLMCompareHourly.candidate_latency_sum / LLMCompareHourly.comparison_count
                ).label("avg_candidate_latency"),
                func.sum(LLMCompareHourly.primary_success_count).label("primary_success_count"),
                func.sum(LLMCompareHourly.candidate_success_count).label("candidate_success_count"),
            )
            .where(
                and_(
                    LLMCompareHourly.call_point == call_point,
                    LLMCompareHourly.time_bucket >= start_time,
                    LLMCompareHourly.time_bucket < end_time,
                )
            )
            .group_by(
                LLMCompareHourly.primary_model,
                LLMCompareHourly.candidate_model,
            )
        )

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "primary_model": row.primary_model,
                "candidate_model": row.candidate_model,
                "total_comparisons": row.total_comparisons or 0,
                "avg_primary_latency": float(row.avg_primary_latency or 0),
                "avg_candidate_latency": float(row.avg_candidate_latency or 0),
                "primary_success_rate": (
                    (row.primary_success_count or 0) / max(1, row.total_comparisons or 1)
                ),
                "candidate_success_rate": (
                    (row.candidate_success_count or 0) / max(1, row.total_comparisons or 1)
                ),
            }
            for row in rows
        ]

    async def cleanup_older_than(self, days: int = 7) -> int:
        """Delete comparison records older than specified days.

        Args:
            days: Number of days to retain.

        Returns:
            Number of rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.session() as session:
            result = await session.execute(
                delete(LLMCompareHourly).where(LLMCompareHourly.time_bucket < cutoff)
            )
            await session.commit()
            removed = result.rowcount

        log.info("llm_compare_cleanup_done", days=days, removed=removed)
        return removed
