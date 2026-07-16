# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LLM-related SQLAlchemy ORM models.

Tracks LLM request failures, raw usage records, hourly aggregations,
and shadow-evaluation comparison statistics.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.models.base import Base


class LLMFailureRecord(Base):
    """LLM request failure record for persistent logging and 3-day rolling cleanup."""

    __tablename__ = "llm_failure_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_point: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float | None] = mapped_column(Numeric(10, 2))
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles_core.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    fallback_tried: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("idx_llm_failure_records_created", "created_at"),
        Index("idx_llm_failure_records_article", "article_id"),
        Index("idx_llm_failure_records_call_point", "call_point"),
        Index("idx_llm_failure_records_provider", "provider"),
    )


class LLMUsageRaw(Base):
    """Raw LLM usage records for detailed tracking and analysis.

    This table stores individual LLM API calls with full context,
    enabling detailed analysis and aggregation.
    """

    __tablename__ = "llm_usage_raw"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    call_point: Mapped[str] = mapped_column(String(100), nullable=False)
    llm_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 8), nullable=False, server_default=text("0.0")
    )
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("ix_llm_usage_raw_created_at", "created_at"),
        Index("ix_llm_usage_raw_label", "label"),
        Index("ix_llm_usage_raw_label_callpoint_created", "label", "call_point", "created_at"),
    )


class LLMUsageHourly(Base):
    """Hourly aggregated LLM usage statistics.

    This table stores pre-aggregated metrics per hour/label/call_point
    for efficient querying and reporting.
    """

    __tablename__ = "llm_usage_hourly"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    time_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    call_point: Mapped[str] = mapped_column(String(100), nullable=False)
    llm_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_tokens_sum: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    reasoning_tokens_sum: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    cost_usd_sum: Mapped[float] = mapped_column(
        Numeric(14, 8), nullable=False, server_default=text("0.0")
    )
    latency_avg_ms: Mapped[float] = mapped_column(Float, nullable=False)
    latency_min_ms: Mapped[float] = mapped_column(Float, nullable=False)
    latency_max_ms: Mapped[float] = mapped_column(Float, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        # Unique constraint for idempotent upsert
        UniqueConstraint("time_bucket", "label", "call_point", name="uq_llm_usage_hourly"),
        Index("ix_llm_usage_hourly_time_bucket", "time_bucket"),
        Index("ix_llm_usage_hourly_provider", "provider"),
        Index("ix_llm_usage_hourly_model", "model"),
    )


class LLMCompareHourly(Base):
    """Hourly aggregated LLM comparison statistics.

    Stores comparison results between primary and candidate models
    for shadow evaluation analysis.
    """

    __tablename__ = "llm_compare_hourly"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    time_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    call_point: Mapped[str] = mapped_column(String(100), nullable=False)
    primary_model: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_model: Mapped[str] = mapped_column(String(100), nullable=False)
    comparison_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    primary_latency_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    candidate_latency_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    primary_success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "time_bucket",
            "call_point",
            "primary_model",
            "candidate_model",
            name="uq_llm_compare_hourly",
        ),
        Index("ix_llm_compare_hourly_time_bucket", "time_bucket"),
        Index("ix_llm_compare_hourly_call_point", "call_point"),
        Index("ix_llm_compare_hourly_primary", "primary_model"),
        Index("ix_llm_compare_hourly_candidate", "candidate_model"),
    )
