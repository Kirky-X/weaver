# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Refactor persist_status enum to backend-agnostic state machine.

Revision ID: 02_refactor_persist_status
Revises: 01_initial
Create Date: 2026-04-25

Changes:
- Replace persist_status enum: (pending, processing, pg_done, neo4j_done, neo4j_failed, failed)
  with: (pending, processing, stored, enriching, complete, failed)
- Map data: pg_done→stored, neo4j_done→complete, neo4j_failed→failed
- Change merged_source_ids from UUID[] to TEXT[] (store source URLs)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "02_refactor_persist_status"
down_revision: str | None = "01_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Refactor persist_status enum and merged_source_ids column."""
    # Step 1: Drop dependent index before type change
    op.execute("DROP INDEX IF EXISTS idx_articles_persist_status;")
    op.execute("DROP INDEX IF EXISTS idx_articles_status_created;")
    op.execute("DROP INDEX IF EXISTS idx_articles_task_status;")
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status DROP DEFAULT;")

    # Step 2: Convert to TEXT
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status TYPE text;")

    # Step 3: Map old values to new values
    op.execute("UPDATE articles SET persist_status = 'stored' WHERE persist_status = 'pg_done';")
    op.execute(
        "UPDATE articles SET persist_status = 'complete' WHERE persist_status = 'neo4j_done';"
    )
    op.execute(
        "UPDATE articles SET persist_status = 'failed' WHERE persist_status = 'neo4j_failed';"
    )

    # Step 3: Create new enum type
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE persist_status_v2 AS ENUM (
                'pending', 'processing', 'stored', 'enriching', 'complete', 'failed'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Step 4: Alter column to new enum type
    op.execute("""
        ALTER TABLE articles
        ALTER COLUMN persist_status TYPE persist_status_v2
        USING persist_status::persist_status_v2;
    """)

    # Step 5: Drop old enum type
    op.execute("DROP TYPE IF EXISTS persist_status CASCADE;")

    # Step 6: Rename new enum to original name
    op.execute("ALTER TYPE persist_status_v2 RENAME TO persist_status;")

    # Step 7: Restore default value
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status SET DEFAULT 'pending';")

    # Step 8: Change merged_source_ids from UUID[] to TEXT[]
    op.execute("""
        ALTER TABLE articles
        ALTER COLUMN merged_source_ids TYPE text[]
        USING merged_source_ids::text[];
    """)


def downgrade() -> None:
    """Revert to old persist_status enum and UUID[] type."""
    # Step 1: Convert to TEXT
    op.execute("ALTER TABLE articles ALTER COLUMN persist_status TYPE text;")
    # Step 2: Map new values back
    op.execute("UPDATE articles SET persist_status = 'pg_done' WHERE persist_status = 'stored';")
    op.execute("UPDATE articles SET persist_status = 'pg_done' WHERE persist_status = 'enriching';")
    op.execute(
        "UPDATE articles SET persist_status = 'neo4j_done' WHERE persist_status = 'complete';"
    )
    # Step 3: Create old enum type
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE persist_status_old AS ENUM (
                'pending', 'processing', 'pg_done', 'neo4j_done', 'neo4j_failed', 'failed'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    # Step 4: Alter column to old enum
    op.execute("""
        ALTER TABLE articles ALTER COLUMN persist_status TYPE persist_status_old
        USING persist_status::persist_status_old;
    """)
    # Step 5: Drop new enum type
    op.execute("DROP TYPE IF EXISTS persist_status CASCADE;")
    # Step 6: Rename old enum back
    op.execute("ALTER TYPE persist_status_old RENAME TO persist_status;")
    # Step 7: Revert merged_source_ids
    op.execute("""
        ALTER TABLE articles ALTER COLUMN merged_source_ids TYPE uuid[]
        USING merged_source_ids::uuid[];
    """)
