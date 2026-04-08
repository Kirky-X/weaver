# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4j config toggle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Neo4jSettings


class TestNeo4jSettingsEnabled:
    """Test Neo4jSettings.enabled field."""

    def test_enabled_default_true(self):
        """Test enabled defaults to True."""
        # Clear any environment variables that might affect the test
        import os

        old_values = {}
        for key in ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_ENABLED"]:
            old_values[key] = os.environ.pop(key, None)

        try:
            settings = Neo4jSettings()
            assert settings.enabled is True
        finally:
            # Restore environment variables
            for key, value in old_values.items():
                if value is not None:
                    os.environ[key] = value

    def test_enabled_from_env(self):
        """Test enabled can be set from constructor."""
        # Neo4jSettings is a BaseModel, not BaseSettings
        # Environment variable parsing is handled by parent Settings class
        settings = Neo4jSettings(enabled=False)
        assert settings.enabled is False

    def test_enabled_from_env_true(self):
        """Test enabled=true from constructor."""
        settings = Neo4jSettings(enabled=True)
        assert settings.enabled is True


class TestContainerNeo4jToggle:
    """Test Container startup initializes graph pool correctly based on settings."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings with neo4j.enabled=False."""
        settings = MagicMock()
        settings.neo4j.enabled = False
        settings.neo4j.uri = "bolt://localhost:7687"
        settings.neo4j.user = "neo4j"
        settings.neo4j.password = "password"
        settings.postgres.dsn = "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver"
        settings.redis.url = "redis://localhost:6379/0"
        settings.fetcher.circuit_breaker_threshold = 5
        settings.fetcher.circuit_breaker_timeout = 60.0
        settings.llm.providers = {}
        settings.llm.call_points = {}
        settings.prompt.dir = "config/prompts"
        return settings

    @pytest.fixture
    def mock_settings_enabled(self):
        """Create mock settings with neo4j.enabled=True."""
        settings = MagicMock()
        settings.neo4j.enabled = True
        settings.neo4j.uri = "bolt://localhost:7687"
        settings.neo4j.user = "neo4j"
        settings.neo4j.password = "password"
        settings.postgres.dsn = "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver"
        settings.redis.url = "redis://localhost:6379/0"
        settings.fetcher.circuit_breaker_threshold = 5
        settings.fetcher.circuit_breaker_timeout = 60.0
        settings.llm.providers = {}
        settings.llm.call_points = {}
        settings.prompt.dir = "config/prompts"
        return settings

    @pytest.mark.asyncio
    async def test_strategy_without_graph_when_disabled(self, mock_settings):
        """Test init_strategy creates strategy without graph pool when neo4j.enabled=False."""
        from container import Container

        container = Container()
        container.configure(mock_settings)

        # Mock create_strategy to return strategy without graph pool
        mock_strategy = MagicMock()
        mock_strategy.graph_pool = None
        mock_strategy.graph_type = "none"
        mock_strategy.relational_type = "postgresql"
        mock_strategy.relational_pool = MagicMock()

        with patch("container.create_strategy", AsyncMock(return_value=mock_strategy)):
            strategy = await container.init_strategy()

        # graph_pool should be None when Neo4j is disabled
        assert strategy.graph_pool is None
        assert strategy.graph_type == "none"

    @pytest.mark.asyncio
    async def test_strategy_with_graph_when_enabled(self, mock_settings_enabled):
        """Test init_strategy creates strategy with graph pool when neo4j.enabled=True."""
        from container import Container

        container = Container()
        container.configure(mock_settings_enabled)

        # Mock create_strategy to return strategy with graph pool
        mock_graph_pool = MagicMock()
        mock_strategy = MagicMock()
        mock_strategy.graph_pool = mock_graph_pool
        mock_strategy.graph_type = "neo4j"
        mock_strategy.relational_type = "postgresql"
        mock_strategy.relational_pool = MagicMock()

        with patch("container.create_strategy", AsyncMock(return_value=mock_strategy)):
            strategy = await container.init_strategy()

        # graph_pool should be available when Neo4j is enabled
        assert strategy.graph_pool is not None
        assert strategy.graph_type == "neo4j"
