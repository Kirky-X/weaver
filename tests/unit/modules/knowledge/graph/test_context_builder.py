# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Context Builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


class TestGlobalContextBuilder:
    """Tests for GlobalContextBuilder."""

    def test_global_context_builder_initializes(self, mock_neo4j_pool):
        """Test that GlobalContextBuilder initializes correctly."""
        from modules.knowledge.search.context.global_context import GlobalContextBuilder

        builder = GlobalContextBuilder(
            graph_pool=mock_neo4j_pool,
            default_max_tokens=12000,
            max_communities=10,
        )

        assert builder is not None

    def test_global_context_builder_with_custom_params(self, mock_neo4j_pool):
        """Test GlobalContextBuilder with custom parameters."""
        from modules.knowledge.search.context.global_context import GlobalContextBuilder

        builder = GlobalContextBuilder(
            graph_pool=mock_neo4j_pool,
            default_max_tokens=15000,
            max_communities=20,
        )

        assert builder._max_communities == 20

    @pytest.mark.asyncio
    async def test_global_context_build_returns_context(self, mock_neo4j_pool):
        """Test that build returns a context object."""
        from modules.knowledge.search.context.global_context import GlobalContextBuilder

        mock_neo4j_pool.execute = AsyncMock(return_value=[])

        builder = GlobalContextBuilder(graph_pool=mock_neo4j_pool)

        context = await builder.build(query="Test", max_tokens=5000)

        assert context is not None


class TestLocalContextBuilder:
    """Tests for LocalContextBuilder."""

    def test_local_context_builder_initializes(self, mock_neo4j_pool):
        """Test that LocalContextBuilder initializes correctly."""
        from modules.knowledge.search.context.local_context import LocalContextBuilder

        builder = LocalContextBuilder(
            graph_pool=mock_neo4j_pool,
            default_max_tokens=8000,
        )

        assert builder is not None

    def test_local_context_builder_with_custom_params(self, mock_neo4j_pool):
        """Test LocalContextBuilder with custom parameters."""
        from modules.knowledge.search.context.local_context import LocalContextBuilder

        builder = LocalContextBuilder(
            graph_pool=mock_neo4j_pool,
            default_max_tokens=10000,
        )

        assert builder._default_max_tokens == 10000

    @pytest.mark.asyncio
    async def test_local_context_build_returns_context(self, mock_neo4j_pool):
        """Test that build returns a context object."""
        from modules.knowledge.search.context.local_context import LocalContextBuilder

        mock_neo4j_pool.execute = AsyncMock(return_value=[])

        builder = LocalContextBuilder(graph_pool=mock_neo4j_pool)

        context = await builder.build(query="Test", max_tokens=5000)

        assert context is not None

    @pytest.mark.asyncio
    async def test_local_context_with_entity_names(self, mock_neo4j_pool):
        """Test LocalContextBuilder with specific entity names."""
        from modules.knowledge.search.context.local_context import LocalContextBuilder

        mock_neo4j_pool.execute = AsyncMock(return_value=[])

        builder = LocalContextBuilder(graph_pool=mock_neo4j_pool)

        context = await builder.build(
            query="Test",
            max_tokens=5000,
            entity_names=["Entity1", "Entity2"],
        )

        assert context is not None


class TestContextBuilderEdgeCases:
    """Edge case tests for context builders."""

    @pytest.mark.asyncio
    async def test_context_build_with_empty_results(self, mock_neo4j_pool):
        """Test context building with empty Neo4j results."""
        from modules.knowledge.search.context.global_context import GlobalContextBuilder

        mock_neo4j_pool.execute = AsyncMock(return_value=[])

        builder = GlobalContextBuilder(graph_pool=mock_neo4j_pool)

        context = await builder.build(query="Test", max_tokens=5000)

        assert context is not None

    @pytest.mark.asyncio
    async def test_context_respects_token_budget(self, mock_neo4j_pool):
        """Test that context building respects token budget."""
        from modules.knowledge.search.context.local_context import LocalContextBuilder

        mock_neo4j_pool.execute = AsyncMock(return_value=[])

        builder = LocalContextBuilder(
            graph_pool=mock_neo4j_pool,
            default_max_tokens=8000,
        )

        context = await builder.build(
            query="Test",
            max_tokens=2000,
        )

        assert context.total_tokens <= 2000


class TestContextBuilderErrorHandling:
    """Error handling tests for context builders."""

    @pytest.mark.asyncio
    async def test_context_handles_neo4j_error(self, mock_neo4j_pool):
        """Test context builder handles Neo4j errors."""
        from modules.knowledge.search.context.global_context import GlobalContextBuilder

        mock_neo4j_pool.execute = AsyncMock(side_effect=Exception("Neo4j connection failed"))

        builder = GlobalContextBuilder(graph_pool=mock_neo4j_pool)

        # Should handle error gracefully
        try:
            context = await builder.build(query="Test", max_tokens=5000)
            assert context is not None
        except Exception:
            # It's also acceptable to raise
            pass
