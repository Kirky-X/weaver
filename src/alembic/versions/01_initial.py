# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Consolidated initial migration - all tables and indexes

Revision ID: 01_initial
Revises: None
Create Date: 2026-04-06

This migration consolidates all previous migrations into a single file:
- 01_initial, 02_llm_failures, 03_remove_article_entities (skipped - dead code)
- 04_source_credibility, 05_drop_orphan_tables (skipped - cleanup only)
- 05_pending_sync, f23755e6c748, 06_llm_usage
- f26c1d1ee6c3 (empty merge), 07_prompt_templates, ac3bc88e1858 (column rename)

Final schema: 13 tables, 4 ENUM types, vector indexes.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = sa.LargeBinary

revision: str = "01_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables, indexes, and custom types."""
    # === ENUM TYPES ===
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE category_type AS ENUM ('政治', '军事', '经济', '科技', '社会', '文化', '体育', '国际');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE persist_status AS ENUM ('pending', 'processing', 'pg_done', 'neo4j_done', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE emotion_type AS ENUM ('乐观', '振奋', '期待', '平静', '客观', '担忧', '悲观', '愤怒', '恐慌');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE vector_type AS ENUM ('title', 'content');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    category_type = postgresql.ENUM(
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
    )
    persist_status = postgresql.ENUM(
        "pending",
        "processing",
        "pg_done",
        "neo4j_done",
        "failed",
        name="persist_status",
        create_type=False,
    )
    emotion_type = postgresql.ENUM(
        "乐观",
        "振奋",
        "期待",
        "平静",
        "客观",
        "担忧",
        "悲观",
        "愤怒",
        "恐慌",
        name="emotion_type",
        create_type=False,
    )
    vector_type = postgresql.ENUM("title", "content", name="vector_type", create_type=False)

    # === ARTICLES ===
    op.create_table(
        "articles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_url", sa.Text(), nullable=False, unique=True),
        sa.Column("source_host", sa.String(200), nullable=True),
        sa.Column("is_news", sa.Boolean(), nullable=False, default=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", category_type, nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("region", sa.String(50), nullable=True),
        sa.Column(
            "merged_into",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id"),
            nullable=True,
        ),
        sa.Column("is_merged", sa.Boolean(), nullable=False, default=False),
        sa.Column(
            "merged_source_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subjects", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("key_data", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("has_data", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Numeric(3, 2), nullable=True),
        sa.Column("sentiment", sa.String(10), nullable=True),
        sa.Column("sentiment_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("primary_emotion", emotion_type, nullable=True),
        sa.Column("emotion_targets", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("credibility_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("source_credibility", sa.Numeric(3, 2), nullable=True),
        sa.Column("cross_verification", sa.Numeric(3, 2), nullable=True),
        sa.Column("content_check_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("credibility_flags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("verified_by_sources", sa.Integer(), nullable=False, default=0),
        sa.Column("persist_status", persist_status, nullable=False, server_default="pending"),
        sa.Column("prompt_versions", postgresql.JSONB, nullable=True),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("processing_stage", sa.String(50), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="chk_score_range"),
        sa.CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1", name="chk_quality_score_range"
        ),
        sa.CheckConstraint(
            "sentiment_score >= 0 AND sentiment_score <= 1", name="chk_sentiment_score_range"
        ),
        sa.CheckConstraint(
            "credibility_score >= 0 AND credibility_score <= 1", name="chk_credibility_score_range"
        ),
        sa.CheckConstraint("merged_into IS DISTINCT FROM id", name="chk_no_self_merge"),
    )

    op.create_index("idx_articles_category", "articles", ["category"])
    op.create_index(
        "idx_articles_publish_time", "articles", [sa.literal_column("publish_time DESC")]
    )
    op.create_index("idx_articles_score", "articles", [sa.literal_column("score DESC")])
    op.create_index(
        "idx_articles_credibility", "articles", [sa.literal_column("credibility_score DESC")]
    )
    op.create_index(
        "idx_articles_sentiment_score", "articles", [sa.literal_column("sentiment_score DESC")]
    )
    op.create_index("idx_articles_primary_emotion", "articles", ["primary_emotion"])
    op.create_index("idx_articles_merged_into", "articles", ["merged_into"])
    op.create_index(
        "idx_articles_category_publish",
        "articles",
        ["category", sa.literal_column("publish_time DESC")],
    )
    op.create_index(
        "idx_articles_host_publish",
        "articles",
        ["source_host", sa.literal_column("publish_time DESC")],
    )
    op.create_index(
        "idx_articles_persist_status",
        "articles",
        ["persist_status"],
        postgresql_where=sa.text("persist_status IN ('pending', 'pg_done')"),
    )
    op.create_index(
        "idx_articles_status_created",
        "articles",
        ["persist_status", sa.literal_column("created_at ASC")],
    )
    op.create_index("idx_articles_task_status", "articles", ["task_id", "persist_status"])

    # === ARTICLE_VECTORS ===
    op.create_table(
        "article_vectors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vector_type", vector_type, nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column(
            "model_id", sa.String(64), nullable=False, server_default="text-embedding-3-large"
        ),
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
    op.create_index("idx_av_unique", "article_vectors", ["article_id", "vector_type"], unique=True)

    m = int(os.getenv("HNSW_M", "16"))
    ef_construction = int(os.getenv("HNSW_EF_CONSTRUCTION", "64"))

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_article_vectors_hnsw
        ON article_vectors USING hnsw (embedding vector_cosine_ops)
        WITH (m = {m}, ef_construction = {ef_construction});
    """)

    # === ENTITY_VECTORS ===
    op.create_table(
        "entity_vectors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("neo4j_id", sa.String(100), nullable=False, unique=True),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column(
            "model_id", sa.String(64), nullable=False, server_default="text-embedding-3-large"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_entity_vectors_hnsw
        ON entity_vectors USING hnsw (embedding vector_cosine_ops)
        WITH (m = {m}, ef_construction = {ef_construction});
    """)

    # === SOURCE_AUTHORITIES ===
    op.create_table(
        "source_authorities",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("host", sa.String(200), nullable=False, unique=True),
        sa.Column("authority", sa.Numeric(3, 2), nullable=False, default=0.50),
        sa.Column("tier", sa.Integer(), nullable=False, default=3),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, default=True),
        sa.Column("auto_score", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # === LLM_FAILURES ===
    op.create_table(
        "llm_failures",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("call_point", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("latency_ms", postgresql.NUMERIC(precision=10, scale=2), nullable=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_tried", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_llm_failures_created", "llm_failures", ["created_at"])
    op.create_index("idx_llm_failures_article", "llm_failures", ["article_id"])
    op.create_index("idx_llm_failures_call_point", "llm_failures", ["call_point"])
    op.create_index("idx_llm_failures_provider", "llm_failures", ["provider"])

    # === SOURCES ===
    op.create_table(
        "sources",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="rss"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("per_host_concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("credibility", sa.Numeric(3, 2), nullable=True),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("last_crawl_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.String(200), nullable=True),
        sa.Column("last_modified", sa.String(100), nullable=True),
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
        sa.CheckConstraint(
            "credibility >= 0 AND credibility <= 1", name="chk_sources_credibility_range"
        ),
        sa.CheckConstraint("tier >= 1 AND tier <= 3", name="chk_sources_tier_range"),
    )
    op.create_index("idx_sources_host", "sources", [sa.text("url")])
    op.create_index("idx_sources_enabled", "sources", ["enabled"])

    # === PENDING_SYNC ===
    op.create_table(
        "pending_sync",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sync_type", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_pending_sync_article_id", "pending_sync", ["article_id"])
    op.create_index("idx_pending_sync_status", "pending_sync", ["status"])
    op.create_index("idx_pending_sync_created_at", "pending_sync", ["created_at"])

    # === RELATION_TYPES ===
    op.create_table(
        "relation_types",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("name_en", sa.String(50), nullable=False, unique=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("is_symmetric", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_relation_types_category", "relation_types", ["category"])
    op.create_index("idx_relation_types_is_active", "relation_types", ["is_active"])

    # === RELATION_TYPE_ALIASES ===
    op.create_table(
        "relation_type_aliases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("alias", sa.String(100), nullable=False),
        sa.Column(
            "relation_type_id",
            sa.BigInteger(),
            sa.ForeignKey("relation_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_unique_constraint(
        "uq_alias_relation_type", "relation_type_aliases", ["alias", "relation_type_id"]
    )
    op.create_index("idx_aliases_relation_type_id", "relation_type_aliases", ["relation_type_id"])
    op.create_index("idx_aliases_alias", "relation_type_aliases", ["alias"])

    # === UNKNOWN_RELATION_TYPES ===
    op.create_table(
        "unknown_relation_types",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("raw_type", sa.String(100), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_unknown_raw_type", "unknown_relation_types", ["raw_type"])
    op.create_index("idx_unknown_resolved", "unknown_relation_types", ["resolved"])
    op.create_index("idx_unknown_hit_count", "unknown_relation_types", ["hit_count"])

    # === LLM_USAGE_RAW ===
    op.create_table(
        "llm_usage_raw",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("call_point", sa.String(100), nullable=False),
        sa.Column("llm_type", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("article_id", sa.BigInteger(), nullable=True),
        sa.Column("task_id", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_llm_usage_raw_created_at", "llm_usage_raw", ["created_at"])
    op.create_index("ix_llm_usage_raw_label", "llm_usage_raw", ["label"])

    # === LLM_USAGE_HOURLY ===
    op.create_table(
        "llm_usage_hourly",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("time_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("call_point", sa.String(100), nullable=False),
        sa.Column("llm_type", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_avg_ms", sa.Float(), nullable=False),
        sa.Column("latency_min_ms", sa.Float(), nullable=False),
        sa.Column("latency_max_ms", sa.Float(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_unique_constraint(
        "uq_llm_usage_hourly", "llm_usage_hourly", ["time_bucket", "label", "call_point"]
    )
    op.create_index("ix_llm_usage_hourly_time_bucket", "llm_usage_hourly", ["time_bucket"])
    op.create_index("ix_llm_usage_hourly_provider", "llm_usage_hourly", ["provider"])
    op.create_index("ix_llm_usage_hourly_model", "llm_usage_hourly", ["model"])

    # === PROMPT_TEMPLATES ===
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("prompt_type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("prompt_metadata", sa.dialects.postgresql.JSONB(), nullable=True),
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
        sa.Column("created_by", sa.String(100), nullable=False, server_default="system"),
    )
    op.create_unique_constraint("uq_prompt_name_version", "prompt_templates", ["name", "version"])
    op.create_index("idx_prompt_templates_name", "prompt_templates", ["name"])
    op.create_index(
        "idx_prompt_templates_created_at", "prompt_templates", [sa.text("created_at DESC")]
    )


def downgrade() -> None:
    """Drop all tables, indexes, and custom types."""
    # Drop in reverse order
    op.drop_index("idx_prompt_templates_created_at", table_name="prompt_templates")
    op.drop_index("idx_prompt_templates_name", table_name="prompt_templates")
    op.drop_constraint("uq_prompt_name_version", "prompt_templates")
    op.drop_table("prompt_templates")

    op.drop_index("ix_llm_usage_hourly_model", table_name="llm_usage_hourly")
    op.drop_index("ix_llm_usage_hourly_provider", table_name="llm_usage_hourly")
    op.drop_index("ix_llm_usage_hourly_time_bucket", table_name="llm_usage_hourly")
    op.drop_constraint("uq_llm_usage_hourly", "llm_usage_hourly")
    op.drop_table("llm_usage_hourly")

    op.drop_index("ix_llm_usage_raw_label", table_name="llm_usage_raw")
    op.drop_index("ix_llm_usage_raw_created_at", table_name="llm_usage_raw")
    op.drop_table("llm_usage_raw")

    op.drop_index("idx_unknown_hit_count", table_name="unknown_relation_types")
    op.drop_index("idx_unknown_resolved", table_name="unknown_relation_types")
    op.drop_index("idx_unknown_raw_type", table_name="unknown_relation_types")
    op.drop_table("unknown_relation_types")

    op.drop_index("idx_aliases_alias", table_name="relation_type_aliases")
    op.drop_index("idx_aliases_relation_type_id", table_name="relation_type_aliases")
    op.drop_constraint("uq_alias_relation_type", "relation_type_aliases")
    op.drop_table("relation_type_aliases")

    op.drop_index("idx_relation_types_is_active", table_name="relation_types")
    op.drop_index("idx_relation_types_category", table_name="relation_types")
    op.drop_table("relation_types")

    op.drop_index("idx_pending_sync_created_at", table_name="pending_sync")
    op.drop_index("idx_pending_sync_status", table_name="pending_sync")
    op.drop_index("idx_pending_sync_article_id", table_name="pending_sync")
    op.drop_table("pending_sync")

    op.drop_index("idx_sources_enabled", table_name="sources")
    op.drop_index("idx_sources_host", table_name="sources")
    op.drop_table("sources")

    op.drop_index("idx_llm_failures_provider", table_name="llm_failures")
    op.drop_index("idx_llm_failures_call_point", table_name="llm_failures")
    op.drop_index("idx_llm_failures_article", table_name="llm_failures")
    op.drop_index("idx_llm_failures_created", table_name="llm_failures")
    op.drop_table("llm_failures")

    op.drop_table("source_authorities")

    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_entity_vectors_hnsw;")
    op.drop_table("entity_vectors")

    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_article_vectors_hnsw;")
    op.drop_index("idx_av_unique", table_name="article_vectors")
    op.drop_table("article_vectors")

    op.drop_index("idx_articles_task_status", table_name="articles")
    op.drop_index("idx_articles_status_created", table_name="articles")
    op.drop_index("idx_articles_persist_status", table_name="articles")
    op.drop_index("idx_articles_host_publish", table_name="articles")
    op.drop_index("idx_articles_category_publish", table_name="articles")
    op.drop_index("idx_articles_merged_into", table_name="articles")
    op.drop_index("idx_articles_primary_emotion", table_name="articles")
    op.drop_index("idx_articles_sentiment_score", table_name="articles")
    op.drop_index("idx_articles_credibility", table_name="articles")
    op.drop_index("idx_articles_score", table_name="articles")
    op.drop_index("idx_articles_publish_time", table_name="articles")
    op.drop_index("idx_articles_category", table_name="articles")
    op.drop_table("articles")

    op.execute("DROP TYPE IF EXISTS vector_type")
    op.execute("DROP TYPE IF EXISTS emotion_type")
    op.execute("DROP TYPE IF EXISTS persist_status")
    op.execute("DROP TYPE IF EXISTS category_type")
