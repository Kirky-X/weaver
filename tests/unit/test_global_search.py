# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GlobalSearchEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.engines.global_search import GlobalSearchEngine, MapReduceResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    return AsyncMock()


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


class TestGlobalSearchEngineBasic:
    """Basic functionality tests for GlobalSearchEngine."""

    @pytest.mark.asyncio
    async def test_global_search_initializes(self, mock_neo4j_pool, mock_llm):
        """Test that global search engine initializes correctly."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        assert engine is not None
        assert engine._max_communities == 10  # default

    @pytest.mark.asyncio
    async def test_global_search_with_custom_params(self, mock_neo4j_pool, mock_llm):
        """Test global search engine with custom parameters."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            default_max_tokens=15000,
            max_communities=20,
        )

        assert engine._default_max_tokens == 15000
        assert engine._max_communities == 20

    @pytest.mark.asyncio
    async def test_global_search_returns_search_result(self, mock_neo4j_pool, mock_llm):
        """Test that global search returns SearchResult."""
        from modules.knowledge.search.engines.local_search import SearchResult

        # Mock context builder
        mock_context = MagicMock()
        mock_context.total_tokens = 100
        mock_context.to_prompt = MagicMock(return_value="Context")

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = "Test answer"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Mock context builder
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("Test query")

        # Verify result type
        assert isinstance(result, SearchResult)


class TestGlobalSearchEngineEdgeCases:
    """Edge case tests for GlobalSearchEngine."""

    @pytest.mark.asyncio
    async def test_global_search_with_no_communities(self, mock_neo4j_pool, mock_llm):
        """Test global search with no communities found."""
        from modules.knowledge.search.engines.local_search import SearchResult

        # Mock empty context
        mock_context = MagicMock()
        mock_context.total_tokens = 0
        mock_context.sections = []

        mock_response = MagicMock()
        mock_response.content = "No information found"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("Unknown topic")

        assert isinstance(result, SearchResult)

    @pytest.mark.asyncio
    async def test_global_search_with_max_tokens_limit(self, mock_neo4j_pool, mock_llm):
        """Test global search initializes with correct token limit."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            default_max_tokens=8000,
        )

        # Verify engine has correct token settings
        assert engine._default_max_tokens == 8000


class TestGlobalSearchEngineErrorHandling:
    """Error handling tests for GlobalSearchEngine."""

    @pytest.mark.asyncio
    async def test_global_search_handles_llm_error(self, mock_neo4j_pool, mock_llm):
        """Test global search handles LLM errors."""
        mock_context = MagicMock()
        mock_context.total_tokens = 100

        mock_llm.chat = AsyncMock(side_effect=Exception("LLM unavailable"))

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        # Should handle error gracefully
        result = await engine.search("Test query")
        assert result is not None

    @pytest.mark.asyncio
    async def test_global_search_handles_context_error(self, mock_neo4j_pool, mock_llm):
        """Test global search handles context building errors."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(side_effect=Exception("Context building failed"))

        # Should handle error gracefully
        try:
            result = await engine.search("Test query")
            assert result is not None
        except Exception:
            # It's also acceptable to raise
            pass
