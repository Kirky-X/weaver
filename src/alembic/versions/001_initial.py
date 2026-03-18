# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Initial migration - create all tables

Revision ID: 001_initial
Revises:
Create Date: 2024-01-01 00:00:00

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Import pgvector Vector type
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # Fallback for when pgvector is not installed
    Vector = sa.LargeBinary

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types using DO blocks for PostgreSQL compatibility
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE category_type AS ENUM ('政治', '军事', '经济', '科技', '社会', '文化', '体育', '国际');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE persist_status AS ENUM ('pending', 'pg_done', 'neo4j_done', 'failed');
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

    # Create pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Reference enum types for column definitions (create_type=False since we created them above)
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
        "pending", "pg_done", "neo4j_done", "failed", name="persist_status", create_type=False
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

    # Create articles table
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
        sa.CheckConstraint("score >= 0 AND score <= 1", name="chk_score_range"),
        sa.CheckConstraint(
            "sentiment_score >= 0 AND sentiment_score <= 1", name="chk_sentiment_score_range"
        ),
        sa.CheckConstraint(
            "credibility_score >= 0 AND credibility_score <= 1", name="chk_credibility_score_range"
        ),
        sa.CheckConstraint("merged_into IS DISTINCT FROM id", name="chk_no_self_merge"),
    )

    # Create indexes for articles
    op.create_index("idx_articles_category", "articles", ["category"])
    op.create_index("idx_articles_publish_time", "articles", ["publish_time"])
    op.create_index("idx_articles_score", "articles", ["score"])
    op.create_index("idx_articles_credibility", "articles", ["credibility_score"])
    op.create_index("idx_articles_sentiment_score", "articles", ["sentiment_score"])
    op.create_index("idx_articles_primary_emotion", "articles", ["primary_emotion"])
    op.create_index("idx_articles_merged_into", "articles", ["merged_into"])

    # Create article_vectors table
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
    )
    op.create_index("idx_av_unique", "article_vectors", ["article_id", "vector_type"], unique=True)

    # Create entity_vectors table
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

    # Create source_authorities table
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

    # Create article_entities junction table
    op.create_table(
        "article_entities",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("neo4j_id", sa.String(100), nullable=False),
        sa.Column("entity_name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("role", sa.String(100), nullable=True),
    )
    op.create_index("idx_ae_article", "article_entities", ["article_id"])
    op.create_index("idx_ae_neo4j", "article_entities", ["neo4j_id"])


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("article_entities")
    op.drop_table("source_authorities")
    op.drop_table("entity_vectors")
    op.drop_table("article_vectors")
    op.drop_table("articles")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS vector_type")
    op.execute("DROP TYPE IF EXISTS emotion_type")
    op.execute("DROP TYPE IF EXISTS persist_status")
    op.execute("DROP TYPE IF EXISTS category_type")
