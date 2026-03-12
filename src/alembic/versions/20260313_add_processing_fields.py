"""Add processing tracking fields

Revision ID: 20260313
Revises: 001_initial
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260313'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # First, check if we need to add PROCESSING to persist_status enum
    # The existing enum uses lowercase values: pending, pg_done, neo4j_done, failed
    # We need to add 'processing' (lowercase to match existing pattern)

    # Add PROCESSING to persist_status enum
    op.execute("""
        ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'processing'
    """)

    # Add processing tracking columns to articles table
    op.add_column('articles', sa.Column('processing_stage', sa.String(50), nullable=True))
    op.add_column('articles', sa.Column('processing_error', sa.Text(), nullable=True))
    op.add_column('articles', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))

    # Create indexes for the new columns
    op.create_index('idx_articles_processing_stage', 'articles', ['processing_stage'])
    op.create_index('idx_articles_retry_count', 'articles', ['retry_count'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_articles_retry_count', table_name='articles')
    op.drop_index('idx_articles_processing_stage', table_name='articles')

    # Drop columns
    op.drop_column('articles', 'retry_count')
    op.drop_column('articles', 'processing_error')
    op.drop_column('articles', 'processing_stage')

    # Note: We cannot remove enum values in PostgreSQL,
    # so we leave the 'processing' value in the enum type
