# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add source_id column to articles_core for source traceability.

Revision ID: 25_add_source_id_to_articles
Revises: 24_add_persist_status_enum_values
Create Date: 2026-06-25

Changes:
- Add source_id VARCHAR(100) column to articles_core (nullable, FK to source_configs.id)
- Recreate articles VIEW to include source_id
- Add index on source_id for filter performance

Background:
- Articles had no direct link to SourceConfig (only fuzzy host matching)
- API ?source_id= filter was silently ignored because the column didn't exist
- This migration establishes the proper relational link
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "25_add_source_id_to_articles"
down_revision: str | None = "24_add_persist_status_enum_values"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add source_id column to articles_core and rebuild articles VIEW."""
    # 1. Add source_id column to articles_core
    op.add_column(
        "articles_core",
        sa.Column("source_id", sa.String(100), nullable=True),
    )

    # 2. Add FK constraint to source_configs
    op.create_foreign_key(
        "fk_articles_core_source_id",
        "articles_core",
        "source_configs",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Add index for source_id filtering
    op.create_index(
        "idx_core_source_id",
        "articles_core",
        ["source_id"],
    )

    # 4. Drop and recreate articles VIEW to include source_id
    op.execute("DROP VIEW IF EXISTS articles")
    op.execute("""
        CREATE VIEW articles AS
        SELECT
            c.id, c.source_url, c.source_host, c.source_id, c.title, c.category,
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


def downgrade() -> None:
    """Remove source_id column and restore original articles VIEW."""
    # 1. Drop articles VIEW
    op.execute("DROP VIEW IF EXISTS articles")

    # 2. Drop FK constraint
    op.drop_constraint("fk_articles_core_source_id", "articles_core", type_="foreignkey")

    # 3. Drop index
    op.drop_index("idx_core_source_id", table_name="articles_core")

    # 4. Drop source_id column
    op.drop_column("articles_core", "source_id")

    # 5. Recreate articles VIEW without source_id
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
