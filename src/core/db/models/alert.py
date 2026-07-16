# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Alert SQLAlchemy ORM models.

Defines alert rules for entity monitoring and the events triggered by
those rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.models.base import Base, JSONCompatible


class AlertRule(Base):
    """Alert rules for entity monitoring.

    Implements: Weaver-数据库设计文档 §12.4
    """

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    operator: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(50), nullable=False, default="webhook", server_default=text("'webhook'")
    )
    cooldown_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    # Relationships
    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "metric IN ('reference_count', 'sentiment_change', 'volume_spike')",
            name="chk_alert_metric_values",
        ),
        CheckConstraint(
            "operator IN ('z_score>', 'pct_change>', 'absolute>')",
            name="chk_alert_operator_values",
        ),
    )


class AlertEvent(Base):
    """Alert events triggered by rules.

    Implements: Weaver-数据库设计文档 §12.4
    """

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("alert_rules.id"), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONCompatible)

    # Relationships
    rule: Mapped[AlertRule] = relationship(back_populates="events")

    __table_args__ = (
        Index("idx_alert_events_triggered", triggered_at.desc()),
        Index("idx_alert_events_entity", "entity_name", triggered_at.desc()),
    )
