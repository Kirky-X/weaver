# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Article-related SQLAlchemy ORM models.

Includes the vertical-split tables (core/body/analysis/processing), the
backward-compatible Article view, embedding vectors, and version history.
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
    DateTime,
    Enum,
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

from core.db.models.base import (
    Base,
    CategoryType,
    EmotionType,
    JSONCompatible,
    PersistStatus,
    VectorType,
)


class ArticleCore(Base):
    """High-frequency query columns for articles.

    Implements: Vertical split per Weaver-数据库设计文档 §9.1
    Row width ~500 bytes → ~16 rows/page → full table scan ×3 faster.
    """

    __tablename__ = "articles_core"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_host: Mapped[str | None] = mapped_column(String(200))
    source_id: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[CategoryType | None] = mapped_column(
        Enum(
            CategoryType,
            name="category_type",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        )
    )
    language: Mapped[str | None] = mapped_column(String(10))
    region: Mapped[str | None] = mapped_column(String(50))
    score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    credibility_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    persist_status: Mapped[PersistStatus] = mapped_column(
        Enum(
            PersistStatus,
            name="persist_status",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=PersistStatus.PENDING,
    )
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Merge related
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles_core.id")
    )
    is_merged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    merged_source_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))

    # Content dedup
    content_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    document_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="news", server_default=text("'news'")
    )
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONCompatible, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Timestamps
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

    # Relationships
    body: Mapped[ArticleBody | None] = relationship(
        back_populates="core",
        cascade="all, delete-orphan",
        uselist=False,
    )
    analysis: Mapped[ArticleAnalysis | None] = relationship(
        back_populates="core",
        cascade="all, delete-orphan",
        uselist=False,
    )
    vectors: Mapped[list[ArticleVector]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
    )
    processing: Mapped[ArticleProcessing | None] = relationship(
        back_populates="core",
        cascade="all, delete-orphan",
        uselist=False,
    )

    # Constraints
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="chk_core_score_range"),
        CheckConstraint(
            "sentiment_score >= 0 AND sentiment_score <= 1",
            name="chk_core_sentiment_score_range",
        ),
        CheckConstraint(
            "credibility_score >= 0 AND credibility_score <= 1",
            name="chk_core_credibility_score_range",
        ),
        CheckConstraint("merged_into IS DISTINCT FROM id", name="chk_core_no_self_merge"),
        CheckConstraint(
            "document_type IN ('news', 'policy', 'tweet', 'wechat', 'blog', 'report', 'pdf_doc', 'social_post')",
            name="chk_core_document_type",
        ),
        # ── Existing indexes ──
        Index("idx_core_category", "category"),
        Index("idx_core_publish_time", publish_time.desc()),
        Index("idx_core_score", score.desc()),
        Index("idx_core_credibility", credibility_score.desc()),
        Index("idx_core_sentiment_score", sentiment_score.desc()),
        Index("idx_core_merged_into", "merged_into"),
        Index(
            "idx_core_persist_status",
            "persist_status",
            postgresql_where=text("persist_status IN ('pending', 'pg_done')"),
        ),
        Index("idx_core_category_publish", "category", publish_time.desc()),
        Index("idx_core_host_publish", "source_host", publish_time.desc()),
        Index("idx_core_status_created", "persist_status", created_at.asc()),
        # ── Optimization indexes (design doc §9.2) ──
        Index(
            "idx_articles_sentiment_time",
            "sentiment_score",
            publish_time.desc(),
            postgresql_where=text("sentiment_score IS NOT NULL"),
        ),
        Index(
            "idx_articles_briefing",
            publish_time.desc(),
            score.desc(),
            postgresql_where=text("score IS NOT NULL"),
        ),
        Index(
            "idx_articles_category_sentiment",
            "category",
            sentiment_score.desc(),
            postgresql_where=text("category IS NOT NULL AND sentiment_score IS NOT NULL"),
        ),
        Index(
            "idx_articles_url_lookup",
            "source_url",
            postgresql_include=["id", "title", "publish_time"],
        ),
        Index(
            "idx_articles_retry",
            "persist_status",
            updated_at.asc(),
            postgresql_where=text("persist_status IN ('pg_done', 'neo4j_failed', 'failed')"),
        ),
        # ── GIN indexes for JSONB queries (design doc §9.2) ──
        Index(
            "idx_articles_doc_metadata_gin",
            "doc_metadata",
            postgresql_using="gin",
        ),
        # ── Composite indexes ──
        Index("idx_core_document_type_publish", "document_type", publish_time.desc()),
    )


