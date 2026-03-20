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
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    type_annotation_map = {
        dict[str, Any]: JSONB,
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
    PENDING = "pending"
    PROCESSING = "processing"
    PG_DONE = "pg_done"
    NEO4J_DONE = "neo4j_done"
    FAILED = "failed"

    @classmethod
    def is_valid_transition(
        cls,
        from_status: PersistStatus,
        to_status: PersistStatus,
    ) -> bool:
        """Validate if a status transition is allowed.

        Valid transitions:
        - PENDING → PROCESSING, FAILED
        - PROCESSING → PG_DONE, FAILED
        - PG_DONE → NEO4J_DONE, FAILED
        - FAILED → PENDING (allows retry)

        Args:
            from_status: Current status.
            to_status: Target status.

        Returns:
            True if the transition is valid, False otherwise.
        """
        # Allow staying in same state (idempotent)
        if from_status == to_status:
            return True

        # Define valid transitions
        valid_transitions = {
            cls.PENDING: {cls.PROCESSING, cls.FAILED},
            cls.PROCESSING: {cls.PG_DONE, cls.FAILED},
            cls.PG_DONE: {cls.NEO4J_DONE, cls.FAILED},
            cls.FAILED: {cls.PENDING},  # Allow retry
            cls.NEO4J_DONE: set(),  # Terminal state
        }

        allowed = valid_transitions.get(from_status, set())
        return to_status in allowed


class EmotionType(str, enum.Enum):
    OPTIMISTIC = "乐观"
    INSPIRED = "振奋"
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


class Article(Base):
    """Main articles table."""

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
        UUID(as_uuid=True), ForeignKey("articles.id")
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
    prompt_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

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

    # Relationships
    vectors: Mapped[list[ArticleVector]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )

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
    )


class ArticleVector(Base):
    """Article embedding vectors table."""

    __tablename__ = "article_vectors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
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
    article: Mapped[Article] = relationship(back_populates="vectors")

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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("NOW()"),
    )


class LLMFailure(Base):
    """LLM request failure record for persistent logging and 3-day rolling cleanup."""

    __tablename__ = "llm_failures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_point: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float | None] = mapped_column(Numeric(10, 2))
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="SET NULL"),
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
        Index("idx_llm_failures_created", "created_at"),
        Index("idx_llm_failures_article", "article_id"),
        Index("idx_llm_failures_call_point", "call_point"),
        Index("idx_llm_failures_provider", "provider"),
    )


class Source(Base):
    """News source configuration with preset credibility."""

    __tablename__ = "sources"

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
            name="chk_sources_credibility_range",
        ),
        CheckConstraint(
            "tier >= 1 AND tier <= 3",
            name="chk_sources_tier_range",
        ),
    )
