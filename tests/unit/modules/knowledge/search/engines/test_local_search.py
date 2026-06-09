# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LocalSearchEngine - comprehensive coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.constants import SearchMode
from modules.knowledge.search.engines.local_search import LocalSearchEngine, SearchResult


@pytest.fixture
def mock_context_builder():
    """Mock context builder."""
    return MagicMock()


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


def _make_mock_context(
    total_tokens=500,
    sections=None,
    total_entities=0,
    total_relationships=0,
    article_count=0,
):
    """Create a mock SearchContext."""
    ctx = MagicMock()
    ctx.total_tokens = total_tokens
    ctx.sections = sections or []
    ctx.metadata = {
        "article_count": article_count,
        "total_entities": total_entities,
        "total_relationships": total_relationships,
    }
    ctx.to_prompt = MagicMock(return_value="Context prompt")
    return ctx


class TestLocalSearchEngineSearch:
    """Tests for search() method."""

    @pytest.mark.asyncio
    async def test_search_with_llm(self, mock_context_builder, mock_llm):
        """Test search with LLM generation."""
        mock_context = _make_mock_context(total_entities=5, total_relationships=3)
        mock_llm.call_at = AsyncMock(return_value="LLM answer")

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test query")

        assert isinstance(result, SearchResult)
        assert result.answer == "LLM answer"
        assert result.metadata["llm_used"] is True
        assert result.metadata["search_type"] == SearchMode.LOCAL.value

    @pytest.mark.asyncio
    async def test_search_use_llm_false(self, mock_context_builder, mock_llm):
        """Test search with use_llm=False."""
        mock_context = _make_mock_context(total_entities=10, total_relationships=5)

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test query", use_llm=False)

        assert "LLM generation skipped" in result.answer
        assert result.metadata["llm_used"] is False

    @pytest.mark.asyncio
    async def test_search_with_entity_names(self, mock_context_builder, mock_llm):
        """Test search with explicit entity names."""
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(return_value="Answer")

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("query", entity_names=["Entity1", "Entity2"])

        call_kwargs = engine._context_builder.build.call_args[1]
        assert call_kwargs["entity_names"] == ["Entity1", "Entity2"]

    @pytest.mark.asyncio
    async def test_search_with_relation_types(self, mock_context_builder, mock_llm):
        """Test search with relation_types filter."""
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(return_value="Answer")

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test", relation_types=["RELATED_TO", "MENTIONS"])

        call_kwargs = engine._context_builder.build.call_args[1]
        assert call_kwargs["relation_types"] == ["RELATED_TO", "MENTIONS"]

    @pytest.mark.asyncio
    async def test_search_with_custom_max_tokens(self, mock_context_builder, mock_llm):
        """Test search with custom max_tokens."""
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(return_value="Answer")

        engine = LocalSearchEngine(
            context_builder=mock_context_builder,
            llm=mock_llm,
            max_context_tokens=5000,
        )
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test", max_tokens=3000)

        call_kwargs = engine._context_builder.build.call_args[1]
        assert call_kwargs["max_tokens"] == 3000

    @pytest.mark.asyncio
    async def test_search_handles_llm_error(self, mock_context_builder, mock_llm):
        """Test search handles LLM errors gracefully."""
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("Test query")

        assert "failed" in result.answer.lower()
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_search_with_hybrid_engine(self, mock_context_builder, mock_llm):
        """Test search metadata includes hybrid_used flag."""
        mock_hybrid = MagicMock()
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(return_value="Answer")

        engine = LocalSearchEngine(
            context_builder=mock_context_builder,
            llm=mock_llm,
            hybrid_engine=mock_hybrid,
        )
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test query")

        assert result.metadata["hybrid_used"] is True

    @pytest.mark.asyncio
    async def test_search_llm_non_string_response(self, mock_context_builder, mock_llm):
        """Test search handles non-string LLM response."""
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(return_value={"content": "dict answer"})

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search("test query")

        assert isinstance(result.answer, str)