class ArticleBody(Base):
    """Large text fields for articles, only accessed on detail pages.

    Implements: Vertical split per Weaver-数据库设计文档 §9.1
    """

    __tablename__ = "article_bodies"

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles_core.id", ondelete="CASCADE"),
        primary_key=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)

    # Relationships
    core: Mapped[ArticleCore] = relationship(back_populates="body")


class ArticleAnalysis(Base):
    """LLM analysis results for articles.

    Implements: Vertical split per Weaver-数据库设计文档 §9.1
    Grows with features without affecting core table performance.
    """

    __tablename__ = "article_analysis"

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles_core.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_news: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subjects: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    key_data: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    impact: Mapped[str | None] = mapped_column(Text)
    has_data: Mapped[bool | None] = mapped_column(Boolean)
    quality_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    sentiment: Mapped[str | None] = mapped_column(String(10))
    primary_emotion: Mapped[EmotionType | None] = mapped_column(
        Enum(
            EmotionType,
            name="emotion_type",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        )
    )
    emotion_targets: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    source_credibility: Mapped[float | None] = mapped_column(Numeric(3, 2))
    cross_verification: Mapped[float | None] = mapped_column(Numeric(3, 2))
    content_check_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    credibility_flags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    verified_by_sources: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_conflicts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONCompatible, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_forensics: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONCompatible, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    prompt_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONCompatible)

    # Relationships
    core: Mapped[ArticleCore] = relationship(back_populates="analysis")

    __table_args__ = (
        CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1",
            name="chk_analysis_quality_score_range",
        ),
        # Optimization index: is_news filter (design doc §9.2 #4)
        # Note: is_news is in article_analysis after vertical split
        Index(
            "idx_articles_is_news",
            "is_news",
            postgresql_where=text("is_news = true"),
        ),
        # GIN index for JSONB queries on data_conflicts
        Index(
            "idx_core_data_conflicts_gin",
            "data_conflicts",
            postgresql_using="gin",
        ),
    )


class ArticleProcessing(Base):
    """Processing tracking fields for articles, separated from core for row width optimization.

    Implements: Vertical split per Weaver-数据库设计文档 §9.1
    Keeps core table narrow (~400 bytes) by moving processing state to separate table.
    """

    __tablename__ = "article_processing"

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles_core.id", ondelete="CASCADE"),
        primary_key=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    processing_stage: Mapped[str | None] = mapped_column(String(50))
    processing_error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default=text("0")
    )

    # Timestamps
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

    # Relationships
    core: Mapped[ArticleCore] = relationship(back_populates="processing")

    # Constraints
    __table_args__ = (
        Index("idx_processing_task_id", "task_id"),
        Index("idx_processing_stage", "processing_stage"),
        Index("idx_processing_task_status", "task_id", "processing_stage"),
    )


