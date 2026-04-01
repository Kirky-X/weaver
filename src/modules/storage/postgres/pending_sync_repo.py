# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pending sync repository for tracking Neo4j sync operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, select, update

from core.db.models import PendingSync
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger

log = get_logger("pending_sync_repo")


class PendingSyncRepo:
    """Repository for pending Neo4j sync operations.

    Args:
        pool: PostgreSQL connection pool.
    """

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def upsert(self, article_id: uuid.UUID, sync_type: str, payload: dict[str, Any]) -> int:
        """Create or update a pending sync record.

        Args:
            article_id: The article UUID.
            sync_type: Type of sync (e.g., 'neo4j').
            payload: JSONB payload containing state to sync.

        Returns:
            The pending_sync record ID.
        """
        async with self._pool.session() as session:
            # Check if exists
            result = await session.execute(
                select(PendingSync).where(
                    and_(
                        PendingSync.article_id == article_id,
                        PendingSync.sync_type == sync_type,
                        PendingSync.status == "pending",
                    )
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing record
                existing.payload = payload
                existing.retry_count = 0
                existing.error = None
                await session.commit()
                return existing.id
            else:
                # Create new record
                record = PendingSync(
                    article_id=article_id,
                    sync_type=sync_type,
                    payload=payload,
                    status="pending",
                )
                session.add(record)
                await session.commit()
                return record.id

    async def get_pending(self, limit: int = 100) -> list[PendingSync]:
        """Get pending sync records ordered by creation time.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of pending sync records.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(PendingSync)
                .where(PendingSync.status == "pending")
                .order_by(PendingSync.created_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def mark_synced(self, id: int) -> None:
        """Mark a sync record as successfully synced.

        Args:
            id: The pending_sync record ID.
        """
        async with self._pool.session() as session:
            await session.execute(
                update(PendingSync)
                .where(PendingSync.id == id)
                .values(status="synced", synced_at=datetime.now(UTC))
            )
            await session.commit()

    async def mark_failed(self, id: int, error: str) -> None:
        """Mark a sync record as failed and increment retry count.

        Args:
            id: The pending_sync record ID.
            error: Error message describing the failure.
        """
        async with self._pool.session() as session:
            result = await session.execute(select(PendingSync).where(PendingSync.id == id))
            record = result.scalar_one_or_none()
            if record:
                record.status = "failed"
                record.error = error
                record.retry_count = record.retry_count + 1
                await session.commit()

    async def cleanup_old_synced(self, days: int = 7) -> int:
        """Delete synced records older than the specified number of days.

        Args:
            days: Number of days to retain synced records. Defaults to 7.

        Returns:
            Number of rows deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.session() as session:
            result = await session.execute(
                delete(PendingSync).where(
                    and_(
                        PendingSync.status == "synced",
                        PendingSync.synced_at < cutoff,
                    )
                )
            )
            await session.commit()
            removed = result.rowcount

        log.info("pending_sync_cleanup_done", days=days, removed=removed)
        return removed

    async def get_stale_pending(self, hours: int = 1) -> list[PendingSync]:
        """Get pending records older than specified hours (for consistency checking).

        Args:
            hours: Number of hours after which a pending record is considered stale.

        Returns:
            List of stale pending records.
        """
        threshold = datetime.now(UTC) - timedelta(hours=hours)
        async with self._pool.session() as session:
            result = await session.execute(
                select(PendingSync).where(
                    and_(
                        PendingSync.status == "pending",
                        PendingSync.created_at < threshold,
                    )
                )
            )
            return list(result.scalars().all())

    def reconstruct_state_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Reconstruct pipeline state from JSONB payload.

        Args:
            payload: The JSONB payload from pending_sync record.

        Returns:
            A dict that can be passed to neo4j_writer.write().
        """
        state: dict[str, Any] = {}

        if "article_id" in payload:
            state["article_id"] = payload["article_id"]

        if "raw" in payload:
            state["raw"] = payload["raw"]

        if "cleaned" in payload:
            state["cleaned"] = payload["cleaned"]

        if "category" in payload:
            state["category"] = payload["category"]

        if "score" in payload:
            state["score"] = payload["score"]

        if "entities" in payload:
            state["entities"] = payload["entities"]

        if "relations" in payload:
            state["relations"] = payload["relations"]

        if "merged_source_ids" in payload:
            state["merged_source_ids"] = payload["merged_source_ids"]

        if "summary_info" in payload:
            state["summary_info"] = payload["summary_info"]

        if "sentiment" in payload:
            state["sentiment"] = payload["sentiment"]

        if "credibility" in payload:
            state["credibility"] = payload["credibility"]

        if "prompt_versions" in payload:
            state["prompt_versions"] = payload["prompt_versions"]

        if "is_merged" in payload:
            state["is_merged"] = payload["is_merged"]

        return state

    async def get_by_article_id(self, article_id: uuid.UUID) -> PendingSync | None:
        """Get pending sync record by article ID.

        Args:
            article_id: The article UUID.

        Returns:
            The pending sync record or None if not found.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(PendingSync).where(
                    and_(
                        PendingSync.article_id == article_id,
                        PendingSync.status == "pending",
                    )
                )
            )
            return result.scalar_one_or_none()
