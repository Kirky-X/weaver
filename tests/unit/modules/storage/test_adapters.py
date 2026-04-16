# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.storage.adapters module."""

import pytest


class TestStorageAdaptersImports:
    """Test that all expected exports are available."""

    def test_import_article_repo(self):
        """Test ArticleRepo can be imported."""
        from modules.storage import ArticleRepo

        assert ArticleRepo is not None

    def test_import_neo4j_article_repo(self):
        """Test Neo4jArticleRepo can be imported."""
        from modules.storage import Neo4jArticleRepo

        assert Neo4jArticleRepo is not None

    def test_import_neo4j_entity_repo(self):
        """Test Neo4jEntityRepo can be imported."""
        from modules.storage import Neo4jEntityRepo

        assert Neo4jEntityRepo is not None

    def test_import_vector_repo(self):
        """Test VectorRepo can be imported."""
        from modules.storage import VectorRepo

        assert VectorRepo is not None

    def test_import_pending_sync_repo(self):
        """Test PendingSyncRepo can be imported."""
        from modules.storage import PendingSyncRepo

        assert PendingSyncRepo is not None

    def test_import_source_authority_repo(self):
        """Test SourceAuthorityRepo can be imported."""
        from modules.storage import SourceAuthorityRepo

        assert SourceAuthorityRepo is not None

    def test_import_graph_repository_from_module(self):
        """Test GraphRepository can be imported from graph_repo module."""
        from modules.storage.graph_repo import GraphRepository

        assert GraphRepository is not None

    def test_import_duckdb_article_repo_from_module(self):
        """Test DuckDBArticleRepo can be imported from duckdb module."""
        from modules.storage.duckdb import DuckDBArticleRepo

        assert DuckDBArticleRepo is not None


class TestStorageAdaptersAll:
    """Test __all__ list."""

    def test_all_exports_defined(self):
        """Test __all__ contains expected exports."""
        from modules.storage import __all__

        expected = [
            "ArticleRepo",
            "Neo4jArticleRepo",
            "Neo4jEntityRepo",
            "PendingSyncRepo",
            "SourceAuthorityRepo",
            "VectorRepo",
        ]

        for item in expected:
            assert item in __all__


class TestRepositoryPatterns:
    """Test repository pattern usage."""

    def test_article_repo_exists(self):
        """Test ArticleRepo class exists."""
        from modules.storage import ArticleRepo

        assert ArticleRepo is not None

    def test_vector_repo_exists(self):
        """Test VectorRepo class exists."""
        from modules.storage import VectorRepo

        assert VectorRepo is not None

    def test_graph_repo_has_expected_methods(self):
        """Test GraphRepository has expected methods."""
        from modules.storage.graph_repo import GraphRepository

        # Check key methods exist
        assert hasattr(GraphRepository, "get_entity")
        assert hasattr(GraphRepository, "get_article")
        assert hasattr(GraphRepository, "get_related_articles")
        assert hasattr(GraphRepository, "get_visualization_nodes")

    def test_neo4j_entity_repo_exists(self):
        """Test Neo4jEntityRepo class exists."""
        from modules.storage import Neo4jEntityRepo

        assert Neo4jEntityRepo is not None


class TestProtocolCompliance:
    """Test that implementations comply with protocols."""

    def test_article_repo_from_correct_module(self):
        """Test ArticleRepo is imported from postgres."""
        from modules.storage.postgres.article_repo import ArticleRepo

        assert ArticleRepo.__module__ == "modules.storage.postgres.article_repo"

    def test_vector_repo_from_correct_module(self):
        """Test VectorRepo is imported from postgres."""
        from modules.storage.postgres.vector_repo import VectorRepo

        assert VectorRepo.__module__ == "modules.storage.postgres.vector_repo"
