# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Add relation_types, relation_type_aliases, and unknown_relation_types tables

Revision ID: f23755e6c748
Revises: 04_source_credibility
Create Date: 2026-03-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f23755e6c748"
down_revision: str | None = "04_source_credibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create relation_types table
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

    # Create relation_type_aliases table
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

    # Create unknown_relation_types table
    op.create_table(
        "unknown_relation_types",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("raw_type", sa.String(100), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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


def downgrade() -> None:
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
