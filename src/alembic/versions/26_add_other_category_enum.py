# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add '其他' value to category_type ENUM for terminal articles.

Revision ID: 26_add_other_category_enum
Revises: 25_add_source_id_to_articles
Create Date: 2026-07-17

Changes:
- Add '其他' (other) to category_type ENUM
- Required for mark_terminal_by_url which sets fallback category='其他'
  for non-news articles (is_news=False)
- Without this, PostgreSQL rejects category='other' with
  InvalidTextRepresentationError: invalid input value for enum category_type

Bug: Pipeline silently failed on terminal articles because category="other"
was not a valid ENUM value (only 政治/军事/经济/科技/社会/文化/体育/国际).
The error was swallowed by _handle_terminal_states try/except, causing
pipeline to report "completed" with total_processed=0.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "26_add_other_category_enum"
down_revision: str | None = "25_add_source_id_to_articles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add '其他' value to category_type ENUM.

    PostgreSQL ALTER TYPE ... ADD VALUE must run outside a transaction.
    """
    op.execute("ALTER TYPE category_type ADD VALUE IF NOT EXISTS '其他'")


def downgrade() -> None:
    """Remove '其他' value from category_type ENUM.

    Note: PostgreSQL does not support removing ENUM values.
    The value will remain in the type but is safe to leave.
    """
    # PostgreSQL cannot remove ENUM values; downgrade is a no-op.
    # To fully remove, recreate the type without '其他'.
    pass
