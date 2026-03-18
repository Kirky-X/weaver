# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for local search engine module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.search.engines.local_search import (
    LocalSearchEngine,
    SearchResult,
)


class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_initialization(self):
        """Test SearchResult initialization."""
        result = SearchResult(
            query="test query",
            answer="Test answer",
            context_tokens=100,
            sources=[{"id": 1}],
            entities=["Entity1"],
            confidence=0.8,
        )

        assert result.query == "test query"
        assert result.answer == "Test answer"
        assert result.context_tokens == 100
        assert result.confidence == 0.8


class TestLocalSearchEngine:
    """Test LocalSearchEngine class."""

    def test_init(self):
        """Test initialization."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        engine = LocalSearchEngine(mock_pool, mock_llm)

        assert engine._pool == mock_pool
        assert engine._llm == mock_llm

    @pytest.mark.asyncio
    async def test_search_no_entities(self):
        """Test search with no matching entities."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()

        engine = LocalSearchEngine(mock_pool, mock_llm)

        result = await engine.search("unknown entity xyz")

        assert isinstance(result, SearchResult)

    @pytest.mark.asyncio
    async def test_search_with_entities(self):
        """Test search with matching entities."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"name": "TestEntity"}],
                [{"canonical_name": "TestEntity", "type": "人物", "description": "A test"}],
                [],
                [],
            ]
        )
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Test answer"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        engine = LocalSearchEngine(mock_pool, mock_llm)

        result = await engine.search("TestEntity")

        assert result.query == "TestEntity"
        assert result.context_tokens > 0

    @pytest.mark.asyncio
    async def test_search_batch(self):
        """Test batch search."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Answer"
        mock_llm.chat = AsyncMock(return_value=mock_response)

        engine = LocalSearchEngine(mock_pool, mock_llm)

        results = await engine.search_batch(["query1", "query2"])

        assert len(results) == 2

    def test_extract_entities_from_context(self):
        """Test entity extraction from context."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        engine = LocalSearchEngine(mock_pool, mock_llm)

        class MockContext:
            def __init__(self):
                self.sections = []
                self.metadata = {}

        context = MockContext()
        context.metadata = {"total_entities": 5}
        context.sections = []

        entities = engine._extract_entities_from_context(context)

        assert isinstance(entities, list)

    def test_estimate_confidence_empty(self):
        """Test confidence estimation with empty context."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        engine = LocalSearchEngine(mock_pool, mock_llm)

        class MockContext:
            def __init__(self):
                self.sections = []
                self.metadata = {}

        context = MockContext()
        confidence = engine._estimate_confidence(context)

        assert confidence == 0.0

    def test_estimate_confidence_with_data(self):
        """Test confidence estimation with data."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        engine = LocalSearchEngine(mock_pool, mock_llm)

        class MockContext:
            def __init__(self):
                self.sections = [1, 2, 3]
                self.metadata = {"total_entities": 20, "total_relationships": 10}
                self.total_tokens = 1000

        context = MockContext()
        confidence = engine._estimate_confidence(context)

        assert confidence > 0.0

    def test_build_prompt(self):
        """Test prompt building."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        engine = LocalSearchEngine(mock_pool, mock_llm)

        class MockContext:
            def to_prompt(self):
                return "Context content"

        context = MockContext()
        prompt = engine._build_prompt("test query", context)

        assert "test query" in prompt
        assert "Context content" in prompt
