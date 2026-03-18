"""Add HNSW indexes to vector tables

Revision ID: e283f4aed36a
Revises: c619ab9ba95a
Create Date: 2026-03-18

"""
import os
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e283f4aed36a'
down_revision: Union[str, None] = 'c619ab9ba95a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create HNSW indexes for vector similarity search.

    Uses CONCURRENTLY to avoid blocking production operations.
    Parameters can be tuned via environment variables:
    - HNSW_M: max connections per node (default: 16)
    - HNSW_EF_CONSTRUCTION: candidate list size during construction (default: 64)

    For large datasets (>5M rows), consider:
    - HNSW_M=32 (more connections for better recall)
    - HNSW_EF_CONSTRUCTION=128 (larger candidate list)
    """
    # Get parameters from environment or use defaults
    m = int(os.getenv('HNSW_M', '16'))
    ef_construction = int(os.getenv('HNSW_EF_CONSTRUCTION', '64'))

    # Create HNSW index on article_vectors
    # Note: CONCURRENTLY cannot be used inside a transaction block
    op.execute(f"""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_article_vectors_hnsw
        ON article_vectors
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {m}, ef_construction = {ef_construction});
    """)

    # Create HNSW index on entity_vectors
    op.execute(f"""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_vectors_hnsw
        ON entity_vectors
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {m}, ef_construction = {ef_construction});
    """)


def downgrade() -> None:
    """Remove HNSW indexes."""
    op.execute("""
        DROP INDEX CONCURRENTLY IF EXISTS idx_entity_vectors_hnsw;
    """)
    op.execute("""
        DROP INDEX CONCURRENTLY IF EXISTS idx_article_vectors_hnsw;
    """)