class TestLocalSearchEngineSearchBatch:
    """Tests for search_batch() method."""

    @pytest.mark.asyncio
    async def test_search_batch(self, mock_context_builder, mock_llm):
        """Test search_batch with multiple queries."""
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(return_value="Batch answer")

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        results = await engine.search_batch(["query1", "query2", "query3"])

        assert len(results) == 3
        assert all(isinstance(r, SearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_search_batch_single_query(self, mock_context_builder, mock_llm):
        """Test search_batch with single query."""
        mock_context = _make_mock_context()
        mock_llm.call_at = AsyncMock(return_value="Answer")

        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        results = await engine.search_batch(["single query"])

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_batch_empty_list(self, mock_context_builder, mock_llm):
        """Test search_batch with empty list."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        results = await engine.search_batch([])

        assert results == []


class TestLocalSearchEngineEstimateConfidence:
    """Tests for _estimate_confidence method."""

    def test_confidence_empty_context(self, mock_context_builder, mock_llm):
        """Test confidence with empty context."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.sections = []

        assert engine._estimate_confidence(mock_context) == 0.0

    def test_confidence_with_entities_and_relationships(self, mock_context_builder, mock_llm):
        """Test confidence with entities and relationships."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.sections = [MagicMock()]
        mock_context.total_tokens = 1000
        mock_context.metadata = {"total_entities": 15, "total_relationships": 30}

        confidence = engine._estimate_confidence(mock_context)

        # Base 0.5 + min(0.2, 15*0.02) + min(0.2, 30*0.01)
        assert confidence == pytest.approx(0.5 + 0.2 + 0.2)

    def test_confidence_low_tokens(self, mock_context_builder, mock_llm):
        """Test confidence reduces for low token count."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.sections = [MagicMock()]
        mock_context.total_tokens = 200  # < 500
        mock_context.metadata = {"total_entities": 5, "total_relationships": 10}

        confidence = engine._estimate_confidence(mock_context)

        # Should be reduced by 0.2
        assert confidence < 0.5

    def test_confidence_capped_at_one(self, mock_context_builder, mock_llm):
        """Test confidence is capped at 1.0."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.sections = [MagicMock()]
        mock_context.total_tokens = 5000
        mock_context.metadata = {"total_entities": 100, "total_relationships": 200}

        confidence = engine._estimate_confidence(mock_context)

        assert confidence <= 1.0

    def test_confidence_minimum_zero(self, mock_context_builder, mock_llm):
        """Test confidence is at least 0.0."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.sections = [MagicMock()]
        mock_context.total_tokens = 100
        mock_context.metadata = {"total_entities": 0, "total_relationships": 0}

        confidence = engine._estimate_confidence(mock_context)

        assert confidence >= 0.0


class TestLocalSearchEngineExtractEntities:
    """Tests for _extract_entities_from_context method."""

    def test_extract_entities_basic(self, mock_context_builder, mock_llm):
        """Test extracting entity names from context."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_section = MagicMock()
        mock_section.metadata = {"entity_count": 3}
        mock_section.content = "- EntityA (Person)\n- EntityB (Organization)\n- Not an entity"

        mock_context = MagicMock()
        mock_context.sections = [mock_section]

        entities = engine._extract_entities_from_context(mock_context)

        assert "EntityA" in entities
        assert "EntityB" in entities

    def test_extract_entities_related_count(self, mock_context_builder, mock_llm):
        """Test extracting entities using related_count metadata."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_section = MagicMock()
        mock_section.metadata = {"related_count": 2}
        mock_section.content = "- EntityC (Event)\n- EntityD (Location)"

        mock_context = MagicMock()
        mock_context.sections = [mock_section]

        entities = engine._extract_entities_from_context(mock_context)

        assert "EntityC" in entities
        assert "EntityD" in entities

    def test_extract_entities_empty_sections(self, mock_context_builder, mock_llm):
        """Test extracting entities with empty sections."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.sections = []

        entities = engine._extract_entities_from_context(mock_context)

        assert entities == []

    def test_extract_entities_deduplication(self, mock_context_builder, mock_llm):
        """Test that duplicate entities are deduplicated."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_section1 = MagicMock()
        mock_section1.metadata = {"entity_count": 1}
        mock_section1.content = "- EntityA (Person)"

        mock_section2 = MagicMock()
        mock_section2.metadata = {"entity_count": 1}
        mock_section2.content = "- EntityA (Person)"

        mock_context = MagicMock()
        mock_context.sections = [mock_section1, mock_section2]

        entities = engine._extract_entities_from_context(mock_context)

        assert entities.count("EntityA") == 1


class TestLocalSearchEngineExtractSources:
    """Tests for _extract_sources_from_context method."""

    def test_extract_sources_basic(self, mock_context_builder, mock_llm):
        """Test extracting source articles from context."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_section = MagicMock()
        mock_section.name = "Article Section"
        mock_section.content = "- Article Title 1\n- Article Title 2"

        mock_context = MagicMock()
        mock_context.sections = [mock_section]

        sources = engine._extract_sources_from_context(mock_context)

        assert len(sources) == 2
        assert sources[0]["title"] == "Article Title 1"

    def test_extract_sources_non_article_sections(self, mock_context_builder, mock_llm):
        """Test that non-article sections are skipped."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_section = MagicMock()
        mock_section.name = "Entity Section"
        mock_section.content = "- Entity1\n- Entity2"

        mock_context = MagicMock()
        mock_context.sections = [mock_section]

        sources = engine._extract_sources_from_context(mock_context)

        assert sources == []


class TestLocalSearchEngineBuildPrompt:
    """Tests for _build_prompt method."""

    def test_build_prompt_includes_query(self, mock_context_builder, mock_llm):
        """Test that prompt includes the query."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.to_prompt = MagicMock(return_value="Context content")

        prompt = engine._build_prompt("What is X?", mock_context)

        assert "What is X?" in prompt
        assert "Context content" in prompt

    def test_build_prompt_includes_instructions(self, mock_context_builder, mock_llm):
        """Test that prompt includes answer instructions."""
        engine = LocalSearchEngine(context_builder=mock_context_builder, llm=mock_llm)

        mock_context = MagicMock()
        mock_context.to_prompt = MagicMock(return_value="Context")

        prompt = engine._build_prompt("Query", mock_context)

        assert "回答要求" in prompt or "Answer:" in prompt


class TestSearchResultExtended:
    """Extended tests for SearchResult dataclass."""

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
