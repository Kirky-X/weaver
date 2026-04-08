# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LocalSearchEngine in knowledge module."""

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
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        assert engine is not None
        assert engine._default_max_tokens == 8000  # default

    @pytest.mark.asyncio
    async def test_local_search_with_custom_params(self, mock_neo4j_pool, mock_llm):
        """Test local search engine with custom parameters."""
        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
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
        mock_context.metadata = {"article_count": 0, "total_entities": 0, "total_relationships": 0}
        mock_context.to_prompt = MagicMock(return_value="Context")

        # Mock LLM response
        mock_llm.call_at = AsyncMock(return_value="Test answer")

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("Test query")

        # Verify result type
        assert isinstance(result, SearchResult)
        assert result.query == "Test query"

    @pytest.mark.asyncio
    async def test_local_search_with_hybrid_engine(self, mock_neo4j_pool, mock_llm):
        """Test local search engine with hybrid engine reference."""
        mock_hybrid = MagicMock()
        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
            hybrid_engine=mock_hybrid,
        )

        assert engine._hybrid_engine is mock_hybrid


class TestLocalSearchEngineSearch:
    """Tests for search method."""

    @pytest.mark.asyncio
    async def test_search_with_use_llm_false(self, mock_neo4j_pool, mock_llm):
        """Test search with use_llm=False returns context info."""
        mock_context = MagicMock()
        mock_context.total_tokens = 100
        mock_context.sections = []
        mock_context.metadata = {"article_count": 5, "total_entities": 10, "total_relationships": 5}

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test query", use_llm=False)

        assert "LLM generation skipped" in result.answer
        assert result.metadata["llm_used"] is False

    @pytest.mark.asyncio
    async def test_search_with_relation_types(self, mock_neo4j_pool, mock_llm):
        """Test search with relation_types filter."""
        mock_context = MagicMock()
        mock_context.total_tokens = 100
        mock_context.sections = []
        mock_context.metadata = {"article_count": 0}
        mock_context.to_prompt = MagicMock(return_value="Context")

        mock_llm.call_at = AsyncMock(return_value="Answer")

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test", relation_types=["RELATED_TO", "MENTIONS"])

        # Verify context builder was called with relation_types
        call_kwargs = engine._context_builder.build.call_args[1]
        assert call_kwargs["relation_types"] == ["RELATED_TO", "MENTIONS"]

    @pytest.mark.asyncio
    async def test_search_batch(self, mock_neo4j_pool, mock_llm):
        """Test search_batch method."""
        mock_context = MagicMock()
        mock_context.total_tokens = 100
        mock_context.sections = []
        mock_context.metadata = {"article_count": 0}
        mock_context.to_prompt = MagicMock(return_value="Context")

        mock_llm.call_at = AsyncMock(return_value="Batch answer")

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        results = await engine.search_batch(["query1", "query2"])

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)


class TestLocalSearchEngineErrorHandling:
    """Error handling tests for LocalSearchEngine."""

    @pytest.mark.asyncio
    async def test_local_search_handles_llm_error(self, mock_neo4j_pool, mock_llm):
        """Test local search handles LLM errors."""
        mock_context = MagicMock()
        mock_context.total_tokens = 100
        mock_context.sections = []
        mock_context.metadata = {"article_count": 0}
        mock_context.to_prompt = MagicMock(return_value="Context")

        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        # Should handle error gracefully
        result = await engine.search("Test query")
        assert result is not None
        assert "failed" in result.answer.lower()
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_local_search_handles_context_error(self, mock_neo4j_pool, mock_llm):
        """Test local search handles context building errors."""
        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder.build = AsyncMock(side_effect=Exception("Context building failed"))

        # The search method does not catch context building errors
        # It's expected to propagate up
        with pytest.raises(Exception, match="Context building failed"):
            await engine.search("Test query")


class TestLocalSearchEngineHelperMethods:
    """Tests for helper methods."""

    def test_build_prompt(self, mock_neo4j_pool, mock_llm):
        """Test _build_prompt creates valid prompt."""
        mock_context = MagicMock()
        mock_context.to_prompt = MagicMock(return_value="Mock context content")

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        prompt = engine._build_prompt("What is X?", mock_context)

        assert "What is X?" in prompt
        assert "Mock context content" in prompt
        assert "Instructions:" in prompt

    def test_extract_entities_from_context(self, mock_neo4j_pool, mock_llm):
        """Test _extract_entities_from_context extracts entity names."""
        mock_section = MagicMock()
        mock_section.metadata = {"entity_count": 3}
        mock_section.content = "- EntityA (Person)\n- EntityB (Organization)\n- Not an entity"

        mock_context = MagicMock()
        mock_context.sections = [mock_section]

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        entities = engine._extract_entities_from_context(mock_context)

        assert "EntityA" in entities
        assert "EntityB" in entities

    def test_extract_entities_empty_sections(self, mock_neo4j_pool, mock_llm):
        """Test _extract_entities_from_context with empty sections."""
        mock_context = MagicMock()
        mock_context.sections = []

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        entities = engine._extract_entities_from_context(mock_context)

        assert entities == []

    def test_estimate_confidence_empty_context(self, mock_neo4j_pool, mock_llm):
        """Test _estimate_confidence with empty context."""
        mock_context = MagicMock()
        mock_context.sections = []

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        confidence = engine._estimate_confidence(mock_context)

        assert confidence == 0.0

    def test_estimate_confidence_with_entities(self, mock_neo4j_pool, mock_llm):
        """Test _estimate_confidence with entities and relationships."""
        mock_context = MagicMock()
        mock_context.sections = [MagicMock()]
        mock_context.total_tokens = 1000
        mock_context.metadata = {"total_entities": 15, "total_relationships": 30}

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        confidence = engine._estimate_confidence(mock_context)

        # Base 0.5 + min(0.2, 15*0.02) + min(0.2, 30*0.01)
        assert confidence == pytest.approx(0.5 + 0.2 + 0.2)

    def test_estimate_confidence_low_tokens(self, mock_neo4j_pool, mock_llm):
        """Test _estimate_confidence reduces confidence for low tokens."""
        mock_context = MagicMock()
        mock_context.sections = [MagicMock()]
        mock_context.total_tokens = 200  # < 500
        mock_context.metadata = {"total_entities": 5, "total_relationships": 10}

        engine = LocalSearchEngine(
            graph_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        confidence = engine._estimate_confidence(mock_context)

        # Base 0.5 + bonuses - 0.2 for low tokens
        assert confidence < 0.5


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_search_result_defaults(self):
        """Test SearchResult with default values."""
        result = SearchResult(
            query="test query",
            answer="test answer",
            context_tokens=100,
        )

        assert result.sources == []
        assert result.entities == []
        assert result.confidence == 0.0
        assert result.metadata == {}

    def test_search_result_with_all_fields(self):
        """Test SearchResult with all fields populated."""
        result = SearchResult(
            query="full query",
            answer="full answer",
            context_tokens=500,
            sources=[{"id": "1"}],
            entities=["EntityA", "EntityB"],
            confidence=0.85,
            metadata={"key": "value"},
        )

        assert len(result.sources) == 1
        assert len(result.entities) == 2
        assert result.confidence == 0.85
        assert result.metadata["key"] == "value"
