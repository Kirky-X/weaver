"""merge_multiple_heads

Revision ID: f26c1d1ee6c3
Revises: 05_drop_orphan_tables, 05_pending_sync, 06_llm_usage
Create Date: 2026-03-30 09:01:49.534501

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "f26c1d1ee6c3"
down_revision: str | None = ("05_drop_orphan_tables", "05_pending_sync", "06_llm_usage")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
