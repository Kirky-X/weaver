# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Audit log service for writing security events to database.

Implements: Weaver-数据库设计文档 §12.3
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.db import AuditLog
from core.observability import get_logger
from core.protocols import RelationalPool

log = get_logger(__name__)


class AuditLogService:
    """Service for persisting audit log events to the database.

    Implements: Weaver-数据库设计文档 §12.3
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def log_event(
        self,
        key_id: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Write an audit event to the database.

        Args:
            key_id: API key identifier of the caller.
            action: Action performed (e.g., 'source.create', 'pipeline.trigger').
            target_type: Type of resource affected.
            target_id: ID of the resource affected.
            detail: Additional details as JSONB.
            client_ip: Client IP address.
            user_agent: Client user agent string.
        """
        try:
            entry = AuditLog(
                key_id=key_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail,
                client_ip=client_ip,
                user_agent=user_agent,
            )
            async with self._pool.session() as session:
                session.add(entry)
                await session.commit()
        except Exception as exc:
            # Audit logging must never break the request
            log.error(
                "audit_log_write_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
                key_id=key_id,
                action=action,
            )

    async def query_events(
        self,
        key_id: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query audit log events.

        Args:
            key_id: Filter by API key ID.
            action: Filter by action.
            target_type: Filter by target type.
            limit: Maximum number of events to return.

        Returns:
            List of audit event dicts.
        """
        async with self._pool.session() as session:
            query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)

            if key_id:
                query = query.where(AuditLog.key_id == key_id)
            if action:
                query = query.where(AuditLog.action == action)
            if target_type:
                query = query.where(AuditLog.target_type == target_type)

            result = await session.execute(query)
            events = result.scalars().all()

            return [
                {
                    "id": e.id,
                    "key_id": e.key_id,
                    "action": e.action,
                    "target_type": e.target_type,
                    "target_id": e.target_id,
                    "detail": e.detail,
                    "client_ip": e.client_ip,
                    "user_agent": e.user_agent,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ]
