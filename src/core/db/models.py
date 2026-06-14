# Copyright (c) 2026 KirkyX. All Rights Reserved
"""SQLAlchemy 2.0 ORM models for the weaver system."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator


class JSONCompatible(TypeDecorator):
    """TypeDecorator that uses JSONB for PostgreSQL and JSON for other dialects.

    DuckDB and SQLite don't support JSONB, only JSON. This decorator
    automatically selects the appropriate type based on the database dialect.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            # Use JSONB for PostgreSQL
            return JSONB().dialect_impl(dialect)
        # Use plain JSON for DuckDB, SQLite, etc.
        return JSON().dialect_impl(dialect)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    type_annotation_map = {
        dict[str, Any]: JSONCompatible,
        list[str]: ARRAY(Text),
        list[uuid.UUID]: ARRAY(UUID(as_uuid=True)),
    }


# ── Enum Types ───────────────────────────────────────────────


class CategoryType(str, enum.Enum):
    POLITICS = "政治"
    MILITARY = "军事"
    ECONOMY = "经济"
    TECHNOLOGY = "科技"
    SOCIETY = "社会"
    CULTURE = "文化"
    SPORTS = "体育"
    INTERNATIONAL = "国际"


class PersistStatus(str, enum.Enum):
    """Persist status for articles.

    States:
        PENDING: Initial state after article creation.
        PROCESSING: Traditional pipeline processing in progress.
        PG_DONE: PostgreSQL write successful.
        NEO4J_DONE: All writes complete (terminal success state for Neo4j).
        LADYBUG_DONE: All writes complete (terminal success state for LadybugDB).
        NEO4J_FAILED: Neo4j write failed (retryable).
        FAILED: Final failure state (retryable).

    Saga States (for cross-database transactions):
        SAGA_STARTED: Saga transaction initiated.
        SAGA_PG_WRITING: PostgreSQL write phase of Saga.
        SAGA_NEO4J_WRITING: Neo4j write phase of Saga.
        SAGA_COMPENSATING: Saga compensation in progress.
        SAGA_COMPENSATED: Saga compensation complete.
        SAGA_COMPLETED: Saga transaction fully complete (terminal success state).
    """

    PENDING = "pending"
    PROCESSING = "processing"
    PG_DONE = "pg_done"
    NEO4J_DONE = "neo4j_done"
    LADYBUG_DONE = "ladybug_done"
    NEO4J_FAILED = "neo4j_failed"
    SAGA_STARTED = "saga_started"
    SAGA_PG_WRITING = "saga_pg_writing"
    SAGA_NEO4J_WRITING = "saga_neo4j_writing"
    SAGA_COMPENSATING = "saga_compensating"
    SAGA_COMPENSATED = "saga_compensated"
    SAGA_COMPLETED = "saga_completed"
    FAILED = "failed"

    @classmethod
    def is_valid_transition(
        cls,
        from_status: PersistStatus,
        to_status: PersistStatus,
    ) -> bool:
        """Validate if a status transition is allowed.

        Valid transitions:
        - PENDING → PROCESSING, FAILED, SAGA_STARTED
        - PROCESSING → PG_DONE, FAILED
        - PG_DONE → NEO4J_DONE, LADYBUG_DONE, NEO4J_FAILED, FAILED
        - NEO4J_FAILED → PENDING, PG_DONE (allows retry)
        - SAGA_STARTED → SAGA_PG_WRITING, FAILED
        - SAGA_PG_WRITING → SAGA_NEO4J_WRITING, SAGA_COMPENSATING
        - SAGA_NEO4J_WRITING → SAGA_COMPLETED, SAGA_COMPENSATING
        - SAGA_COMPENSATING → SAGA_COMPENSATED, FAILED
        - SAGA_COMPENSATED → PENDING (allows retry)
        - SAGA_COMPLETED is terminal
        - FAILED → PENDING (allows retry), NEO4J_DONE, LADYBUG_DONE (allows recovery after graph write success)
        - NEO4J_DONE is terminal
        - LADYBUG_DONE is terminal

        Args:
            from_status: Current status.
            to_status: Target status.

        Returns:
            True if the transition is valid, False otherwise.
        """
        if from_status == to_status:
            return True

        valid_transitions = {
            cls.PENDING: {
                cls.PROCESSING,
                cls.FAILED,
                cls.SAGA_STARTED,
                cls.LADYBUG_DONE,
                cls.NEO4J_DONE,
            },
            cls.PROCESSING: {cls.PG_DONE, cls.FAILED},
            cls.PG_DONE: {cls.NEO4J_DONE, cls.LADYBUG_DONE, cls.NEO4J_FAILED, cls.FAILED},
            cls.NEO4J_FAILED: {cls.PENDING, cls.PG_DONE},
            cls.SAGA_STARTED: {cls.SAGA_PG_WRITING, cls.FAILED},
            cls.SAGA_PG_WRITING: {cls.SAGA_NEO4J_WRITING, cls.SAGA_COMPENSATING},
            cls.SAGA_NEO4J_WRITING: {cls.SAGA_COMPLETED, cls.SAGA_COMPENSATING},
            cls.SAGA_COMPENSATING: {cls.SAGA_COMPENSATED, cls.FAILED},
            cls.SAGA_COMPENSATED: {cls.PENDING},
            cls.SAGA_COMPLETED: set(),
            cls.FAILED: {cls.PENDING, cls.NEO4J_DONE, cls.LADYBUG_DONE},
            cls.NEO4J_DONE: set(),
            cls.LADYBUG_DONE: set(),
        }

        allowed = valid_transitions.get(from_status, set())
        return to_status in allowed

    @classmethod
    def completed_statuses(cls) -> frozenset[PersistStatus]:
        """Return the set of statuses that indicate article processing is complete.

        Includes all terminal success states and PG_DONE (intermediate success).
        Used for queries that need to find "completed" articles regardless of
        which graph database backend was used.
        """
        return frozenset({cls.PG_DONE, cls.NEO4J_DONE, cls.LADYBUG_DONE, cls.SAGA_COMPLETED})

    @classmethod
    def is_terminal(cls, status: PersistStatus) -> bool:
        """Check if a status is terminal (no outgoing transitions except self).

        Args:
            status: Status to check.

        Returns:
            True if the status is terminal.
        """
        return status in {cls.NEO4J_DONE, cls.LADYBUG_DONE, cls.SAGA_COMPLETED}

    @classmethod
    def allows_retry(cls, status: PersistStatus) -> bool:
        """Check if a status allows retry (can transition to PENDING).

        Args:
            status: Status to check.

        Returns:
            True if the status allows retry.
        """
        return status in {cls.FAILED, cls.SAGA_COMPENSATED, cls.NEO4J_FAILED}


class EmotionType(str, enum.Enum):
    OPTIMISTIC = "乐观"
    INSPIRED = "振奋"
    EXCITED = "兴奋"
    EXPECTANT = "期待"
    CALM = "平静"
    OBJECTIVE = "客观"
    WORRIED = "担忧"
    PESSIMISTIC = "悲观"
    ANGRY = "愤怒"
    PANIC = "恐慌"


class VectorType(str, enum.Enum):
    TITLE = "title"
    CONTENT = "content"


# ── Models ───────────────────────────────────────────────────


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
        Enum(VectorType, name="vector_type", create_type=True), nullable=False
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
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    article_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("ix_llm_usage_raw_created_at", "created_at"),
        Index("ix_llm_usage_raw_label", "label"),
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
    )


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    briefing_date: Mapped[datetime] = mapped_column(Date, nullable=False, unique=True)
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

    items: Mapped[list[DailyBriefingItem]] = relationship(
        back_populates="briefing", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="chk_briefing_status",
        ),
        Index("idx_briefings_date", "briefing_date"),
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
        ),
        # GIN index for text search on title (design doc §8.6)
        Index(
            "idx_community_vectors_title_gin",
            "title",
            postgresql_using="gin",
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
