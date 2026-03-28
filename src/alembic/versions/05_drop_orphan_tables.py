# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Drop orphan tables that have no code references

Revision ID: 05_drop_orphan_tables
Revises: 04_source_credibility
Create Date: 2026-03-28

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "05_drop_orphan_tables"
down_revision: Union[str, None] = "04_source_credibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop orphan tables with no code references."""
    op.execute("DROP TABLE IF EXISTS api_keys CASCADE")
    op.execute("DROP TABLE IF EXISTS arbitration_records CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS community_summaries CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_registry CASCADE")
    op.execute("DROP TABLE IF EXISTS multimodal_files CASCADE")


def downgrade() -> None:
    """Recreate orphan tables for rollback."""
    op.execute("""
        CREATE TABLE api_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id VARCHAR NOT NULL,
            key_hash VARCHAR NOT NULL,
            key_prefix VARCHAR NOT NULL,
            scopes VARCHAR[] DEFAULT '{read,write}',
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT now(),
            revoked_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            description TEXT
        )
    """)
    op.execute("""
        CREATE TABLE arbitration_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_a_id VARCHAR NOT NULL,
            entity_b_id VARCHAR NOT NULL,
            result VARCHAR NOT NULL,
            confidence NUMERIC(3, 2),
            reasoning TEXT,
            decided_by VARCHAR,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL,
            event_data JSONB,
            trace_id UUID,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE community_summaries (
            community_id VARCHAR PRIMARY KEY,
            summary TEXT,
            node_ids UUID[],
            entity_ids VARCHAR[],
            size INTEGER,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE entity_registry (
            entity_id VARCHAR PRIMARY KEY,
            entity_type VARCHAR NOT NULL,
            canonical_name VARCHAR NOT NULL,
            aliases VARCHAR[],
            description TEXT,
            properties JSONB,
            confidence NUMERIC(3, 2),
            merge_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE multimodal_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id VARCHAR NOT NULL,
            file_name VARCHAR NOT NULL,
            file_type VARCHAR NOT NULL,
            file_size BIGINT,
            bucket VARCHAR NOT NULL,
            object_path VARCHAR NOT NULL,
            compressed BOOLEAN DEFAULT false,
            access_count INTEGER DEFAULT 0,
            last_accessed_at TIMESTAMPTZ,
            is_deleted BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
