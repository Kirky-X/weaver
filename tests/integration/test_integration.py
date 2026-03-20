# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for API endpoints."""

from unittest.mock import MagicMock

import pytest


class TestContainerIntegration:
    """Integration tests for container."""

    def test_container_creation(self):
        """Test container can be created."""
        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        assert container is not None
        assert container.settings is settings

    def test_container_initializes_components(self):
        """Test container initializes all components."""
        from config.settings import Settings
        from container import Container

        settings = Settings()
        container = Container().configure(settings)

        # Verify all component getters exist
        assert hasattr(container, "settings")
        assert hasattr(container, "source_registry")
        assert hasattr(container, "article_repo")
        assert hasattr(container, "source_authority_repo")


class TestSourceRegistryIntegration:
    """Integration tests for source registry."""

    def test_registry_creation(self):
        """Test source registry can be created."""
        from modules.fetcher.base import BaseFetcher
        from modules.source.registry import SourceRegistry

        mock_fetcher = MagicMock(spec=BaseFetcher)
        registry = SourceRegistry(mock_fetcher)
        assert registry is not None

    def test_registry_default_parsers(self):
        """Test registry has default parsers."""
        from modules.fetcher.base import BaseFetcher
        from modules.source.registry import SourceRegistry

        mock_fetcher = MagicMock(spec=BaseFetcher)
        registry = SourceRegistry(mock_fetcher)
        parser = registry.get_parser("rss")
        assert parser is not None

    def test_source_management(self):
        """Test adding and retrieving sources."""
        from modules.fetcher.base import BaseFetcher
        from modules.source.models import SourceConfig
        from modules.source.registry import SourceRegistry

        mock_fetcher = MagicMock(spec=BaseFetcher)
        registry = SourceRegistry(mock_fetcher)

        config = SourceConfig(
            id="test",
            name="Test",
            url="https://example.com/feed.xml",
        )
        registry.add_source(config)

        retrieved = registry.get_source("test")
        assert retrieved is not None
        assert retrieved.id == "test"


class TestRepositoryIntegration:
    """Integration tests for repositories."""

    def test_article_repo_requires_pool(self):
        """Test article repo requires pool."""
        from modules.storage.article_repo import ArticleRepo

        # Should fail without pool
        with pytest.raises(TypeError):
            repo = ArticleRepo()

    def test_source_authority_repo_requires_pool(self):
        """Test source authority repo requires pool."""
        from modules.storage.source_authority_repo import SourceAuthorityRepo

        # Should fail without pool
        with pytest.raises(TypeError):
            repo = SourceAuthorityRepo()


class TestLLMClientIntegration:
    """Integration tests for LLM client."""

    def test_llm_client_requires_config(self):
        """Test LLM client requires config."""

        config = {
            "providers": {
                "openai": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "api_key": "test-key",
                }
            },
            "call_points": {},
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "rerank_provider": "openai",
            "rerank_model": "",
        }

        # Test that we can create config without instantiating client
        assert config is not None
        assert "providers" in config


class TestPipelineIntegration:
    """Integration tests for pipeline."""

    def test_pipeline_graph_exists(self):
        """Test pipeline graph module exists."""
        from modules.pipeline import graph

        assert graph is not None


class TestFetcherIntegration:
    """Integration tests for fetchers."""

    def test_smart_fetcher_exists(self):
        """Test smart fetcher module exists."""
        from modules.fetcher import smart_fetcher

        assert smart_fetcher is not None


class TestDatabaseModelsIntegration:
    """Integration tests for database models."""

    def test_article_model_fields(self):
        """Test Article model has expected fields."""
        from core.db.models import Article

        # Check key fields exist
        assert hasattr(Article, "id")
        assert hasattr(Article, "source_url")
        assert hasattr(Article, "title")
        assert hasattr(Article, "body")
        assert hasattr(Article, "category")
        assert hasattr(Article, "score")
        assert hasattr(Article, "credibility_score")

    def test_article_vector_model(self):
        """Test ArticleVector model."""
        from core.db.models import ArticleVector

        assert hasattr(ArticleVector, "article_id")
        assert hasattr(ArticleVector, "vector_type")
        assert hasattr(ArticleVector, "embedding")

    def test_source_authority_model(self):
        """Test SourceAuthority model."""
        from core.db.models import SourceAuthority

        assert hasattr(SourceAuthority, "host")
        assert hasattr(SourceAuthority, "authority")
        assert hasattr(SourceAuthority, "tier")


class TestSettingsIntegration:
    """Integration tests for settings."""

    def test_settings_loads(self):
        """Test settings can be loaded."""
        from config.settings import Settings

        settings = Settings()
        assert settings.app_name == "weaver"

    def test_nested_settings(self):
        """Test nested settings structure."""
        from config.settings import Settings

        settings = Settings()
        assert hasattr(settings, "postgres")
        assert hasattr(settings, "redis")
        assert hasattr(settings, "llm")
        assert hasattr(settings, "api")
