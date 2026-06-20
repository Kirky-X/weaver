# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Vertical split: articles → articles_core + article_bodies + article_analysis.

Revision ID: 06_vertical_split_articles
Revises: 05_create_security_tables
Create Date: 2026-06-10

Changes per Weaver-数据库设计文档 §9.1:
- Create articles_core (high-frequency query columns, ~500 bytes/row)
- Create article_bodies (large text fields, detail-page only)
- Create article_analysis (LLM analysis results)
- Migrate data from articles to the three new tables
- Create backward-compatible `articles` VIEW joining all three tables
- Drop original articles table
- Redirect article_vectors FK to articles_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "06_vertical_split_articles"
down_revision: str | None = "05_create_security_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply vertical split migration: articles → articles_core + article_bodies + article_analysis."""
    # ── Step 1: Create articles_core ──────────────────────────
    op.create_table(
        "articles_core",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("source_url", sa.Text, unique=True, nullable=False),
        sa.Column("source_host", sa.String(200)),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(
                "政治",
                "军事",
                "经济",
                "科技",
                "社会",
                "文化",
                "体育",
                "国际",
                name="category_type",
                create_type=False,
            ),
        ),
        sa.Column("language", sa.String(10)),
        sa.Column("region", sa.String(50)),
        sa.Column("score", sa.Numeric(3, 2)),
        sa.Column("sentiment_score", sa.Numeric(3, 2)),
        sa.Column("credibility_score", sa.Numeric(3, 2)),
        sa.Column(
            "persist_status",
            postgresql.ENUM(
                "pending",
                "processing",
                "pg_done",
                "neo4j_done",
                "neo4j_failed",
                "failed",
                name="persist_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("publish_time", sa.DateTime(timezone=True)),
        # Merge related
        sa.Column("merged_into", postgresql.UUID(as_uuid=True), sa.ForeignKey("articles_core.id")),
        sa.Column("is_merged", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("merged_source_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        # Content dedup
        sa.Column("content_hash", sa.String(64)),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("document_type", sa.String(20), nullable=False, server_default=sa.text("'news'")),
        sa.Column(
            "doc_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        # Task tracking
        sa.Column("task_id", postgresql.UUID(as_uuid=True)),
        # Processing tracking
        sa.Column("processing_stage", sa.String(50)),
        sa.Column("processing_error", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # Constraints
        sa.CheckConstraint("score >= 0 AND score <= 1", name="chk_core_score_range"),
        sa.CheckConstraint(
            "sentiment_score >= 0 AND sentiment_score <= 1", name="chk_core_sentiment_score_range"
        ),
        sa.CheckConstraint(
            "credibility_score >= 0 AND credibility_score <= 1",
            name="chk_core_credibility_score_range",
        ),
        sa.CheckConstraint("merged_into IS DISTINCT FROM id", name="chk_core_no_self_merge"),
    )

    # Indexes for articles_core
    op.create_index("idx_core_category", "articles_core", ["category"])
    op.create_index("idx_core_publish_time", "articles_core", [sa.text("publish_time DESC")])
    op.create_index("idx_core_score", "articles_core", [sa.text("score DESC")])
    op.create_index("idx_core_credibility", "articles_core", [sa.text("credibility_score DESC")])
    op.create_index("idx_core_sentiment_score", "articles_core", [sa.text("sentiment_score DESC")])
    op.create_index("idx_core_merged_into", "articles_core", ["merged_into"])
    op.create_index(
        "idx_core_persist_status",
        "articles_core",
        ["persist_status"],
        postgresql_where=sa.text("persist_status IN ('pending', 'pg_done')"),
    )
    op.create_index(
        "idx_core_category_publish", "articles_core", ["category", sa.text("publish_time DESC")]
    )
    op.create_index(
        "idx_core_host_publish", "articles_core", ["source_host", sa.text("publish_time DESC")]
    )
    op.create_index(
        "idx_core_status_created", "articles_core", ["persist_status", sa.text("created_at ASC")]
    )
    op.create_index("idx_core_task_status", "articles_core", ["task_id", "persist_status"])

    # ── Step 2: Create article_bodies ─────────────────────────
    op.create_table(
        "article_bodies",
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles_core.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("summary", sa.Text),
    )

    # ── Step 3: Create article_analysis ───────────────────────
    op.create_table(
        "article_analysis",
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles_core.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_news", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("subjects", postgresql.ARRAY(sa.Text)),
        sa.Column("key_data", postgresql.ARRAY(sa.Text)),
        sa.Column("impact", sa.Text),
        sa.Column("has_data", sa.Boolean),
        sa.Column("quality_score", sa.Numeric(3, 2)),
        sa.Column("sentiment", sa.String(10)),
        sa.Column(
            "primary_emotion",
            postgresql.ENUM(
                "乐观",
                "振奋",
                "兴奋",
                "期待",
                "平静",
                "客观",
                "担忧",
                "悲观",
                "愤怒",
                "恐慌",
                name="emotion_type",
                create_type=False,
            ),
        ),
        sa.Column("emotion_targets", postgresql.ARRAY(sa.Text)),
        sa.Column("source_credibility", sa.Numeric(3, 2)),
        sa.Column("cross_verification", sa.Numeric(3, 2)),
        sa.Column("content_check_score", sa.Numeric(3, 2)),
        sa.Column("credibility_flags", postgresql.ARRAY(sa.Text)),
        sa.Column("verified_by_sources", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "data_conflicts",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column(
            "image_forensics",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("prompt_versions", postgresql.JSONB),
        sa.CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1", name="chk_analysis_quality_score_range"
        ),
    )

    # ── Step 4: Migrate data from articles ────────────────────
    op.execute("""
        INSERT INTO articles_core (
            id, source_url, source_host, title, category, language, region,
            score, sentiment_score, credibility_score, persist_status, publish_time,
            merged_into, is_merged, merged_source_ids,
            content_hash, version, document_type, doc_metadata,
            task_id, processing_stage, processing_error, retry_count,
            created_at, updated_at
        )
        SELECT
            id, source_url, source_host, title, category, language, region,
            score, sentiment_score, credibility_score, persist_status, publish_time,
            merged_into, is_merged, merged_source_ids::uuid[],
            content_hash, version, document_type, doc_metadata,
            task_id, processing_stage, processing_error, retry_count,
            created_at, updated_at
        FROM articles
    """)

    op.execute("""
        INSERT INTO article_bodies (article_id, body, summary)
        SELECT id, body, summary FROM articles
    """)

    op.execute("""
        INSERT INTO article_analysis (
            article_id, is_news, subjects, key_data, impact, has_data,
            quality_score, sentiment, primary_emotion, emotion_targets,
            source_credibility, cross_verification, content_check_score,
            credibility_flags, verified_by_sources, data_conflicts,
            event_time, image_forensics, prompt_versions
        )
        SELECT
            id, is_news, subjects, key_data, impact, has_data,
            quality_score, sentiment, primary_emotion, emotion_targets,
            source_credibility, cross_verification, content_check_score,
            credibility_flags, verified_by_sources, data_conflicts,
            event_time, image_forensics, prompt_versions
        FROM articles
    """)

    # ── Step 5: Redirect article_vectors FK ───────────────────
    op.drop_constraint("article_vectors_article_id_fkey", "article_vectors", type_="foreignkey")
    op.create_foreign_key(
        "article_vectors_article_id_fkey",
        "article_vectors",
        "articles_core",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── Step 6: Redirect other FKs ────────────────────────────
    # llm_failures
    op.drop_constraint("llm_failures_article_id_fkey", "llm_failures", type_="foreignkey")
    op.create_foreign_key(
        "llm_failures_article_id_fkey",
        "llm_failures",
        "articles_core",
        ["article_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # pending_sync
    op.drop_constraint("pending_sync_article_id_fkey", "pending_sync", type_="foreignkey")
    op.create_foreign_key(
        "pending_sync_article_id_fkey",
        "pending_sync",
        "articles_core",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # daily_briefing_items
    op.drop_constraint(
        "daily_briefing_items_article_id_fkey", "daily_briefing_items", type_="foreignkey"
    )
    op.create_foreign_key(
        "daily_briefing_items_article_id_fkey",
        "daily_briefing_items",
        "articles_core",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # articles merged_into self-reference
    op.drop_constraint("articles_merged_into_fkey", "articles", type_="foreignkey")

    # ── Step 7: Drop original articles table ──────────────────
    op.drop_table("articles")

    # ── Step 8: Create backward-compatible view ───────────────
    op.execute("""
        CREATE VIEW articles AS
        SELECT
            c.id, c.source_url, c.source_host, c.title,
            c.category, c.language, c.region,
            b.body, b.summary,
            a.is_news, a.subjects, a.key_data, a.impact, a.has_data,
            a.quality_score, a.sentiment, a.primary_emotion, a.emotion_targets,
            a.source_credibility, a.cross_verification, a.content_check_score,
            a.credibility_flags, a.verified_by_sources, a.data_conflicts,
            a.event_time, a.image_forensics,
            c.document_type, c.doc_metadata, c.content_hash, c.version,
            c.score, a.prompt_versions,
            c.persist_status, c.publish_time, c.created_at, c.updated_at,
            c.merged_into, c.is_merged, c.merged_source_ids,
            c.task_id, c.processing_stage, c.processing_error, c.retry_count,
            c.sentiment_score
        FROM articles_core c
        LEFT JOIN article_bodies b ON c.id = b.article_id
        LEFT JOIN article_analysis a ON c.id = a.article_id
    """)


def downgrade() -> None:
    """Revert vertical split: recreate monolithic articles table from split tables."""
    # Drop the view
    op.execute("DROP VIEW IF EXISTS articles")

    # Recreate the original articles table
    # Note: Full downgrade is complex; this is a simplified version
    # that recreates the table structure for rollback purposes.
    # Data loss will occur in downgrade.
    op.create_table(
        "articles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("source_url", sa.Text, unique=True, nullable=False),
        sa.Column("source_host", sa.String(200)),
        sa.Column("is_news", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(
                "政治",
                "军事",
                "经济",
                "科技",
                "社会",
                "文化",
                "体育",
                "国际",
                name="category_type",
                create_type=False,
            ),
        ),
        sa.Column("language", sa.String(10)),
        sa.Column("region", sa.String(50)),
        sa.Column("merged_into", postgresql.UUID(as_uuid=True), sa.ForeignKey("articles.id")),
        sa.Column("is_merged", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("merged_source_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("summary", sa.Text),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column("subjects", postgresql.ARRAY(sa.Text)),
        sa.Column("key_data", postgresql.ARRAY(sa.Text)),
        sa.Column("impact", sa.Text),
        sa.Column("has_data", sa.Boolean),
        sa.Column(
            "data_conflicts",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "image_forensics",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("document_type", sa.String(20), nullable=False, server_default=sa.text("'news'")),
        sa.Column(
            "doc_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("score", sa.Numeric(3, 2)),
        sa.Column("quality_score", sa.Numeric(3, 2)),
        sa.Column("sentiment", sa.String(10)),
        sa.Column("sentiment_score", sa.Numeric(3, 2)),
        sa.Column(
            "primary_emotion",
            postgresql.ENUM(
                "乐观",
                "振奋",
                "兴奋",
                "期待",
                "平静",
                "客观",
                "担忧",
                "悲观",
                "愤怒",
                "恐慌",
                name="emotion_type",
                create_type=False,
            ),
        ),
        sa.Column("emotion_targets", postgresql.ARRAY(sa.Text)),
        sa.Column("credibility_score", sa.Numeric(3, 2)),
        sa.Column("source_credibility", sa.Numeric(3, 2)),
        sa.Column("cross_verification", sa.Numeric(3, 2)),
        sa.Column("content_check_score", sa.Numeric(3, 2)),
        sa.Column("credibility_flags", postgresql.ARRAY(sa.Text)),
        sa.Column("verified_by_sources", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "persist_status",
            postgresql.ENUM(
                "pending",
                "processing",
                "pg_done",
                "neo4j_done",
                "neo4j_failed",
                "failed",
                name="persist_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("task_id", postgresql.UUID(as_uuid=True)),
        sa.Column("processing_stage", sa.String(50)),
        sa.Column("processing_error", sa.Text),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("prompt_versions", postgresql.JSONB),
        sa.Column("publish_time", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Migrate data back
    op.execute("""
        INSERT INTO articles
        SELECT
            c.id, c.source_url, c.source_host, a.is_news, c.title,
            COALESCE(b.body, ''), c.category, c.language, c.region,
            c.merged_into, c.is_merged, c.merged_source_ids,
            b.summary, a.event_time, a.subjects, a.key_data, a.impact, a.has_data,
            a.data_conflicts, a.image_forensics,
            c.document_type, c.doc_metadata, c.content_hash, c.version,
            c.score, a.quality_score, a.sentiment, c.sentiment_score,
            a.primary_emotion, a.emotion_targets,
            c.credibility_score, a.source_credibility, a.cross_verification,
            a.content_check_score, a.credibility_flags, a.verified_by_sources,
            c.persist_status, c.task_id, c.processing_stage, c.processing_error,
            c.retry_count, a.prompt_versions, c.publish_time, c.created_at, c.updated_at
        FROM articles_core c
        LEFT JOIN article_bodies b ON c.id = b.article_id
        LEFT JOIN article_analysis a ON c.id = a.article_id
    """)

    # Redirect FKs back to articles
    op.drop_constraint("article_vectors_article_id_fkey", "article_vectors", type_="foreignkey")
    op.create_foreign_key(
        "article_vectors_article_id_fkey",
        "article_vectors",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("llm_failures_article_id_fkey", "llm_failures", type_="foreignkey")
    op.create_foreign_key(
        "llm_failures_article_id_fkey",
        "llm_failures",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("pending_sync_article_id_fkey", "pending_sync", type_="foreignkey")
    op.create_foreign_key(
        "pending_sync_article_id_fkey",
        "pending_sync",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "daily_briefing_items_article_id_fkey", "daily_briefing_items", type_="foreignkey"
    )
    op.create_foreign_key(
        "daily_briefing_items_article_id_fkey",
        "daily_briefing_items",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Drop split tables
    op.drop_table("article_analysis")
    op.drop_table("article_bodies")
    op.drop_table("articles_core")
