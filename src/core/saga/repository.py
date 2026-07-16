# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Saga log repository for persisting and querying saga execution logs.

Implements:
    - SagaLogRepo: Repository for saga_logs table CRUD operations
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update

from core.db.models import SagaLog
from core.observability import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)

# Default retention period for saga log archival
DEFAULT_RETENTION_DAYS = 30


class SagaLogRepo:
    """Repository for saga execution log persistence.

    Provides CRUD operations, batch writes, and log archival for
    the saga_logs table.

    Args:
        pool: Relational database connection pool.
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def create(
        self,
        saga_id: uuid.UUID,
        article_id: uuid.UUID,
        step_name: str,
        step_status: str,
        compensation_data: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        """Create a new saga log entry.

        Args:
            saga_id: ID of the saga.
            article_id: ID of the article being processed.
            step_name: Name of the saga step.
            step_status: Status of the step (e.g., 'started', 'completed', 'failed').
            compensation_data: Optional compensation command data for rollback.

        Returns:
            UUID of the created log entry.
        """
        log_id = uuid.uuid4()
        now = datetime.now(UTC)

        async with self._pool.session() as session:
            entry = SagaLog(
                id=log_id,
                saga_id=saga_id,
                article_id=article_id,
                step_name=step_name,
                step_status=step_status,
                started_at=now,
                compensation_data=compensation_data,
            )
            session.add(entry)
            await session.commit()

        log.debug(
            "saga_log_created",
            log_id=str(log_id),
            saga_id=str(saga_id),
            step_name=step_name,
            step_status=step_status,
        )
        return log_id

    async def update_status(
        self,
        log_id: uuid.UUID,
        step_status: str,
        error_message: str | None = None,
    ) -> None:
        """Update the status of a saga log entry.

        Args:
            log_id: ID of the log entry to update.
            step_status: New status value.
            error_message: Optional error message for failed steps.
        """
        now = datetime.now(UTC)

        async with self._pool.session() as session:
            values: dict[str, Any] = {
                "step_status": step_status,
                "completed_at": now,
            }
            if error_message is not None:
                values["error_message"] = error_message

            await session.execute(update(SagaLog).where(SagaLog.id == log_id).values(**values))
            await session.commit()

    async def increment_retry(self, log_id: uuid.UUID) -> None:
        """Increment the retry count for a saga log entry.

        Args:
            log_id: ID of the log entry.
        """
        async with self._pool.session() as session:
            await session.execute(
                update(SagaLog)
                .where(SagaLog.id == log_id)
                .values(retry_count=SagaLog.retry_count + 1)
            )
            await session.commit()

    async def get_by_saga_id(self, saga_id: uuid.UUID) -> list[SagaLog]:
        """Get all log entries for a saga, ordered by creation time.

        Args:
            saga_id: ID of the saga.

        Returns:
            List of SagaLog entries ordered by started_at.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SagaLog).where(SagaLog.saga_id == saga_id).order_by(SagaLog.started_at)
            )
            return list(result.scalars().all())

    async def get_by_article_id(self, article_id: uuid.UUID) -> list[SagaLog]:
        """Get all saga log entries for an article.

        Args:
            article_id: ID of the article.

        Returns:
            List of SagaLog entries.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SagaLog)
                .where(SagaLog.article_id == article_id)
                .order_by(SagaLog.started_at.desc())
            )
            return list(result.scalars().all())

    async def get_failed_logs(self, limit: int = 50) -> list[SagaLog]:
        """Get saga log entries with failed status.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of failed SagaLog entries.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SagaLog)
                .where(SagaLog.step_status == "failed")
                .order_by(SagaLog.started_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def batch_create(self, entries: list[dict[str, Any]]) -> None:
        """Batch create multiple saga log entries.

        Args:
            entries: List of dicts with saga log fields.
        """
        if not entries:
            return

        async with self._pool.session() as session:
            for entry_data in entries:
                entry = SagaLog(**entry_data)
                session.add(entry)
            await session.commit()

        log.debug("saga_log_batch_created", count=len(entries))

    async def archive_old_logs(self, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
        """Archive saga logs older than retention period.

        Deletes logs older than the specified retention period.
        In a production system, this would move logs to cold storage
        before deletion.

        Args:
            retention_days: Number of days to retain logs (default 30).

        Returns:
            Number of archived (deleted) log entries.
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        async with self._pool.session() as session:
            result = await session.execute(delete(SagaLog).where(SagaLog.created_at < cutoff))
            await session.commit()
            deleted_count = result.rowcount

        log.info(
            "saga_logs_archived",
            deleted_count=deleted_count,
            retention_days=retention_days,
        )
        return deleted_count

    async def get_completed_compensation_data(self, saga_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get compensation data for all completed steps in a saga.

        Used by CompensationExecutor to determine which compensations
        to execute in reverse order.

        Args:
            saga_id: ID of the saga.

        Returns:
            List of compensation_data dicts for completed steps,
            ordered by started_at (will be reversed by executor).
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(SagaLog.compensation_data)
                .where(
                    SagaLog.saga_id == saga_id,
                    SagaLog.step_status == "completed",
                    SagaLog.compensation_data.isnot(None),
                )
                .order_by(SagaLog.started_at)
            )
            rows = result.scalars().all()
            return [row for row in rows if row is not None]
