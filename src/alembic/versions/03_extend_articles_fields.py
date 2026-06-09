# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Extend articles table with 6 new fields + PersistStatus data migration.

Revision ID: 03_extend_articles_fields
Revises: 02_refactor_persist_status
Create Date: 2026-06-09

Changes:
- Add data_conflicts JSONB DEFAULT '[]'
- Add image_forensics JSONB DEFAULT '[]'
- Add document_type VARCHAR(20) DEFAULT 'news'
- Add doc_metadata JSONB DEFAULT '{}'
- Add content_hash VARCHAR(64)
- Add version INTEGER DEFAULT 1
- Data migration: stored->pg_done, complete->neo4j_done
- Clean up persist_status enum (remove stored, complete)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "03_extend_articles_fields"
down_revision: str | None = "02_refactor_persist_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend articles table and clean up PersistStatus enum."""
    # Step 1: Add 6 new columns to articles
    op.add_column(
        "articles",
        sa.Column(
            "data_conflicts",
            postgresql.JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "articles",
        sa.Column(
            "image_forensics",
            postgresql.JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "articles",
        sa.Column("document_type", sa.String(20), server_default=sa.text("'news'"), nullable=False),
    )
    op.add_column(
        "articles",
        sa.Column(
            "doc_metadata", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.add_column("articles", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column(
        "articles", sa.Column("version", sa.Integer, server_default=sa.text("1"), nullable=False)
    )

    # Step 2: Drop indexes that reference persist_status
    op.execute("DROP INDEX IF EXISTS idx_articles_persist_status;")
    op.execute("DROP INDEX IF EXISTS idx_articles_status_created;")
    op.execute("DROP INDEX IF EXISTS idx_articles_task_status;")
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status DROP DEFAULT;")

    # Step 3: Convert to TEXT
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status TYPE text;")

    # Step 4: Map stored->pg_done, complete->neo4j_done
    op.execute("UPDATE articles SET persist_status = 'pg_done' WHERE persist_status = 'stored';")
    op.execute(
        "UPDATE articles SET persist_status = 'neo4j_done' WHERE persist_status = 'complete';"
    )

    # Step 5: Create new enum type (only 6 values)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE persist_status_v3 AS ENUM (
                'pending', 'processing', 'pg_done', 'neo4j_done', 'neo4j_failed', 'failed'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)

    # Step 6: Alter column to new enum type
    op.execute("""
        ALTER TABLE articles ALTER COLUMN persist_status TYPE persist_status_v3
        USING persist_status::persist_status_v3;
    """)

    # Step 7: Drop old enum
    op.execute("DROP TYPE IF EXISTS persist_status CASCADE;")

    # Step 8: Rename new enum
    op.execute("ALTER TYPE persist_status_v3 RENAME TO persist_status;")

    # Step 9: Restore default
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status SET DEFAULT 'pending';")

    # Step 10: Recreate indexes
    op.execute("""
        CREATE INDEX idx_articles_persist_status ON articles (persist_status)
        WHERE persist_status IN ('pending', 'pg_done');
    """)
    op.execute(
        "CREATE INDEX idx_articles_status_created ON articles (persist_status, created_at ASC);"
    )
    op.execute("CREATE INDEX idx_articles_task_status ON articles (task_id, persist_status);")


def downgrade() -> None:
    """Revert articles fields and PersistStatus enum changes."""
    # Remove new columns
    op.drop_column("articles", "version")
    op.drop_column("articles", "content_hash")
    op.drop_column("articles", "doc_metadata")
    op.drop_column("articles", "document_type")
    op.drop_column("articles", "image_forensics")
    op.drop_column("articles", "data_conflicts")

    # Revert persist_status
    op.execute("DROP INDEX IF EXISTS idx_articles_persist_status;")
    op.execute("DROP INDEX IF EXISTS idx_articles_status_created;")
    op.execute("DROP INDEX IF EXISTS idx_articles_task_status;")
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status DROP DEFAULT;")
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status TYPE text;")

    # Map back
    op.execute("UPDATE articles SET persist_status = 'stored' WHERE persist_status = 'pg_done';")
    op.execute(
        "UPDATE articles SET persist_status = 'complete' WHERE persist_status = 'neo4j_done';"
    )

    # Create old enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE persist_status_v2 AS ENUM (
                'pending', 'processing', 'stored', 'enriching', 'complete', 'failed'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
        ALTER TABLE articles ALTER COLUMN persist_status TYPE persist_status_v2
        USING persist_status::persist_status_v2;
    """)
    op.execute("DROP TYPE IF EXISTS persist_status CASCADE;")
    op.execute("ALTER TYPE persist_status_v2 RENAME TO persist_status;")
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status SET DEFAULT 'pending';")
