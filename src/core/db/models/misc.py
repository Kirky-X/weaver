# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Miscellaneous SQLAlchemy ORM models.

Groups models that don't fit a dedicated module: entity/community vectors,
source authority/config, relation types, sentiment shifts, daily briefings,
audit logs, API keys, and prompt templates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.models.base import Base, JSONCompatible


class EntityVector(Base):
    """Entity embedding vectors table for entity resolution."""

    __tablename__ = "entity_vectors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    neo4j_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(1024), nullable=False)
    model_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="text-embedding-3-large"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index(
            "idx_entity_vectors_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 200},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class SourceAuthority(Base):
    """Source authority scores for credibility assessment."""

    __tablename__ = "source_authorities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    authority: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0.50)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    description: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    # Design doc §4.1: manual scoring and computed final score
    manual_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    final_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    article_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )


class SourceConfig(Base):
    """News source configuration with preset credibility.

    Implements: SourceRepository
    """

    __tablename__ = "source_configs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="rss")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    per_host_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    credibility: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_crawl_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    etag: Mapped[str | None] = mapped_column(String(200))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint(
            "credibility >= 0 AND credibility <= 1",
            name="chk_source_configs_credibility_range",
        ),
        CheckConstraint(
            "tier >= 1 AND tier <= 3",
            name="chk_source_configs_tier_range",
        ),
        CheckConstraint(
            "interval_minutes >= 5 AND interval_minutes <= 1440",
            name="chk_source_configs_interval_minutes_range",
        ),
    )


class RelationType(Base):
    """Standard relation types for knowledge graph relationships."""

    __tablename__ = "relation_types"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name_en: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    is_symmetric: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    # Relationships
    aliases: Mapped[list[RelationTypeAlias]] = relationship(
        back_populates="relation_type", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_relation_types_category", "category"),
        Index("idx_relation_types_is_active", "is_active"),
    )


class RelationTypeAlias(Base):
    """Alternative names for relation types."""

    __tablename__ = "relation_type_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    relation_type_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("relation_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    # Relationships
    relation_type: Mapped[RelationType] = relationship(back_populates="aliases")

    __table_args__ = (
        Index("idx_aliases_relation_type_id", "relation_type_id"),
        Index("idx_aliases_alias", "alias"),
    )


class UnknownRelationType(Base):
    """Unknown relation types extracted from entities for later review."""

    __tablename__ = "unknown_relation_types"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_type: Mapped[str] = mapped_column(String(100), nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("idx_unknown_raw_type", "raw_type"),
        Index("idx_unknown_resolved", "resolved"),
        Index("idx_unknown_hit_count", "hit_count"),
    )


class SentimentShift(Base):
    __tablename__ = "sentiment_shifts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Design doc §12.1: denormalized community name
    community_title: Mapped[str | None] = mapped_column(String(200))
    shift_type: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    magnitude: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Design doc §12.1: detection time window
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    before_avg: Mapped[float | None] = mapped_column(Numeric(5, 4))
    after_avg: Mapped[float | None] = mapped_column(Numeric(5, 4))
    trigger_article_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    # Migration 30: article-level tracking fields (T003 SentimentTrackerNode)
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shift_value: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        CheckConstraint(
            "shift_type IN ('mean_shift', 'cumulative_drift', 'variance_change')",
            name="chk_shift_type_values",
        ),
        Index("idx_shifts_community", "community_id"),
        Index("idx_shifts_type", "shift_type"),
        Index("idx_shifts_detected", "detected_at"),
        # Migration 31: covering index for T003 SentimentTrackerNode's
        # get_last_article_shift query (WHERE entity_name=? AND article_id IS
        # NOT NULL ORDER BY detected_at DESC LIMIT 1). Partial index keeps it
        # small — only article-level rows are indexed. DuckDB falls back to a
        # regular composite index (no partial index support).
        Index(
            "idx_shifts_entity_article_detected",
            "entity_name",
            "article_id",
            "detected_at",
            postgresql_where=text("article_id IS NOT NULL"),
        ),
    )


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Migration 32: dropped single-column unique=True to allow 4 briefings
    # per day (finance/tech/ai/general). Composite UNIQUE(briefing_date,
    # category) replaces it — see __table_args__ below.
    briefing_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    # Design doc §12.2: briefing metadata
    title: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default=text("'draft'")
    )
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )
    # T004: Briefing category — finance/tech/ai/general (spec R-briefing-003).
    # Nullable for backward compat with pre-migration-32 rows. DISTINCT from
    # articles_core.category (CategoryType enum) — briefing category is the
    # output grouping, article category is the input filter.
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)

    items: Mapped[list[DailyBriefingItem]] = relationship(
        back_populates="briefing", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="chk_briefing_status",
        ),
        Index("idx_briefings_date", "briefing_date"),
        # Migration 32: composite unique replaces single-column unique on
        # briefing_date. Allows up to 4 briefings per day (one per category).
        # NULL category treated as distinct by PostgreSQL, so pre-migration-32
        # rows with category=NULL remain valid.
        UniqueConstraint(
            "briefing_date",
            "category",
            name="uq_briefings_date_category",
        ),
    )


class DailyBriefingItem(Base):
    __tablename__ = "daily_briefing_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    briefing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("daily_briefings.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles_core.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # Design doc §12.2: scoring fields
    score: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False)
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONCompatible)
    category: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)

    briefing: Mapped[DailyBriefing] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint(
            "rank >= 1 AND rank <= 10",
            name="chk_briefing_item_rank_range",
        ),
        UniqueConstraint("briefing_id", "article_id", name="uq_briefing_item_article"),
        UniqueConstraint("briefing_id", "rank", name="uq_briefing_item_rank"),
    )


class AuditLog(Base):
    """Audit log for security monitoring and compliance.

    Implements: Weaver-数据库设计文档 §12.3
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONCompatible)
    # NOTE: Design doc specifies INET type, but kept as String(45) for DuckDB compatibility.
    # IPv6 addresses can be up to 45 chars. INET would break DuckDB fallback.
    client_ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("idx_audit_occurred", created_at.desc()),
        Index("idx_audit_key", "key_id", created_at.desc()),
    )


class CommunityVector(Base):
    __tablename__ = "community_vectors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    community_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    embedding: Mapped[Any] = mapped_column(Vector(1024), nullable=False)
    model_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="text-embedding-3-large"
    )
    # Design doc §8.6: metadata for text fallback search
    title: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    entity_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    article_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rank: Mapped[float | None] = mapped_column(Numeric(3, 2))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index(
            "idx_community_vectors_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 200},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # GIN index for text search on title (design doc §8.6)
        Index(
            "idx_community_vectors_title_gin",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )


# ── New tables per design docs ────────────────────────────────


class ApiKey(Base):
    """API key management with scopes, expiry, and rate limits.

    Implements: Weaver-数据库设计文档 §1.6.3
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        JSONCompatible, nullable=False, server_default=text("'[\"search:read\"]'::jsonb")
    )
    rate_limit_per_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default=text("100")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Design doc §1.6.3: key rotation tracking
    rotated_to: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("idx_api_keys_key_id", "key_id"),
        Index(
            "idx_api_keys_expires",
            "expires_at",
            postgresql_where=text("is_revoked = false"),
        ),
    )


class PromptTemplate(Base):
    """Prompt templates for LLM calls.

    Fixes: Migration 01_initial created this table but no ORM model existed.
    """

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
        onupdate=lambda: datetime.now(UTC),
    )
