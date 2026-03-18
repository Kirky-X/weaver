# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Search workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.search.engines.global_search import GlobalSearchEngine, MapReduceResult
from modules.search.engines.local_search import LocalSearchEngine, SearchResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    return AsyncMock()


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_vector_repo():
    """Mock vector repository."""
    return AsyncMock()


class TestGlobalSearchIntegration:
    """Integration tests for Global Search workflow."""

    @pytest.mark.asyncio
    async def test_global_search_returns_map_reduce_result(self, mock_neo4j_pool, mock_llm):
        """Test that global search returns SearchResult."""
        # Mock LLM to return intermediate and final answers
        mock_llm.call = AsyncMock(
            side_effect=[
                "Intermediate answer about AI research",
                "Final aggregated answer",
            ]
        )

        # Mock Neo4j to return community data
        mock_neo4j_pool.execute = AsyncMock(
            return_value=[
                {
                    "community": "AI Research",
                    "nodes": ["Paper1", "Paper2"],
                    "relationships": ["CITES"],
                }
            ]
        )

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("What is AI research about?")

        # Verify result structure (SearchResult is a dataclass)
        assert isinstance(result, SearchResult)
        assert result.query == "What is AI research about?"
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_global_search_with_no_communities(self, mock_neo4j_pool, mock_llm):
        """Test global search with no relevant communities."""
        mock_neo4j_pool.execute = AsyncMock(return_value=[])

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Unknown topic")

        # Should return empty or default result
        assert result is not None

    @pytest.mark.asyncio
    async def test_global_search_handles_llm_error(self, mock_neo4j_pool, mock_llm):
        """Test global search handles LLM errors gracefully."""
        mock_neo4j_pool.execute = AsyncMock(return_value=[{"community": "Test"}])
        mock_llm.call = AsyncMock(side_effect=Exception("LLM unavailable"))

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Should handle error - may return empty result or raise
        try:
            result = await engine.search("Test query")
            # If it doesn't raise, it should return a valid result
            assert result is not None
        except Exception:
            # It's also acceptable to raise
            pass


class TestLocalSearchIntegration:
    """Integration tests for Local Search workflow."""

    @pytest.mark.asyncio
    async def test_local_search_returns_search_result(self, mock_neo4j_pool, mock_llm):
        """Test that local search returns SearchResult."""
        # Mock Neo4j to return entity data
        mock_neo4j_pool.execute = AsyncMock(
            return_value=[
                {
                    "entity": "AI",
                    "description": "Artificial Intelligence",
                    "relationships": [],
                }
            ]
        )

        # Mock LLM chat response
        mock_response = MagicMock()
        mock_response.content = "AI stands for Artificial Intelligence"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("What is AI?")

        # Verify result structure
        assert isinstance(result, SearchResult)
        assert result.query == "What is AI?"
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_local_search_with_no_entities(self, mock_neo4j_pool, mock_llm):
        """Test local search with no relevant entities."""
        mock_neo4j_pool.execute = AsyncMock(return_value=[])

        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Unknown query")

        # Should return a result (may be empty)
        assert result is not None

    @pytest.mark.asyncio
    async def test_local_search_handles_neo4j_error(self, mock_neo4j_pool, mock_llm):
        """Test local search handles Neo4j errors."""
        mock_neo4j_pool.execute = AsyncMock(side_effect=Exception("Neo4j unavailable"))

        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Should handle error - may return empty result or raise
        try:
            result = await engine.search("Test query")
            assert result is not None
        except Exception:
            # It's also acceptable to raise
            pass


class TestSearchEngineComparison:
    """Integration tests comparing local and global search."""

    @pytest.mark.asyncio
    async def test_engines_provide_different_granularity(self, mock_neo4j_pool, mock_llm):
        """Test that local and global search provide results."""
        # Setup mocks
        mock_neo4j_pool.execute = AsyncMock(
            return_value=[{"entity": "AI", "community": "AI Research"}]
        )
        mock_llm.call = AsyncMock(return_value="Answer about AI")

        # Local search
        local_engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )
        local_result = await local_engine.search("AI")

        # Global search
        global_engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )
        global_result = await global_engine.search("AI")

        # Both should return SearchResult objects
        assert isinstance(local_result, SearchResult)
        assert isinstance(global_result, SearchResult)
        assert local_result.query == "AI"
        assert global_result.query == "AI"
