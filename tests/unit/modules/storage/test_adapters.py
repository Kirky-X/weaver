# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.storage module exports and patterns."""

import pytest


class TestStorageInitExports:
    """Test that __init__.py exports are available."""

    def test_import_article_repo(self):
        from modules.storage import ArticleRepo

        assert ArticleRepo is not None

    def test_import_neo4j_article_repo(self):
        from modules.storage import Neo4jArticleRepo

        assert Neo4jArticleRepo is not None

    def test_import_neo4j_entity_repo(self):
        from modules.storage import Neo4jEntityRepo

        assert Neo4jEntityRepo is not None

    def test_import_vector_repo(self):
        from modules.storage import VectorRepo

        assert VectorRepo is not None

    def test_import_pending_sync_repo(self):
        from modules.storage import PendingSyncRepo

        assert PendingSyncRepo is not None

    def test_import_source_authority_repo(self):
        from modules.storage import SourceAuthorityRepo

        assert SourceAuthorityRepo is not None

    def test_all_exports_count(self):
        from modules.storage import __all__

        assert len(__all__) == 11

    def test_all_exports_match(self):
        from modules.storage import __all__

        expected = [
            "ArticleRepo",
            "BaseEntityRepo",
            "DuckDBLLMUsageRepo",
            "GraphRepository",
            "LadybugArticleRepo",
            "LadybugEntityRepo",
            "Neo4jArticleRepo",
            "Neo4jEntityRepo",
            "PendingSyncRepo",
            "SourceAuthorityRepo",
            "VectorRepo",
        ]
        assert sorted(__all__) == sorted(expected)


class TestStorageAdaptersModule:
    """Test the adapters sub-module with extended exports."""

    def test_adapters_all_exports(self):
        from modules.storage.adapters import __all__

        assert "ArticleRepo" in __all__
        assert "ArticleRepository" in __all__
        assert "DuckDBArticleRepo" in __all__
        assert "GraphRepository" in __all__
        assert "VectorRepository" in __all__
        assert "EntityRepository" in __all__

    def test_adapters_re_exports_protocols(self):
        from modules.storage.adapters import (
            ArticleRepository,
            EntityRepository,
            VectorRepository,
        )

        assert ArticleRepository is not None
        assert EntityRepository is not None
        assert VectorRepository is not None

    def test_adapters_re_exports_duckdb(self):
        from modules.storage.adapters import (
            DuckDBArticleRepo,
            DuckDBLLMUsageRepo,
            DuckDBSourceAuthorityRepo,
        )

        assert DuckDBArticleRepo is not None
        assert DuckDBLLMUsageRepo is not None
        assert DuckDBSourceAuthorityRepo is not None


class TestRepositoryPatterns:
    """Test repository pattern usage."""

    def test_article_repo_exists(self):
        from modules.storage import ArticleRepo

        assert ArticleRepo is not None

    def test_vector_repo_exists(self):
        from modules.storage import VectorRepo

        assert VectorRepo is not None

    def test_graph_repo_has_expected_methods(self):
        from modules.storage.graph_repo import GraphRepository

        assert hasattr(GraphRepository, "get_entity")
        assert hasattr(GraphRepository, "get_article")
        assert hasattr(GraphRepository, "get_related_articles")
        assert hasattr(GraphRepository, "get_visualization_nodes")

    def test_neo4j_entity_repo_exists(self):
        from modules.storage import Neo4jEntityRepo

        assert Neo4jEntityRepo is not None


class TestProtocolCompliance:
    """Test that implementations come from correct modules."""

    def test_article_repo_from_correct_module(self):
        from modules.storage.postgres.article_repo import ArticleRepo

        assert ArticleRepo.__module__ == "modules.storage.postgres.article_repo"

    def test_vector_repo_from_correct_module(self):
        from modules.storage.postgres.vector_repo import VectorRepo

        assert VectorRepo.__module__ == "modules.storage.postgres.vector_repo"

    def test_article_repository_from_protocols(self):
        from core.protocols.repositories import ArticleRepository

        assert ArticleRepository.__module__ == "core.protocols.repositories"

    def test_entity_repository_from_protocols(self):
        from core.protocols.repositories import EntityRepository

        assert EntityRepository.__module__ == "core.protocols.repositories"

    def test_vector_repository_from_protocols(self):
        from core.protocols.repositories import VectorRepository

        assert VectorRepository.__module__ == "core.protocols.repositories"

    def test_duckdb_article_repo_from_correct_module(self):
        from modules.storage.duckdb import DuckDBArticleRepo

        # DuckDBArticleRepo is a re-export of ArticleRepo from postgres module
        assert DuckDBArticleRepo.__module__ == "modules.storage.postgres.article_repo"

    def test_graph_repository_from_correct_module(self):
        from modules.storage.graph_repo import GraphRepository

        assert GraphRepository.__module__ == "modules.storage.graph_repo"

    def test_neo4j_article_repo_from_correct_module(self):
        from modules.storage.neo4j import Neo4jArticleRepo

        assert Neo4jArticleRepo.__module__.startswith("modules.storage.neo4j")

    def test_neo4j_entity_repo_from_correct_module(self):
        from modules.storage.neo4j import Neo4jEntityRepo

        assert Neo4jEntityRepo.__module__.startswith("modules.storage.neo4j")
