# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Remove article_entities table (dead code - was never written to).

Revision ID: 03_remove_article_entities
Revises: 02_llm_failures
Create Date: 2026-03-20

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "03_remove_article_entities"
down_revision: Union[str, None] = "02_llm_failures"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("article_entities")


def downgrade() -> None:
    op.create_table(
        "article_entities",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            sa.UUID(as_uuid=True),
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
