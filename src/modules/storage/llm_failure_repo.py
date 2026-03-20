# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM failure record repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from core.db.models import LLMFailure
from core.db.postgres import PostgresPool
from core.event.bus import LLMFailureEvent
from core.observability.logging import get_logger

log = get_logger("llm_failure_repo")


class LLMFailureRepo:
    """Repository for LLM failure records.

    Args:
        pool: PostgreSQL connection pool.
    """

    def __init__(self, pool: PostgresPool) -> None:
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
