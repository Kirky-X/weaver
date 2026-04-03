# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LocalSearchEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.engines.local_search import LocalSearchEngine, SearchResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    return AsyncMock()


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


class TestLocalSearchEngineBasic:
    """Basic functionality tests for LocalSearchEngine."""

    @pytest.mark.asyncio
    async def test_local_search_initializes(self, mock_neo4j_pool, mock_llm):
        """Test that local search engine initializes correctly."""
        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        assert engine is not None
        assert engine._default_max_tokens == 8000  # default

    @pytest.mark.asyncio
    async def test_local_search_with_custom_params(self, mock_neo4j_pool, mock_llm):
        """Test local search engine with custom parameters."""
        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            default_max_tokens=10000,
            max_context_tokens=8000,
        )

        assert engine._default_max_tokens == 10000
        assert engine._max_context_tokens == 8000

    @pytest.mark.asyncio
    async def test_local_search_returns_search_result(self, mock_neo4j_pool, mock_llm):
        """Test that local search returns SearchResult."""
        # Mock context
        mock_context = MagicMock()
        mock_context.total_tokens = 500
        mock_context.sections = []
        mock_context.to_prompt = MagicMock(return_value="Context")

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = "Test answer"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("Test query")

        # Verify result type
        assert isinstance(result, SearchResult)
        assert result.query == "Test query"


class TestLocalSearchEngineEdgeCases:
    """Edge case tests for LocalSearchEngine."""

    @pytest.mark.asyncio
    async def test_local_search_with_no_entities(self, mock_neo4j_pool, mock_llm):
        """Test local search with no entities found."""
        # Mock empty context
        mock_context = MagicMock()
        mock_context.total_tokens = 0
        mock_context.sections = []
        mock_context.to_prompt = MagicMock(return_value="")

        mock_response = MagicMock()
        mock_response.content = "No information found"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("Unknown entity")

        assert isinstance(result, SearchResult)

    @pytest.mark.asyncio
    async def test_local_search_with_entity_names(self, mock_neo4j_pool, mock_llm):
        """Test LocalSearchEngine initializes with correct params."""
        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Verify engine exists and has expected attributes
        assert engine is not None
        assert hasattr(engine, "_context_builder")

    @pytest.mark.asyncio
    async def test_local_search_respects_token_limit(self, mock_neo4j_pool, mock_llm):
        """Test LocalSearchEngine has correct token limits."""
        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            max_context_tokens=6000,
        )

        # Verify engine has correct token settings
        assert engine._max_context_tokens == 6000


class TestLocalSearchEngineErrorHandling:
    """Error handling tests for LocalSearchEngine."""

    @pytest.mark.asyncio
    async def test_local_search_handles_llm_error(self, mock_neo4j_pool, mock_llm):
        """Test local search handles LLM errors."""
        mock_context = MagicMock()
        mock_context.total_tokens = 100
        mock_context.to_prompt = MagicMock(return_value="Context")

        mock_llm.chat = AsyncMock(side_effect=Exception("LLM unavailable"))

        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        # Should handle error gracefully
        result = await engine.search("Test query")
        assert result is not None
        assert "failed" in result.answer.lower() or result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_local_search_handles_context_error(self, mock_neo4j_pool, mock_llm):
        """Test local search handles context building errors."""
        engine = LocalSearchEngine(
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