class Article(Base):
    """Backward-compatible view joining articles_core + article_bodies + article_analysis.

    After vertical split (migration 06), the `articles` table is replaced by a VIEW.
    This ORM class maps to that view for backward compatibility.
    For write operations, use ArticleCore, ArticleBody, ArticleAnalysis directly.
    """

    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_host: Mapped[str | None] = mapped_column(String(200))
    source_id: Mapped[str | None] = mapped_column(String(100))
    is_news: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[CategoryType | None] = mapped_column(
        Enum(
            CategoryType,
            name="category_type",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],  # Use enum values, not names
        )
    )
    language: Mapped[str | None] = mapped_column(String(10))
    region: Mapped[str | None] = mapped_column(String(50))

    # Merge related
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles_core.id")
    )
    is_merged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    merged_source_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))

    # Summary & analysis
    summary: Mapped[str | None] = mapped_column(Text)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subjects: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    key_data: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    impact: Mapped[str | None] = mapped_column(Text)
    has_data: Mapped[bool | None] = mapped_column(Boolean)

    # Content enrichment
    data_conflicts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONCompatible, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    image_forensics: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONCompatible, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    document_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="news", server_default=text("'news'")
    )
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONCompatible, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    content_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    # Score (0.00~1.00)
    score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    quality_score: Mapped[float | None] = mapped_column(Numeric(3, 2))

    # Sentiment
    sentiment: Mapped[str | None] = mapped_column(String(10))
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    primary_emotion: Mapped[EmotionType | None] = mapped_column(
        Enum(
            EmotionType,
            name="emotion_type",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],  # Use enum values, not names
        )
    )
    emotion_targets: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    # Credibility
    credibility_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    source_credibility: Mapped[float | None] = mapped_column(Numeric(3, 2))
    cross_verification: Mapped[float | None] = mapped_column(Numeric(3, 2))
    content_check_score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    credibility_flags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    verified_by_sources: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Persist status
    persist_status: Mapped[PersistStatus] = mapped_column(
        Enum(
            PersistStatus,
            name="persist_status",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=PersistStatus.PENDING,
    )

    # Task tracking
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # Processing tracking
    processing_stage: Mapped[str | None] = mapped_column(String(50))
    processing_error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Prompt version tracing
    prompt_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONCompatible)

    # Timestamps
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    # Relationships - vectors relationship moved to ArticleCore after vertical split
    # Article maps to a backward-compatible view; use ArticleCore for vector access

    # Constraints
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="chk_score_range"),
        CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1",
            name="chk_quality_score_range",
        ),
        CheckConstraint(
            "sentiment_score >= 0 AND sentiment_score <= 1",
            name="chk_sentiment_score_range",
        ),
        CheckConstraint(
            "credibility_score >= 0 AND credibility_score <= 1",
            name="chk_credibility_score_range",
        ),
        CheckConstraint("merged_into IS DISTINCT FROM id", name="chk_no_self_merge"),
        Index("idx_articles_category", "category"),
        Index("idx_articles_publish_time", publish_time.desc()),
        Index("idx_articles_score", score.desc()),
        Index("idx_articles_credibility", credibility_score.desc()),
        Index("idx_articles_sentiment_score", sentiment_score.desc()),
        Index("idx_articles_primary_emotion", "primary_emotion"),
        Index("idx_articles_merged_into", "merged_into"),
        Index(
            "idx_articles_persist_status",
            "persist_status",
            postgresql_where=text("persist_status IN ('pending', 'pg_done')"),
        ),
        Index("idx_articles_category_publish", "category", publish_time.desc()),
        Index("idx_articles_host_publish", "source_host", publish_time.desc()),
        Index("idx_articles_status_created", "persist_status", created_at.asc()),
        Index("idx_articles_task_status", "task_id", "persist_status"),
        # GIN index for JSONB queries on data_conflicts
        Index(
            "idx_articles_data_conflicts_gin",
            "data_conflicts",
            postgresql_using="gin",
        ),
        # Composite index for document_type + publish_time queries
        Index("idx_articles_document_type_publish", "document_type", publish_time.desc()),
    )


class ArticleVector(Base):
    """Article embedding vectors table."""

    __tablename__ = "article_vectors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles_core.id", ondelete="CASCADE"),
        nullable=False,
    )
    vector_type: Mapped[VectorType] = mapped_column(
        Enum(
            VectorType,
            name="vector_type",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    embedding: Mapped[Any] = mapped_column(Vector(1024), nullable=False)
    model_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="text-embedding-3-large"
    )
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

    # Relationships
    article: Mapped[ArticleCore] = relationship(back_populates="vectors")

    __table_args__ = (
        Index(
            "idx_av_unique",
            "article_id",
            "vector_type",
            unique=True,
        ),
    )


class ArticleVersion(Base):
    """Article version history for tracking content changes.

    Implements: Weaver-数据库设计文档 §9.11.6
    """

    __tablename__ = "article_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles_core.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Numeric(3, 2))
    changed_fields: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        UniqueConstraint("article_id", "version", name="uq_article_version"),
        Index("idx_article_versions_id", "article_id", version.desc()),
    )
