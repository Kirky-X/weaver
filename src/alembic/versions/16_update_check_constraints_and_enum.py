# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Update CHECK constraint values and add 兴奋 to emotion_type ENUM.

Revision ID: 16_update_check_constraints_and_enum
Revises: 15_add_rotated_to_field
Create Date: 2026-06-11

Changes:
- articles_core: update document_type CHECK to match design doc values
- sentiment_shifts: update shift_type CHECK to match design doc values
- emotion_type ENUM: add 兴奋 value
"""

from collections.abc import Sequence

from alembic import op

revision: str = "16_update_check_constraints_and_enum"
down_revision: str | None = "15_add_rotated_to_field"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update CHECK constraints and add ENUM value."""
    # ── articles_core: update document_type CHECK ──
    op.execute("ALTER TABLE articles_core DROP CONSTRAINT IF EXISTS chk_core_document_type")
    op.execute(
        "ALTER TABLE articles_core ADD CONSTRAINT chk_core_document_type "
        "CHECK (document_type IN ('news', 'policy', 'tweet', 'wechat', 'blog', 'report', 'pdf_doc', 'social_post'))"
    )

    # ── sentiment_shifts: update shift_type CHECK ──
    op.execute("ALTER TABLE sentiment_shifts DROP CONSTRAINT IF EXISTS chk_shift_type_values")
    op.execute(
        "ALTER TABLE sentiment_shifts ADD CONSTRAINT chk_shift_type_values "
        "CHECK (shift_type IN ('mean_shift', 'cumulative_drift', 'variance_change'))"
    )

    # ── emotion_type ENUM: add 兴奋 ──
    op.execute("ALTER TYPE emotion_type ADD VALUE IF NOT EXISTS '兴奋'")


def downgrade() -> None:
    """Revert CHECK constraints (ENUM value cannot be removed in PostgreSQL)."""
    # ── articles_core: revert document_type CHECK ──
    op.execute("ALTER TABLE articles_core DROP CONSTRAINT IF EXISTS chk_core_document_type")
    op.execute(
        "ALTER TABLE articles_core ADD CONSTRAINT chk_core_document_type "
        "CHECK (document_type IN ('news', 'social', 'official', 'research', 'opinion'))"
    )

    # ── sentiment_shifts: revert shift_type CHECK ──
    op.execute("ALTER TABLE sentiment_shifts DROP CONSTRAINT IF EXISTS chk_shift_type_values")
    op.execute(
        "ALTER TABLE sentiment_shifts ADD CONSTRAINT chk_shift_type_values "
        "CHECK (shift_type IN ('abrupt', 'gradual'))"
    )

    # Note: PostgreSQL does not support removing ENUM values
