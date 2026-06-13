# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Extract processing tracking fields from articles_core to article_processing.

Revision ID: 21_extract_article_processing
Revises: 20_create_saga_logs
Create Date: 2026-06-13

Changes:
- Create article_processing table with task_id, processing_stage, processing_error, retry_count
- Migrate existing data from articles_core to article_processing
- Drop processing columns from articles_core
- Rebuild articles VIEW to JOIN article_processing
- Move idx_core_task_status index to article_processing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "21_extract_article_processing"
down_revision: str | None = "20_create_saga_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extract processing tracking fields from articles_core to article_processing."""
    # 1. Create article_processing table
    op.create_table(
        "article_processing",
        sa.Column(
            "article_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("articles_core.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("task_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("processing_stage", sa.String(50), nullable=True),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # 2. Create indexes on article_processing
    op.create_index("idx_processing_task_id", "article_processing", ["task_id"])
    op.create_index("idx_processing_stage", "article_processing", ["processing_stage"])
    op.create_index(
        "idx_processing_task_status", "article_processing", ["task_id", "processing_stage"]
    )

    # 3. Migrate existing data from articles_core to article_processing
    op.execute("""
        INSERT INTO article_processing (article_id, task_id, processing_stage, processing_error, retry_count, created_at, updated_at)
        SELECT id, task_id, processing_stage, processing_error, retry_count, created_at, updated_at
        FROM articles_core
        """)

    # 4. Drop old index on articles_core
    op.drop_index("idx_core_task_status", table_name="articles_core")

    # 5. Drop processing columns from articles_core
    op.drop_column("articles_core", "task_id")
    op.drop_column("articles_core", "processing_stage")
    op.drop_column("articles_core", "processing_error")
    op.drop_column("articles_core", "retry_count")

    # 6. Rebuild articles VIEW to JOIN article_processing
    op.execute("DROP VIEW IF EXISTS articles")
    op.execute("""
        CREATE VIEW articles AS
        SELECT
            c.id, c.source_url, c.source_host, c.title, c.category,
            c.language, c.region, c.score, c.sentiment_score,
            c.credibility_score, c.persist_status, c.publish_time,
            c.merged_into, c.is_merged, c.merged_source_ids,
            c.content_hash, c.version, c.document_type, c.doc_metadata,
            b.body, b.summary,
            a.is_news, a.subjects, a.key_data, a.impact, a.has_data,
            a.quality_score, a.sentiment, a.primary_emotion, a.emotion_targets,
            a.source_credibility, a.cross_verification, a.content_check_score,
            a.credibility_flags, a.verified_by_sources, a.data_conflicts,
            a.event_time, a.image_forensics, a.prompt_versions,
            p.task_id, p.processing_stage, p.processing_error, p.retry_count,
            c.created_at, c.updated_at
        FROM articles_core c
        LEFT JOIN article_bodies b ON b.article_id = c.id
        LEFT JOIN article_analysis a ON a.article_id = c.id
        LEFT JOIN article_processing p ON p.article_id = c.id
        """)

    # 7. Drop old task_status index on articles VIEW (no longer valid)
    # Note: VIEW indexes are not physical in PostgreSQL, this is handled by the ORM model


def downgrade() -> None:
    """Restore processing tracking fields to articles_core."""
    # 1. Add columns back to articles_core
    op.add_column("articles_core", sa.Column("task_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("articles_core", sa.Column("processing_stage", sa.String(50), nullable=True))
    op.add_column("articles_core", sa.Column("processing_error", sa.Text, nullable=True))
    op.add_column("articles_core", sa.Column("retry_count", sa.Integer, nullable=True))

    # 2. Migrate data back from article_processing
    op.execute("""
        UPDATE articles_core c
        SET task_id = p.task_id,
            processing_stage = p.processing_stage,
            processing_error = p.processing_error,
            retry_count = p.retry_count
        FROM article_processing p
        WHERE p.article_id = c.id
        """)

    # 3. Set default for retry_count where NULL
    op.execute("UPDATE articles_core SET retry_count = 0 WHERE retry_count IS NULL")
    op.alter_column("articles_core", "retry_count", nullable=False, server_default=sa.text("0"))

    # 4. Recreate index
    op.create_index("idx_core_task_status", "articles_core", ["task_id", "persist_status"])

    # 5. Rebuild articles VIEW without article_processing JOIN
    op.execute("DROP VIEW IF EXISTS articles")
    op.execute("""
        CREATE VIEW articles AS
        SELECT
            c.id, c.source_url, c.source_host, c.title, c.category,
            c.language, c.region, c.score, c.sentiment_score,
            c.credibility_score, c.persist_status, c.publish_time,
            c.merged_into, c.is_merged, c.merged_source_ids,
            c.content_hash, c.version, c.document_type, c.doc_metadata,
            c.task_id, c.processing_stage, c.processing_error, c.retry_count,
            b.body, b.summary,
            a.is_news, a.subjects, a.key_data, a.impact, a.has_data,
            a.quality_score, a.sentiment, a.primary_emotion, a.emotion_targets,
            a.source_credibility, a.cross_verification, a.content_check_score,
            a.credibility_flags, a.verified_by_sources, a.data_conflicts,
            a.event_time, a.image_forensics, a.prompt_versions,
            c.created_at, c.updated_at
        FROM articles_core c
        LEFT JOIN article_bodies b ON b.article_id = c.id
        LEFT JOIN article_analysis a ON a.article_id = c.id
        """)

    # 6. Drop article_processing table
    op.drop_index("idx_processing_task_status", table_name="article_processing")
    op.drop_index("idx_processing_stage", table_name="article_processing")
    op.drop_index("idx_processing_task_id", table_name="article_processing")
    op.drop_table("article_processing")
