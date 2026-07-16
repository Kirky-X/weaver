# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Create security tables: audit_log, community_vectors.

Revision ID: 05_create_security_tables
Revises: 04_create_analytics_tables
Create Date: 2026-06-09

Changes:
- Create audit_log table for security event tracking
- Create community_vectors table with pgvector HNSW index
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

revision: str = "05_create_security_tables"
down_revision: str | None = "04_create_analytics_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create security tables: audit_log and community_vectors."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # === AUDIT_LOG ===
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.String(100), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", sa.String(100), nullable=True),
        sa.Column("detail", postgresql.JSONB, nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_audit_occurred", "audit_log", ["created_at"])
    op.create_index("idx_audit_key", "audit_log", ["key_id"])

    # === COMMUNITY_VECTORS ===
    op.create_table(
        "community_vectors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("community_id", sa.String(100), nullable=False, unique=True),
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

    # nosemgrep: python.sqlalchemy.security.audit sqlalchemy-execute-raw-query
    # Migration: HNSW index params from env vars (deployment controlled)
    m = int(os.getenv("HNSW_M", "16"))
    ef_construction = int(os.getenv("HNSW_EF_CONSTRUCTION", "200"))
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_community_vectors_hnsw
        ON community_vectors USING hnsw (embedding vector_cosine_ops)
        WITH (m = {m}, ef_construction = {ef_construction});
    """)


def downgrade() -> None:
    """Drop security tables."""
    op.execute("DROP INDEX IF EXISTS idx_community_vectors_hnsw;")
    op.drop_table("community_vectors")
    op.drop_index("idx_audit_key", table_name="audit_log")
    op.drop_index("idx_audit_occurred", table_name="audit_log")
    op.drop_table("audit_log")
