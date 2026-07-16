# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for database optimization indexes (Task 5).

Tests verify that the required optimization indexes exist on the
articles_core and article_analysis tables as specified in the
Weaver-数据库设计文档 §9.2.
"""

from __future__ import annotations

from sqlalchemy import inspect


class TestArticleCoreOptimizationIndexes:
    """Tests for optimization indexes on articles_core table."""

    def test_idx_articles_sentiment_time_exists(self):
        """Test idx_articles_sentiment_time partial index exists.

        Required by design doc §9.2 #1: sentiment_score + publish_time DESC
        WHERE sentiment_score IS NOT NULL
        """
        from core.db.models import ArticleCore

        index_names = {idx.name for idx in ArticleCore.__table__.indexes}
        assert "idx_articles_sentiment_time" in index_names

    def test_idx_articles_sentiment_time_is_partial(self):
        """Test idx_articles_sentiment_time has WHERE clause."""
        from core.db.models import ArticleCore

        for idx in ArticleCore.__table__.indexes:
            if idx.name == "idx_articles_sentiment_time":
                assert idx.dialect_options.get("postgresql", {}).get("where") is not None
                break

    def test_idx_articles_briefing_exists(self):
        """Test idx_articles_briefing partial index exists.

        Required by design doc §9.2 #2: publish_time DESC + score DESC
        WHERE score IS NOT NULL
        """
        from core.db.models import ArticleCore

        index_names = {idx.name for idx in ArticleCore.__table__.indexes}
        assert "idx_articles_briefing" in index_names

    def test_idx_articles_briefing_is_partial(self):
        """Test idx_articles_briefing has WHERE clause."""
        from core.db.models import ArticleCore

        for idx in ArticleCore.__table__.indexes:
            if idx.name == "idx_articles_briefing":
                where = idx.dialect_options.get("postgresql", {}).get("where")
                assert where is not None
                break

    def test_idx_articles_category_sentiment_exists(self):
        """Test idx_articles_category_sentiment partial index exists.

        Required by design doc §9.2 #3: category + sentiment_score DESC
        WHERE category IS NOT NULL AND sentiment_score IS NOT NULL
        """
        from core.db.models import ArticleCore

        index_names = {idx.name for idx in ArticleCore.__table__.indexes}
        assert "idx_articles_category_sentiment" in index_names

    def test_idx_articles_url_lookup_exists(self):
        """Test idx_articles_url_lookup covering index exists.

        Required by design doc §9.2 #5: source_url INCLUDE (id, title, publish_time)
        """
        from core.db.models import ArticleCore

        index_names = {idx.name for idx in ArticleCore.__table__.indexes}
        assert "idx_articles_url_lookup" in index_names

    def test_idx_articles_retry_exists(self):
        """Test idx_articles_retry partial index exists.

        Required by design doc §9.2 #6: persist_status + updated_at ASC
        WHERE persist_status IN ('pg_done', 'neo4j_failed', 'failed')
        """
        from core.db.models import ArticleCore

        index_names = {idx.name for idx in ArticleCore.__table__.indexes}
        assert "idx_articles_retry" in index_names

    def test_idx_articles_retry_is_partial(self):
        """Test idx_articles_retry has WHERE clause for Saga recovery."""
        from core.db.models import ArticleCore

        for idx in ArticleCore.__table__.indexes:
            if idx.name == "idx_articles_retry":
                where = idx.dialect_options.get("postgresql", {}).get("where", "")
                where_text = str(where)
                assert "pg_done" in where_text
                assert "neo4j_failed" in where_text
                assert "failed" in where_text
                break


class TestArticleAnalysisIndexes:
    """Tests for indexes on article_analysis table."""

    def test_idx_articles_is_news_exists(self):
        """Test idx_articles_is_news partial index exists on article_analysis.

        Required by design doc §9.2 #4: publish_time DESC WHERE is_news = true.
        Note: is_news is in article_analysis after vertical split, so this
        index must be on article_analysis, not articles_core.
        """
        from core.db.models import ArticleAnalysis

        index_names = {idx.name for idx in ArticleAnalysis.__table__.indexes}
        assert "idx_articles_is_news" in index_names

    def test_idx_articles_is_news_is_partial(self):
        """Test idx_articles_is_news has WHERE is_news = true clause."""
        from core.db.models import ArticleAnalysis

        for idx in ArticleAnalysis.__table__.indexes:
            if idx.name == "idx_articles_is_news":
                where = idx.dialect_options.get("postgresql", {}).get("where", "")
                assert "is_news" in str(where)
                break


class TestEntityVectorIndexes:
    """Tests for HNSW vector index on entity_vectors."""

    def test_entity_vectors_has_hnsw_index(self):
        """Test that entity_vectors has HNSW index on embedding column.

        Required by design doc §8.1: both vector tables need HNSW indexes.
        """
        from core.db.models import EntityVector

        index_names = {idx.name for idx in EntityVector.__table__.indexes}
        assert "idx_entity_vectors_hnsw" in index_names


class TestDailyBriefingItemIndexes:
    """Tests for indexes on daily_briefing_items table."""

    def test_briefing_items_unique_article_constraint(self):
        """Test UNIQUE(briefing_id, article_id) exists on daily_briefing_items.

        Required by design doc §12.2.
        """
        from core.db.models import DailyBriefingItem

        constraint_names = set()
        for constraint in DailyBriefingItem.__table__.constraints:
            if hasattr(constraint, "name"):
                constraint_names.add(constraint.name)
        assert "uq_briefing_item_article" in constraint_names

    def test_briefing_items_unique_rank_constraint(self):
        """Test UNIQUE(briefing_id, rank) exists on daily_briefing_items.

        Required by design doc §12.2.
        """
        from core.db.models import DailyBriefingItem

        constraint_names = set()
        for constraint in DailyBriefingItem.__table__.constraints:
            if hasattr(constraint, "name"):
                constraint_names.add(constraint.name)
        assert "uq_briefing_item_rank" in constraint_names
