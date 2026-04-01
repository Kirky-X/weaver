# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GlobalSearchEngine in knowledge module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.engines.global_search import (
    CommunityContext,
    GlobalSearchEngine,
)
from modules.knowledge.search.engines.local_search import SearchResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    return AsyncMock()


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@dataclass
class MockContext:
    """Mock SearchContext for testing."""

    query: str
    sections: list[Any]
    total_tokens: int
    max_tokens: int
    metadata: dict[str, Any]

    def to_prompt(self) -> str:
        return "Mock context prompt"


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
    async def test_global_search_with_hybrid_engine(self, mock_neo4j_pool, mock_llm):
        """Test global search engine with hybrid engine reference."""
        mock_hybrid = MagicMock()
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            hybrid_engine=mock_hybrid,
        )

        assert engine._hybrid_engine is mock_hybrid


class TestGlobalSearchEngineSearch:
    """Tests for search method."""

    @pytest.mark.asyncio
    async def test_search_no_communities_at_all(self, mock_neo4j_pool, mock_llm):
        """Test search when no communities exist in the graph."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Mock no relevant communities and no communities at all
        engine._get_community_contexts = AsyncMock(return_value=[])
        engine._has_any_communities = AsyncMock(return_value=False)

        result = await engine.search("test query")

        assert "尚未初始化" in result.answer
        assert result.metadata["hint"] == "run POST /api/v1/admin/communities/rebuild"

    @pytest.mark.asyncio
    async def test_search_no_relevant_communities_but_some_exist(self, mock_neo4j_pool, mock_llm):
        """Test search when no relevant communities but some exist."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._get_community_contexts = AsyncMock(return_value=[])
        engine._has_any_communities = AsyncMock(return_value=True)

        result = await engine.search("test query")

        assert "No relevant communities" in result.answer

    @pytest.mark.asyncio
    async def test_search_without_llm_returns_context(self, mock_neo4j_pool, mock_llm):
        """Test search with use_llm=False returns context info."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Mock communities - use_llm=False path needs communities
        mock_communities = [
            CommunityContext(
                id="comm-1",
                title="Test Community",
                summary="Test summary",
                entity_count=5,
                rank=1.0,
                similarity_score=0.9,
                full_content="Full content",
                key_entities=["Entity1"],
            ),
        ]

        engine._get_community_contexts = AsyncMock(return_value=mock_communities)

        result = await engine.search("test query", use_llm=False)

        assert "Found" in result.answer
        assert result.metadata["llm_used"] is False
        assert result.metadata["communities"] == 1

    @pytest.mark.asyncio
    async def test_search_with_llm_and_communities(self, mock_neo4j_pool, mock_llm):
        """Test full Map-Reduce search with LLM."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_communities = [
            CommunityContext(
                id="comm-1",
                title="Community A",
                summary="Summary A",
                entity_count=10,
                rank=2.0,
                similarity_score=0.95,
                full_content="Full report A",
                key_entities=["KeyEnt1"],
            ),
            CommunityContext(
                id="comm-2",
                title="Community B",
                summary="Summary B",
                entity_count=5,
                rank=1.0,
                similarity_score=0.85,
                full_content=None,  # Test fallback to summary
                key_entities=["KeyEnt2"],
            ),
        ]

        engine._get_community_contexts = AsyncMock(return_value=mock_communities)
        # Mock LLM calls for map and reduce phases
        mock_llm.call = AsyncMock(
            side_effect=["Map answer 1", "Map answer 2", "Final reduce answer"]
        )

        result = await engine.search("test query", use_llm=True)

        assert result.answer == "Final reduce answer"
        assert result.metadata["llm_used"] is True
        assert result.metadata["intermediate_count"] == 2

    @pytest.mark.asyncio
    async def test_search_handles_error(self, mock_neo4j_pool, mock_llm):
        """Test search handles errors gracefully."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._get_community_contexts = AsyncMock(side_effect=Exception("Database error"))

        result = await engine.search("test query")

        assert "failed" in result.answer.lower()
        assert result.confidence == 0.0


class TestGlobalSearchEngineGetCommunityContexts:
    """Tests for _get_community_contexts method."""

    @pytest.mark.asyncio
    async def test_get_community_contexts_returns_empty(self, mock_neo4j_pool, mock_llm):
        """Test _get_community_contexts with no communities."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        engine._context_builder._find_relevant_communities = AsyncMock(
            return_value=([], False, "vector_similarity")
        )

        contexts = await engine._get_community_contexts("test query", level=0)

        assert contexts == []

    @pytest.mark.asyncio
    async def test_get_community_contexts_returns_contexts(self, mock_neo4j_pool, mock_llm):
        """Test _get_community_contexts returns community contexts."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_community_data = [
            {
                "id": "c1",
                "title": "Test Community",
                "summary": "Test summary",
                "entity_count": 10,
                "rank": 1.5,
                "similarity_score": 0.8,
                "full_content": "Full content",
                "key_entities": ["Entity1"],
            },
        ]
        engine._context_builder._find_relevant_communities = AsyncMock(
            return_value=(mock_community_data, False, "vector_similarity")
        )
        engine._context_builder._get_community_entities = AsyncMock(
            return_value=[{"canonical_name": "Entity1", "type": "Person"}]
        )

        contexts = await engine._get_community_contexts("test query", level=0)

        assert len(contexts) == 1
        assert contexts[0].id == "c1"
        assert contexts[0].title == "Test Community"


class TestGlobalSearchEnginePromptBuilding:
    """Tests for prompt building methods."""

    def test_build_map_prompt_with_full_content(self, mock_neo4j_pool, mock_llm):
        """Test _build_map_prompt with full_content available."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        community = CommunityContext(
            id="c1",
            title="Test Community",
            summary="Short summary",
            entity_count=20,
            rank=1.0,
            similarity_score=0.9,
            full_content="Full detailed report content",
            key_entities=["EntityA", "EntityB"],
        )

        prompt = engine._build_map_prompt("What is this about?", community)

        assert "Full detailed report content" in prompt
        assert "EntityA" in prompt
        assert "Test Community" in prompt

    def test_build_map_prompt_without_full_content(self, mock_neo4j_pool, mock_llm):
        """Test _build_map_prompt falls back to summary when full_content is None."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        community = CommunityContext(
            id="c1",
            title="Fallback Community",
            summary="Summary text",
            entity_count=5,
            rank=1.0,
            similarity_score=0.8,
            full_content=None,
            key_entities=None,
        )

        prompt = engine._build_map_prompt("Query?", community)

        assert "Summary text" in prompt
        assert "Fallback Community" in prompt

    def test_build_reduce_prompt(self, mock_neo4j_pool, mock_llm):
        """Test _build_reduce_prompt with multiple answers."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        intermediate_answers = ["Answer from community 1", "Answer from community 2"]
        community_weights = [
            {"community_id": "c1", "title": "Community A", "weight": 0.95},
            {"community_id": "c2", "title": "Community B", "weight": 0.85},
        ]

        prompt = engine._build_reduce_prompt("Test query", intermediate_answers, community_weights)

        assert "Test query" in prompt
        assert "Answer from community 1" in prompt
        assert "Community A" in prompt
        assert "Most Relevant Community: Community A" in prompt

    def test_build_reduce_prompt_empty_weights(self, mock_neo4j_pool, mock_llm):
        """Test _build_reduce_prompt with empty weights."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        prompt = engine._build_reduce_prompt("Query", ["Answer"], [])

        assert "Most Relevant Community: N/A" in prompt


class TestGlobalSearchEngineConfidence:
    """Tests for confidence estimation methods."""

    def test_estimate_confidence_empty_answers(self, mock_neo4j_pool, mock_llm):
        """Test _estimate_confidence with empty answers."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        confidence = engine._estimate_confidence([])

        assert confidence == 0.0

    def test_estimate_confidence_with_answers(self, mock_neo4j_pool, mock_llm):
        """Test _estimate_confidence with multiple answers."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # 3 answers with total length > 500
        answers = [
            "This is a detailed answer with enough content. " * 10,  # ~520 chars
            "Another answer with some content.",
            "Third answer with more content.",
        ]
        confidence = engine._estimate_confidence(answers)

        # Base 0.5 + 0.1 for 3 answers + 0.2 for >500 chars + 0.1 for all non-empty
        assert confidence == 0.9

    def test_estimate_confidence_short_answers(self, mock_neo4j_pool, mock_llm):
        """Test _estimate_confidence with short answers."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        answers = ["Short", "Answers"]
        confidence = engine._estimate_confidence(answers)

        # Base 0.5, no +0.1 for <3 answers, no +0.2 for <=500 chars, +0.1 for all non-empty
        assert confidence == 0.6


