# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add optimization indexes per design doc §9.2.

Revision ID: 12_add_optimization_indexes
Revises: 11_update_audit_log
Create Date: 2026-06-11

Changes per Weaver-数据库设计文档 §9.2:
- idx_articles_sentiment_time: partial index on articles_core
- idx_articles_briefing: partial index on articles_core
- idx_articles_category_sentiment: partial index on articles_core
- idx_articles_url_lookup: covering index on articles_core
- idx_articles_retry: partial index on articles_core for Saga recovery
- idx_articles_is_news: partial index on article_analysis
- idx_entity_vectors_hnsw: HNSW vector index on entity_vectors
- uq_briefing_item_article: unique constraint on daily_briefing_items
- uq_briefing_item_rank: unique constraint on daily_briefing_items
"""

from collections.abc import Sequence

from alembic import op

revision: str = "12_add_optimization_indexes"
down_revision: str | None = "11_update_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create optimization indexes using CONCURRENTLY to avoid lock contention."""
    # CONCURRENTLY cannot run inside a transaction block; use autocommit_block.
    # ── articles_core optimization indexes (design doc §9.2) ──
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_sentiment_time "
            "ON articles_core (sentiment_score, publish_time DESC) "
            "WHERE sentiment_score IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_briefing "
            "ON articles_core (publish_time DESC, score DESC) "
            "WHERE score IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_category_sentiment "
            "ON articles_core (category, sentiment_score DESC) "
            "WHERE category IS NOT NULL AND sentiment_score IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_url_lookup "
            "ON articles_core (source_url) INCLUDE (id, title, publish_time)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_retry "
            "ON articles_core (persist_status, updated_at ASC) "
            "WHERE persist_status IN ('pg_done', 'neo4j_failed', 'failed')"
        )

    # ── article_analysis index (is_news moved after vertical split) ──
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_is_news "
            "ON article_analysis (is_news) "
            "WHERE is_news = true"
        )

    # ── entity_vectors HNSW index (design doc §8.1) ──
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_vectors_hnsw "
            "ON entity_vectors USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 200)"
        )

    # ── daily_briefing_items unique constraints (design doc §12.2) ──
    op.create_unique_constraint(
        "uq_briefing_item_article",
        "daily_briefing_items",
        ["briefing_id", "article_id"],
    )
    op.create_unique_constraint(
        "uq_briefing_item_rank",
        "daily_briefing_items",
        ["briefing_id", "rank"],
    )


def downgrade() -> None:
    """Drop optimization indexes and unique constraints."""
    # ── daily_briefing_items constraints ──
    op.drop_constraint(
        "uq_briefing_item_rank",
        "daily_briefing_items",
        type_="unique",
    )
    op.drop_constraint(
        "uq_briefing_item_article",
        "daily_briefing_items",
        type_="unique",
    )

    # DROP INDEX CONCURRENTLY cannot run inside a transaction block.
    # ── entity_vectors HNSW index ──
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_entity_vectors_hnsw")

    # ── article_analysis index ──
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_is_news")

    # ── articles_core optimization indexes ──
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_retry")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_url_lookup")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_category_sentiment")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_briefing")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_sentiment_time")
