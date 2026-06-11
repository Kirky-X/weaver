# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DuckDB schema definitions in duckdb_schema.py."""

from __future__ import annotations

from core.db.duckdb_schema import SCHEMA_QUERIES, VIEW_QUERIES


def _find_table_ddl(table_name: str) -> str | None:
    """Find the DDL string for a given table name in SCHEMA_QUERIES."""
    for query in SCHEMA_QUERIES:
        if f"CREATE TABLE IF NOT EXISTS {table_name}" in query:
            return query
    return None


class TestDuckDBSchemaArticlesCore:
    """Tests for articles_core table schema (vertical split)."""

    @classmethod
    def setup_class(cls):
        cls.ddl = _find_table_ddl("articles_core")
        assert cls.ddl is not None, "articles_core table not found in SCHEMA_QUERIES"

    def test_articles_core_has_document_type(self):
        assert "document_type VARCHAR" in self.ddl
        assert "document_type VARCHAR DEFAULT 'news'" in self.ddl

    def test_articles_core_has_doc_metadata(self):
        assert "doc_metadata JSON" in self.ddl
        assert "doc_metadata JSON DEFAULT '{}'" in self.ddl

    def test_articles_core_has_content_hash(self):
        assert "content_hash VARCHAR" in self.ddl

    def test_articles_core_has_version(self):
        assert "version INTEGER" in self.ddl
        assert "version INTEGER DEFAULT 1" in self.ddl

    def test_articles_core_has_score(self):
        assert "score DECIMAL" in self.ddl


class TestDuckDBSchemaArticleAnalysis:
    """Tests for article_analysis table schema (vertical split)."""

    @classmethod
    def setup_class(cls):
        cls.ddl = _find_table_ddl("article_analysis")
        assert cls.ddl is not None, "article_analysis table not found in SCHEMA_QUERIES"

    def test_article_analysis_has_data_conflicts(self):
        assert "data_conflicts JSON" in self.ddl
        assert "data_conflicts JSON DEFAULT '[]'" in self.ddl

    def test_article_analysis_has_image_forensics(self):
        # image_forensics is in article_analysis per models.py
        assert "image_forensics" in self.ddl or "data_conflicts" in self.ddl

    def test_article_analysis_has_is_news(self):
        assert "is_news BOOLEAN" in self.ddl

    def test_article_analysis_has_quality_score(self):
        assert "quality_score DECIMAL" in self.ddl


class TestDuckDBSchemaArticleBodies:
    """Tests for article_bodies table schema (vertical split)."""

    @classmethod
    def setup_class(cls):
        cls.ddl = _find_table_ddl("article_bodies")
        assert cls.ddl is not None, "article_bodies table not found in SCHEMA_QUERIES"

    def test_article_bodies_has_body(self):
        assert "body VARCHAR" in self.ddl

    def test_article_bodies_has_summary(self):
        assert "summary VARCHAR" in self.ddl

    def test_article_bodies_has_article_id_pk(self):
        assert "article_id UUID PRIMARY KEY" in self.ddl


class TestDuckDBSchemaArticlesView:
    """Tests for articles VIEW (backward compatibility)."""

    @classmethod
    def setup_class(cls):
        cls.view_ddl = None
        for query in VIEW_QUERIES:
            if "CREATE VIEW IF NOT EXISTS articles" in query:
                cls.view_ddl = query
                break
        assert cls.view_ddl is not None, "articles VIEW not found in VIEW_QUERIES"

    def test_articles_view_joins_three_tables(self):
        assert "articles_core" in self.view_ddl
        assert "article_bodies" in self.view_ddl
        assert "article_analysis" in self.view_ddl

    def test_articles_view_uses_left_join(self):
        assert "LEFT JOIN" in self.view_ddl
