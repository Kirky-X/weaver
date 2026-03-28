# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4j config toggle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Neo4jSettings


class TestNeo4jSettingsEnabled:
    """Test Neo4jSettings.enabled field."""

    def test_enabled_default_true(self):
        """Test enabled defaults to True."""
        settings = Neo4jSettings()
        assert settings.enabled is True

    def test_enabled_from_env(self):
        """Test enabled can be set from environment variable."""
        with patch.dict("os.environ", {"NEO4J_ENABLED": "false"}):
            settings = Neo4jSettings()
            assert settings.enabled is False

    def test_enabled_from_env_true(self):
        """Test enabled=true from environment variable."""
        with patch.dict("os.environ", {"NEO4J_ENABLED": "true"}):
            settings = Neo4jSettings()
            assert settings.enabled is True


class TestContainerNeo4jToggle:
    """Test Container startup skips Neo4j init when disabled."""

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
    async def test_startup_skips_neo4j_when_disabled(self, mock_settings):
        """Test startup() skips init_neo4j() when neo4j.enabled=False."""
        from container import Container

        container = Container()
        container.configure(mock_settings)

        # Mock all init methods to isolate neo4j init call
        container.init_postgres = AsyncMock()
        container.init_redis = AsyncMock()
        container.init_llm = AsyncMock()
        container.init_search_engines = MagicMock(return_value=None)
        container.init_playwright_pool = AsyncMock()
        container.init_smart_fetcher = AsyncMock()

        # Mock source scheduler to avoid needing real processor
        mock_scheduler = MagicMock()
        container._source_scheduler = mock_scheduler
        container.init_source_scheduler = AsyncMock(return_value=mock_scheduler)

        # Mock pipeline to avoid complex setup
        mock_pipeline_instance = MagicMock()
        container._pipeline = mock_pipeline_instance
        container.init_pipeline = AsyncMock(return_value=mock_pipeline_instance)

        container._llm_failure_repo = MagicMock()
        container._event_bus = MagicMock()
        container._llm_failure_cleanup_thread = MagicMock()

        with patch("core.db.initializer.initialize_database", new_callable=AsyncMock):
            with patch.object(Container, "init_neo4j", new_callable=AsyncMock) as mock_init_neo4j:
                await container.startup()

        # init_neo4j should NOT be called when disabled
        mock_init_neo4j.assert_not_called()

    @pytest.mark.asyncio
    async def test_startup_calls_neo4j_when_enabled(self, mock_settings_enabled):
        """Test startup() calls init_neo4j() when neo4j.enabled=True."""
        from container import Container

        container = Container()
        container.configure(mock_settings_enabled)

        # Mock all init methods to isolate neo4j init call
        container.init_postgres = AsyncMock()
        container.init_redis = AsyncMock()
        container.init_llm = AsyncMock()
        container.init_search_engines = MagicMock(return_value=None)
        container.init_playwright_pool = AsyncMock()
        container.init_smart_fetcher = AsyncMock()

        # Mock source scheduler to avoid needing real processor
        mock_scheduler = MagicMock()
        container._source_scheduler = mock_scheduler
        container.init_source_scheduler = AsyncMock(return_value=mock_scheduler)

        # Mock pipeline to avoid complex setup
        mock_pipeline_instance = MagicMock()
        container._pipeline = mock_pipeline_instance
        container.init_pipeline = AsyncMock(return_value=mock_pipeline_instance)

        container._llm_failure_repo = MagicMock()
        container._event_bus = MagicMock()
        container._llm_failure_cleanup_thread = MagicMock()

        with patch("core.db.initializer.initialize_database", new_callable=AsyncMock):
            with patch.object(Container, "init_neo4j", new_callable=AsyncMock) as mock_init_neo4j:
                await container.startup()

        # init_neo4j SHOULD be called when enabled
        mock_init_neo4j.assert_called_once()
