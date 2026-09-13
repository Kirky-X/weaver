# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Repository for the transactional event outbox (T018).

Implements: OutboxRepository protocol (core/protocols/services.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from core.db.models import EventOutbox
from core.observability import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)

# A row retried this many times is parked as 'dead' for manual inspection
MAX_OUTBOX_RETRIES = 5


class OutboxRepo:
    """CRUD for event_outbox rows (enqueue / fetch / mark outcomes)."""

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def enqueue(
        self,
        event_type: str,
        payload: dict[str, Any],
        article_id: uuid.UUID | str | None = None,
    ) -> int:
        """Persist a new pending event row.

        Args:
            event_type: Event class name (e.g. ``MemoryIngestEvent``).
            payload: JSON-serializable event payload.
            article_id: Optional correlation id.

        Returns:
            The new row id.
        """
        if isinstance(article_id, str):
            article_id = uuid.UUID(article_id)
        async with self._pool.session() as session:
            row = EventOutbox(
                event_type=event_type,
                payload=payload,
                article_id=article_id,
                status="pending",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def fetch_pending(self, limit: int = 100) -> list[EventOutbox]:
        """Fetch pending rows in creation order."""
        async with self._pool.session() as session:
            result = await session.execute(
                select(EventOutbox)
                .where(EventOutbox.status == "pending")
                .order_by(EventOutbox.created_at.asc(), EventOutbox.id.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def mark_dispatched(self, row_id: int) -> None:
        """Mark a row as dispatched."""
        async with self._pool.session() as session:
            await session.execute(
                update(EventOutbox)
                .where(EventOutbox.id == row_id)
                .values(status="dispatched", dispatched_at=datetime.now(UTC))
            )
            await session.commit()

    async def mark_failed(self, row_id: int, error: str) -> str:
        """Record a dispatch failure.

        Increments retry_count; parks the row as 'dead' once retries are
        exhausted (ERROR-level visibility for operators).

        Returns:
            The new status ('pending' or 'dead').
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(EventOutbox).where(EventOutbox.id == row_id)
            )
            row = result.scalars().first()
            if row is None:
                return "missing"
            retry_count = (row.retry_count or 0) + 1
            new_status = "dead" if retry_count >= MAX_OUTBOX_RETRIES else "pending"
            await session.execute(
                update(EventOutbox)
                .where(EventOutbox.id == row_id)
                .values(
                    retry_count=retry_count,
                    status=new_status,
                    last_error=error[:2000],
                )
            )
            await session.commit()
        if new_status == "dead":
            log.error(
                "outbox_event_dead",
                row_id=row_id,
                event_type=row.event_type,
                retries=retry_count,
            )
        return new_status
