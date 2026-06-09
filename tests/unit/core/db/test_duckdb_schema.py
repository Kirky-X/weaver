# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DuckDB schema definitions in duckdb_schema.py."""

from __future__ import annotations

from core.db.duckdb_schema import SCHEMA_QUERIES


class TestDuckDBSchemaArticles:
    """Tests for articles table schema."""

    @classmethod
    def setup_class(cls):
        cls.articles_ddl = SCHEMA_QUERIES[1]

    def test_articles_table_has_data_conflicts(self):
        assert "data_conflicts JSON" in self.articles_ddl
        assert "data_conflicts JSON DEFAULT '[]'" in self.articles_ddl

    def test_articles_table_has_image_forensics(self):
        assert "image_forensics JSON" in self.articles_ddl
        assert "image_forensics JSON DEFAULT '[]'" in self.articles_ddl

    def test_articles_table_has_document_type(self):
        assert "document_type VARCHAR" in self.articles_ddl
        assert "document_type VARCHAR DEFAULT 'news'" in self.articles_ddl

    def test_articles_table_has_doc_metadata(self):
        assert "doc_metadata JSON" in self.articles_ddl
        assert "doc_metadata JSON DEFAULT '{}'" in self.articles_ddl

    def test_articles_table_has_content_hash(self):
        assert "content_hash VARCHAR" in self.articles_ddl

    def test_articles_table_has_version(self):
        assert "version INTEGER" in self.articles_ddl
        assert "version INTEGER DEFAULT 1" in self.articles_ddl

    def test_articles_table_has_score_unchanged(self):
        assert "score DECIMAL" in self.articles_ddl

    def test_articles_table_new_fields_before_score(self):
        score_pos = self.articles_ddl.index("score DECIMAL")
        version_pos = self.articles_ddl.index("version INTEGER")
        doc_meta_pos = self.articles_ddl.index("doc_metadata JSON")
        doc_type_pos = self.articles_ddl.index("document_type VARCHAR")
        forensics_pos = self.articles_ddl.index("image_forensics JSON")
        conflicts_pos = self.articles_ddl.index("data_conflicts JSON")
        assert conflicts_pos < score_pos
        assert forensics_pos < score_pos
        assert doc_type_pos < score_pos
        assert doc_meta_pos < score_pos
        assert version_pos < score_pos

    def test_articles_table_new_fields_after_has_data(self):
        has_data_pos = self.articles_ddl.index("has_data BOOLEAN")
        conflicts_pos = self.articles_ddl.index("data_conflicts JSON")
        assert conflicts_pos > has_data_pos

    def test_all_six_new_columns_present(self):
        columns = [
            "data_conflicts JSON",
            "image_forensics JSON",
            "document_type VARCHAR",
            "doc_metadata JSON",
            "content_hash VARCHAR",
            "version INTEGER",
        ]
        for col in columns:
            assert col in self.articles_ddl, f"Missing column: {col}"
