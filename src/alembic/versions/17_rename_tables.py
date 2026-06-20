# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Rename tables: sources → source_configs, llm_failures → llm_failure_records.

Revision ID: 17_rename_tables
Revises: 16_update_check_constraints_and_enum
Create Date: 2026-06-11

Changes:
- Rename table sources → source_configs
- Rename constraints chk_sources_* → chk_source_configs_*
- Rename indexes idx_sources_* → idx_source_configs_*
- Rename table llm_failures → llm_failure_records
- Rename indexes idx_llm_failures_* → idx_llm_failure_records_*
- Rename sequence llm_failures_id_seq → llm_failure_records_id_seq
"""

from collections.abc import Sequence

from alembic import op

revision: str = "17_rename_tables"
down_revision: str | None = "16_update_check_constraints_and_enum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename tables and related objects."""
    # ── sources → source_configs ──
    op.rename_table("sources", "source_configs")

    # Rename constraints
    op.execute(
        "ALTER TABLE source_configs RENAME CONSTRAINT chk_sources_credibility_range "
        "TO chk_source_configs_credibility_range"
    )
    op.execute(
        "ALTER TABLE source_configs RENAME CONSTRAINT chk_sources_tier_range "
        "TO chk_source_configs_tier_range"
    )
    op.execute(
        "ALTER TABLE source_configs RENAME CONSTRAINT chk_sources_interval_minutes_range "
        "TO chk_source_configs_interval_minutes_range"
    )

    # Rename indexes
    op.execute("ALTER INDEX idx_sources_host RENAME TO idx_source_configs_host")
    op.execute("ALTER INDEX idx_sources_enabled RENAME TO idx_source_configs_enabled")

    # ── llm_failures → llm_failure_records ──
    op.rename_table("llm_failures", "llm_failure_records")

    # Rename indexes
    op.execute("ALTER INDEX idx_llm_failures_created RENAME TO idx_llm_failure_records_created")
    op.execute("ALTER INDEX idx_llm_failures_article RENAME TO idx_llm_failure_records_article")
    op.execute(
        "ALTER INDEX idx_llm_failures_call_point RENAME TO idx_llm_failure_records_call_point"
    )
    op.execute("ALTER INDEX idx_llm_failures_provider RENAME TO idx_llm_failure_records_provider")

    # Rename sequence
    op.execute("ALTER SEQUENCE IF EXISTS llm_failures_id_seq RENAME TO llm_failure_records_id_seq")


def downgrade() -> None:
    """Revert table renames."""
    # ── llm_failure_records → llm_failures ──
    op.execute("ALTER SEQUENCE IF EXISTS llm_failure_records_id_seq RENAME TO llm_failures_id_seq")

    op.execute("ALTER INDEX idx_llm_failure_records_created RENAME TO idx_llm_failures_created")
    op.execute("ALTER INDEX idx_llm_failure_records_article RENAME TO idx_llm_failures_article")
    op.execute(
        "ALTER INDEX idx_llm_failure_records_call_point RENAME TO idx_llm_failures_call_point"
    )
    op.execute("ALTER INDEX idx_llm_failure_records_provider RENAME TO idx_llm_failures_provider")

    op.rename_table("llm_failure_records", "llm_failures")

    # ── source_configs → sources ──
    op.execute("ALTER INDEX idx_source_configs_host RENAME TO idx_sources_host")
    op.execute("ALTER INDEX idx_source_configs_enabled RENAME TO idx_sources_enabled")

    op.execute(
        "ALTER TABLE source_configs RENAME CONSTRAINT chk_source_configs_interval_minutes_range "
        "TO chk_sources_interval_minutes_range"
    )
    op.execute(
        "ALTER TABLE source_configs RENAME CONSTRAINT chk_source_configs_tier_range "
        "TO chk_sources_tier_range"
    )
    op.execute(
        "ALTER TABLE source_configs RENAME CONSTRAINT chk_source_configs_credibility_range "
        "TO chk_sources_credibility_range"
    )

    op.rename_table("source_configs", "sources")
