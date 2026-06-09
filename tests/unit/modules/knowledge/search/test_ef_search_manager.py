# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for HNSW dynamic ef_search manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.ef_search_manager import (
    EfSearchConfig,
    EfSearchManager,
    SearchMode,
)


@pytest.fixture
def config() -> EfSearchConfig:
    """Default configuration for tests."""
    return EfSearchConfig()


@pytest.fixture
def manager(config: EfSearchConfig) -> EfSearchManager:
    """EfSearchManager instance with mocked pool."""
    pool = AsyncMock()
    return EfSearchManager(pool=pool, config=config)


class TestSearchMode:
    """Test SearchMode enum."""

    def test_search_modes_exist(self) -> None:
        """Test that all search modes are defined."""
        assert SearchMode.HYBRID == "hybrid"
        assert SearchMode.LOCAL == "local"
        assert SearchMode.GLOBAL == "global"
        assert SearchMode.DRIFT == "drift"
        assert SearchMode.LATENCY == "latency"


class TestEfSearchConfig:
    """Test EfSearchConfig defaults."""

    def test_default_config(self, config: EfSearchConfig) -> None:
        """Test that default config values are set correctly."""
        assert config.hybrid == 40
        assert config.local == 120
        assert config.global_value == 60
        assert config.drift == 80
        assert config.latency == 20

    def test_config_from_settings(self) -> None:
        """Test config loading from settings."""
        settings = MagicMock()
        settings.search.hnsw.ef_search.hybrid = 50
        settings.search.hnsw.ef_search.local = 150
        settings.search.hnsw.ef_search.global_value = 70
        settings.search.hnsw.ef_search.drift = 90
        settings.search.hnsw.ef_search.latency = 25

        config = EfSearchConfig.from_settings(settings)

        assert config.hybrid == 50
        assert config.local == 150
        assert config.global_value == 70
        assert config.drift == 90
        assert config.latency == 25


class TestEfSearchManager:
    """Test EfSearchManager functionality."""

    @pytest.mark.asyncio
    async def test_get_ef_search_hybrid(self, manager: EfSearchManager) -> None:
        """Test hybrid mode returns correct ef_search value."""
        value = manager.get_ef_search(SearchMode.HYBRID)
        assert value == 40

    @pytest.mark.asyncio
    async def test_get_ef_search_local(self, manager: EfSearchManager) -> None:
        """Test local mode returns correct ef_search value."""
        value = manager.get_ef_search(SearchMode.LOCAL)
        assert value == 120

    @pytest.mark.asyncio
    async def test_get_ef_search_global(self, manager: EfSearchManager) -> None:
        """Test global mode returns correct ef_search value."""
        value = manager.get_ef_search(SearchMode.GLOBAL)
        assert value == 60

    @pytest.mark.asyncio
    async def test_get_ef_search_drift(self, manager: EfSearchManager) -> None:
        """Test drift mode returns correct ef_search value."""
        value = manager.get_ef_search(SearchMode.DRIFT)
        assert value == 80

    @pytest.mark.asyncio
    async def test_get_ef_search_latency(self, manager: EfSearchManager) -> None:
        """Test latency mode returns correct ef_search value."""
        value = manager.get_ef_search(SearchMode.LATENCY)
        assert value == 20

    @pytest.mark.asyncio
    async def test_set_ef_search_calls_pool(self, manager: EfSearchManager) -> None:
        """Test that set_ef_search executes SQL command."""
        # Mock the pool session context manager
        mock_session = AsyncMock()
        manager._pool.session = MagicMock()
        manager._pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        manager._pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        await manager.set_ef_search(SearchMode.HYBRID)

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        assert "SET hnsw.ef_search = 40" in str(call_args)

    @pytest.mark.asyncio
    async def test_set_ef_search_with_custom_value(self, manager: EfSearchManager) -> None:
        """Test set_ef_search with custom value."""
        # Mock the pool session context manager
        mock_session = AsyncMock()
        manager._pool.session = MagicMock()
        manager._pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        manager._pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        await manager.set_ef_search(SearchMode.LOCAL, value=150)

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        assert "SET hnsw.ef_search = 150" in str(call_args)

    @pytest.mark.asyncio
    async def test_set_ef_search_handles_error(self, manager: EfSearchManager) -> None:
        """Test that set_ef_search handles errors gracefully."""
        # Mock the pool session context manager to raise exception
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database error")
        manager._pool.session = MagicMock()
        manager._pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        manager._pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # Should not raise exception
        await manager.set_ef_search(SearchMode.HYBRID)


class TestEfSearchManagerIntegration:
    """Test EfSearchManager integration with search methods."""

    @pytest.mark.asyncio
    async def test_apply_ef_search_before_query(self, manager: EfSearchManager) -> None:
        """Test that apply_ef_search sets ef_search before query."""
        # Mock the pool session context manager
        mock_session = AsyncMock()
        manager._pool.session = MagicMock()
        manager._pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        manager._pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        async with manager.apply_ef_search(SearchMode.LOCAL):
            # Inside the context manager, ef_search should be set
            pass

        # Verify ef_search was set (execute called at least once)
        assert mock_session.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_apply_ef_search_restores_on_exit(self, manager: EfSearchManager) -> None:
        """Test that apply_ef_search restores original ef_search on exit."""
        # Mock the pool session context manager
        mock_session = AsyncMock()
        manager._pool.session = MagicMock()
        manager._pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        manager._pool.session.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock the initial ef_search value
        mock_result = MagicMock()
        mock_result.scalar.return_value = 40
        mock_session.execute.return_value = mock_result

        async with manager.apply_ef_search(SearchMode.LOCAL):
            pass

        # Should have been called three times: SHOW, SET, RESTORE
        assert mock_session.execute.call_count == 3


class TestEdgeCases:
    """Test edge cases."""

    def test_invalid_search_mode(self, manager: EfSearchManager) -> None:
        """Test invalid search mode raises error."""
        with pytest.raises(ValueError):
            manager.get_ef_search("invalid_mode")

    @pytest.mark.asyncio
    async def test_set_ef_search_with_none_pool(self) -> None:
        """Test set_ef_search with None pool."""
        manager = EfSearchManager(pool=None, config=EfSearchConfig())
        # Should not raise exception
        await manager.set_ef_search(SearchMode.HYBRID)

    @pytest.mark.asyncio
    async def test_apply_ef_search_with_none_pool(self) -> None:
        """Test apply_ef_search with None pool."""
        manager = EfSearchManager(pool=None, config=EfSearchConfig())
        # Should not raise exception
        async with manager.apply_ef_search(SearchMode.HYBRID):
            pass
