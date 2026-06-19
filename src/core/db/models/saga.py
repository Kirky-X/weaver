# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Saga SQLAlchemy ORM models.

Tracks pending cross-database sync records and Saga orchestration log
entries for compensation-based transaction recovery.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.models.base import Base, JSONCompatible


class PendingSync(Base):
    """Pending Neo4j sync records for compensation-based sync."""

    __tablename__ = "pending_sync"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles_core.id", ondelete="CASCADE"),
        nullable=False,
    )
    sync_type: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONCompatible, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_pending_sync_article_id", "article_id"),
        Index("idx_pending_sync_status", "status"),
        Index("idx_pending_sync_created_at", "created_at"),
    )


class SagaLog(Base):
    """Saga execution log entries for compensation transaction tracking.

    Records each step of a Saga orchestration, including execution status,
    compensation data, and error details. Supports fault recovery and
    audit trails for cross-database transactions.
    """

    __tablename__ = "saga_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    saga_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    article_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    step_status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    compensation_data: Mapped[dict[str, Any] | None] = mapped_column(JSONCompatible)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("idx_saga_logs_saga_id", "saga_id"),
        Index("idx_saga_logs_article_id", "article_id"),
        Index("idx_saga_logs_step_status", "step_status"),
    )