class TestGlobalSearchEngineSimple:
    """Tests for search_simple method."""

    @pytest.mark.asyncio
    async def test_search_simple_without_llm(self, mock_neo4j_pool, mock_llm):
        """Test search_simple with use_llm=False."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_context = MockContext(
            query="test",
            sections=[],
            total_tokens=500,
            max_tokens=8000,
            metadata={"total_communities": 3, "search_method": "vector"},
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search_simple("test query", use_llm=False)

        assert "3 communities" in result.answer
        assert result.metadata["llm_used"] is False

    @pytest.mark.asyncio
    async def test_search_simple_with_llm(self, mock_neo4j_pool, mock_llm):
        """Test search_simple with LLM generation."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_context = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=1000,
            max_tokens=8000,
            metadata={"total_communities": 2},
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)
        mock_llm.call = AsyncMock(return_value="LLM generated answer")

        result = await engine.search_simple("test query", use_llm=True)

        assert result.answer == "LLM generated answer"
        assert result.metadata["llm_used"] is True

    @pytest.mark.asyncio
    async def test_search_simple_handles_llm_error(self, mock_neo4j_pool, mock_llm):
        """Test search_simple handles LLM errors gracefully."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_context = MockContext(
            query="test",
            sections=[],
            total_tokens=100,
            max_tokens=8000,
            metadata={},
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)
        mock_llm.call = AsyncMock(side_effect=Exception("LLM failed"))

        result = await engine.search_simple("test query", use_llm=True)

        assert "failed" in result.answer.lower()
        assert result.confidence == 0.0


class TestGlobalSearchEngineSimpleConfidence:
    """Tests for _estimate_simple_confidence method."""

    def test_estimate_simple_confidence_empty_sections(self, mock_neo4j_pool, mock_llm):
        """Test confidence with empty sections."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_context = MockContext(
            query="test",
            sections=[],  # Empty sections
            total_tokens=0,
            max_tokens=8000,
            metadata={"total_communities": 0},
        )

        confidence = engine._estimate_simple_confidence(mock_context)

        assert confidence == 0.0

    def test_estimate_simple_confidence_with_communities(self, mock_neo4j_pool, mock_llm):
        """Test confidence with multiple communities."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_context = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=1500,  # > 1000 for bonus
            max_tokens=8000,
            metadata={"total_communities": 3},  # >= 3 for bonus
        )

        confidence = engine._estimate_simple_confidence(mock_context)

        # Base 0.4 + 0.2 for >=3 communities + 0.2 for >1000 tokens
        assert confidence == 0.8

    def test_estimate_simple_confidence_one_community(self, mock_neo4j_pool, mock_llm):
        """Test confidence with one community."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_context = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=500,  # <= 1000, no bonus
            max_tokens=8000,
            metadata={"total_communities": 1},
        )

        confidence = engine._estimate_simple_confidence(mock_context)

        # Base 0.4 + 0.1 for >=1 community
        assert confidence == 0.5


class TestCommunityContext:
    """Tests for CommunityContext dataclass."""

    def test_community_context_defaults(self):
        """Test CommunityContext with default values."""
        ctx = CommunityContext(
            id="test-id",
            title="Test Title",
            summary="Test summary",
            entity_count=10,
            rank=1.0,
            similarity_score=0.8,
        )

        assert ctx.full_content is None
        assert ctx.key_entities is None
        assert ctx.entities is None

    def test_community_context_with_all_fields(self):
        """Test CommunityContext with all fields populated."""
        ctx = CommunityContext(
            id="full-id",
            title="Full Title",
            summary="Summary",
            entity_count=20,
            rank=2.0,
            similarity_score=0.95,
            full_content="Full report content",
            key_entities=["Entity1", "Entity2"],
            entities=[{"name": "Entity1", "type": "Person"}],
        )

        assert ctx.full_content == "Full report content"
        assert ctx.key_entities == ["Entity1", "Entity2"]
        assert len(ctx.entities) == 1
