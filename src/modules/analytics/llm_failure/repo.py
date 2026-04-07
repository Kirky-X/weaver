# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM failure record repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete

from core.db.models import LLMFailure
from core.event.bus import LLMFailureEvent
from core.observability.logging import get_logger
from core.protocols import RelationalPool

log = get_logger("llm_failure_repo")


class LLMFailureRepo:
    """Repository for LLM failure records.

    Implements: EntityRepository (partial)

    Args:
        pool: Relational database connection pool.
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def record(self, event: LLMFailureEvent) -> None:
        """Insert a single LLM failure record.

        Args:
            event: The LLM failure event to persist.
        """
        article_uuid: uuid.UUID | None = None
        if event.article_id:
            try:
                article_uuid = uuid.UUID(event.article_id)
            except ValueError:
                pass

        async with self._pool.session() as session:
            session.add(
                LLMFailure(
                    call_point=event.call_point,
                    provider=event.provider,
                    error_type=event.error_type,
                    error_detail=event.error_detail,
                    latency_ms=event.latency_ms,
                    article_id=article_uuid,
                    task_id=event.task_id,
                    attempt=event.attempt,
                    fallback_tried=event.fallback_tried,
                )
            )
            await session.commit()

        log.info(
            "llm_failure_recorded",
            call_point=event.call_point,
            provider=event.provider,
            error_type=event.error_type,
        )

    async def query(
        self,
        call_point: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[LLMFailure]:
        """Query LLM failure records with optional filters.

        Args:
            call_point: Filter by call point (e.g., 'classifier', 'analyzer').
            status: Filter by status (e.g., 'pending', 'retried', 'ignored').
            since: Only return records after this timestamp.
            limit: Maximum number of records to return (default 50, max 200).

        Returns:
            List of matching LLM failure records.
        """
        from sqlalchemy import select

        limit = min(limit, 200)

        stmt = select(LLMFailure).order_by(LLMFailure.created_at.desc()).limit(limit)

        if call_point:
            stmt = stmt.where(LLMFailure.call_point == call_point)
        if status:
            stmt = stmt.where(LLMFailure.error_type == status)
        if since:
            stmt = stmt.where(LLMFailure.created_at >= since)

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_stats(self, since: datetime | None = None) -> dict[str, Any]:
        """Get statistics summary of LLM failures.

        Args:
            since: Only count records after this timestamp.

        Returns:
            Statistics dictionary with counts by call_point and error_type.
        """
        from sqlalchemy import func, select

        stmt = select(
            LLMFailure.call_point,
            LLMFailure.error_type,
            func.count().label("count"),
        )

        if since:
            stmt = stmt.where(LLMFailure.created_at >= since)

        stmt = stmt.group_by(LLMFailure.call_point, LLMFailure.error_type)

        async with self._pool.session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        total = sum(r.count for r in rows)
        by_call_point: dict[str, int] = {}
        by_error_type: dict[str, int] = {}

        for row in rows:
            by_call_point[row.call_point] = by_call_point.get(row.call_point, 0) + row.count
            by_error_type[row.error_type] = by_error_type.get(row.error_type, 0) + row.count

        # Get last failure timestamp
        last_failure_at: str | None = None
        last_stmt = select(LLMFailure.created_at).order_by(LLMFailure.created_at.desc()).limit(1)
        if since:
            last_stmt = last_stmt.where(LLMFailure.created_at >= since)

        async with self._pool.session() as session:
            last_result = await session.execute(last_stmt)
            last_row = last_result.first()
            if last_row and last_row[0]:
                last_failure_at = last_row[0].isoformat()

        return {
            "total": total,
            "by_call_point": by_call_point,
            "by_error_type": by_error_type,
            "last_failure_at": last_failure_at,
        }

    async def cleanup_older_than(self, days: int = 3) -> int:
        """Delete failure records older than the specified number of days.

        Args:
            days: Number of days to retain. Defaults to 3.

        Returns:
            Number of rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.session() as session:
            result = await session.execute(delete(LLMFailure).where(LLMFailure.created_at < cutoff))
            await session.commit()
            removed = result.rowcount

        log.info("llm_failure_cleanup_done", days=days, removed=removed)
        return removed
