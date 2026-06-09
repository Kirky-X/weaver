# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GlobalSearchEngine - comprehensive coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.constants import SearchMode
from modules.knowledge.search.engines.global_search import (
    CommunityContext,
    GlobalSearchEngine,
    MapReduceResult,
)
from modules.knowledge.search.engines.local_search import SearchResult


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


def _make_mock_context_builder():
    """Create a mock context builder."""
    builder = AsyncMock()
    builder._pool = None
    return builder


def _make_mock_llm():
    """Create a mock LLM client."""
    return AsyncMock()


class TestGlobalSearchEngineSearch:
    """Tests for the search() method."""

    @pytest.mark.asyncio
    async def test_search_no_communities_at_all(self):
        """Test search when no communities exist in graph."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._get_community_contexts = AsyncMock(return_value=[])
        engine._has_any_communities = AsyncMock(return_value=False)

        result = await engine.search("test query")

        assert "尚未初始化" in result.answer
        assert result.confidence == 0.0
        assert result.metadata["hint"] == "run POST /api/v1/admin/communities/rebuild"

    @pytest.mark.asyncio
    async def test_search_no_relevant_communities_but_some_exist(self):
        """Test search when communities exist but none are relevant."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._get_community_contexts = AsyncMock(return_value=[])
        engine._has_any_communities = AsyncMock(return_value=True)

        result = await engine.search("test query")

        assert "No relevant communities" in result.answer
        assert result.metadata["search_type"] == SearchMode.GLOBAL.value

    @pytest.mark.asyncio
    async def test_search_no_relevant_with_local_fallback(self):
        """Test search falls back to local when no relevant communities."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        mock_local = AsyncMock()

        local_result = SearchResult(
            query="test",
            answer="Local answer",
            context_tokens=100,
            confidence=0.6,
        )
        mock_local.search = AsyncMock(return_value=local_result)

        engine = GlobalSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=mock_local,
        )
        engine._get_community_contexts = AsyncMock(return_value=[])
        engine._has_any_communities = AsyncMock(return_value=True)

        result = await engine.search("test query")

        assert result.metadata.get("fallback_from_global") is True

    @pytest.mark.asyncio
    async def test_search_use_llm_false(self):
        """Test search with use_llm=False returns context info."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        communities = [
            CommunityContext(
                id="c1",
                title="Test",
                summary="Summary text",
                entity_count=5,
                rank=1.0,
                similarity_score=0.9,
                full_content="Full content here",
                key_entities=["Entity1"],
            ),
        ]

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._get_community_contexts = AsyncMock(return_value=communities)

        result = await engine.search("test query", use_llm=False)

        assert "Found" in result.answer
        assert result.metadata["llm_used"] is False
        assert result.metadata["communities"] == 1

    @pytest.mark.asyncio
    async def test_search_with_llm_and_communities(self):
        """Test full Map-Reduce search with LLM."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        communities = [
            CommunityContext(
                id="c1",
                title="Community A",
                summary="Summary A",
                entity_count=10,
                rank=2.0,
                similarity_score=0.95,
                full_content="Full report A",
                key_entities=["KeyEnt1"],
            ),
            CommunityContext(
                id="c2",
                title="Community B",
                summary="Summary B",
                entity_count=5,
                rank=1.0,
                similarity_score=0.85,
                full_content=None,
                key_entities=["KeyEnt2"],
            ),
        ]

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._get_community_contexts = AsyncMock(return_value=communities)
        llm.call = AsyncMock(side_effect=["Map answer 1", "Map answer 2", "Final reduce answer"])

        result = await engine.search("test query", use_llm=True)

        assert result.answer == "Final reduce answer"
        assert result.metadata["llm_used"] is True

    @pytest.mark.asyncio
    async def test_search_low_relevance_skip(self):
        """Test search skips communities with very low relevance."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        communities = [
            CommunityContext(
                id="c1",
                title="Low Relevance",
                summary="Summary",
                entity_count=5,
                rank=1.0,
                similarity_score=0.1,  # Below 0.15 threshold
                full_content="Content",
                key_entities=[],
            ),
        ]

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._get_community_contexts = AsyncMock(return_value=communities)

        result = await engine.search("test query")

        assert result.metadata.get("low_relevance_skip") is True
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_search_exception_handling(self):
        """Test search handles exceptions gracefully."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._get_community_contexts = AsyncMock(side_effect=Exception("Unexpected error"))

        result = await engine.search("test query")

        assert "failed" in result.answer.lower()
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_search_local_fallback_dict_result(self):
        """Test local fallback when local engine returns dict."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        mock_local = AsyncMock()

        local_dict = {
            "query": "test",
            "answer": "Local dict answer",
            "context_tokens": 100,
            "confidence": 0.6,
            "metadata": {},
        }
        mock_local.search = AsyncMock(return_value=local_dict)

        engine = GlobalSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=mock_local,
        )
        engine._get_community_contexts = AsyncMock(return_value=[])
        engine._has_any_communities = AsyncMock(return_value=True)

        result = await engine.search("test query")

        # When local engine returns a dict, global search returns that dict
        # with metadata updated in-place (not a SearchResult object)
        assert isinstance(result, dict)
        assert result["metadata"].get("fallback_from_global") is True


class TestGlobalSearchEngineSearchSimple:
    """Tests for search_simple() method."""

    @pytest.mark.asyncio
    async def test_search_simple_without_llm(self):
        """Test search_simple with use_llm=False."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        mock_context = MockContext(
            query="test",
            sections=[],
            total_tokens=500,
            max_tokens=8000,
            metadata={"total_communities": 3, "search_method": "vector"},
        )

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search_simple("test query", use_llm=False)

        assert "3 communities" in result.answer
        assert result.metadata["llm_used"] is False

    @pytest.mark.asyncio
    async def test_search_simple_with_llm(self):
        """Test search_simple with LLM generation."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        mock_context = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=1000,
            max_tokens=8000,
            metadata={"total_communities": 2},
        )

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)
        llm.call = AsyncMock(return_value="LLM generated answer")

        result = await engine.search_simple("test query", use_llm=True)

        assert result.answer == "LLM generated answer"
        assert result.metadata["llm_used"] is True

    @pytest.mark.asyncio
    async def test_search_simple_handles_llm_error(self):
        """Test search_simple handles LLM errors gracefully."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()

        mock_context = MockContext(
            query="test",
            sections=[],
            total_tokens=100,
            max_tokens=8000,
            metadata={},
        )

        engine = GlobalSearchEngine(context_builder=context_builder, llm=llm)
        engine._context_builder.build = AsyncMock(return_value=mock_context)
        llm.call = AsyncMock(side_effect=Exception("LLM failed"))

        result = await engine.search_simple("test query", use_llm=True)

        assert "failed" in result.answer.lower()
        assert result.confidence == 0.0


class TestGlobalSearchEngineEstimateConfidence:
    """Tests for _estimate_confidence method."""

    def test_confidence_empty_answers(self):
        """Test confidence with empty answers."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())
        assert engine._estimate_confidence([]) == 0.0

    def test_confidence_with_community_scores(self):
        """Test confidence with community similarity scores."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        answers = ["Answer 1", "Answer 2"]
        scores = [0.9, 0.8]

        confidence = engine._estimate_confidence(answers, scores)

        # top_score * 0.6 + avg_score * 0.2 + consistency bonus
        expected_base = 0.9 * 0.6 + 0.85 * 0.2
        assert confidence > 0.0
        assert confidence <= 1.0

    def test_confidence_high_consistency_bonus(self):
        """Test confidence gets consistency bonus for low variance."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        answers = ["A" * 600, "B" * 400]  # > 500 chars total
        scores = [0.8, 0.8]  # Same scores = low variance

        confidence = engine._estimate_confidence(answers, scores)

        # Should get consistency bonus
        assert confidence > 0.8 * 0.6 + 0.8 * 0.2

    def test_confidence_no_scores_fallback(self):
        """Test confidence with no community scores uses fallback."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        answers = ["Short answer"]
        confidence = engine._estimate_confidence(answers, None)

        # Fallback base 0.3 + non-empty bonus 0.03
        assert confidence == pytest.approx(0.33)

    def test_confidence_length_bonus(self):
        """Test confidence gets bonus for longer answers."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        short_answers = ["Short"]
        long_answers = ["A" * 600]

        short_conf = engine._estimate_confidence(short_answers)
        long_conf = engine._estimate_confidence(long_answers)

        assert long_conf > short_conf

    def test_confidence_non_empty_bonus(self):
        """Test confidence gets bonus when all answers are non-empty."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        all_non_empty = ["Answer 1", "Answer 2"]
        some_empty = ["Answer 1", ""]

        conf_non_empty = engine._estimate_confidence(all_non_empty)
        conf_some_empty = engine._estimate_confidence(some_empty)

        assert conf_non_empty > conf_some_empty

    def test_confidence_capped_at_one(self):
        """Test confidence is capped at 1.0."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        answers = ["A" * 1000]
        scores = [1.0]

        confidence = engine._estimate_confidence(answers, scores)
        assert confidence <= 1.0

    def test_confidence_minimum_zero(self):
        """Test confidence is at least 0.0."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        answers = [""]
        confidence = engine._estimate_confidence(answers)
        assert confidence >= 0.0


class TestGlobalSearchEngineEstimateSimpleConfidence:
    """Tests for _estimate_simple_confidence method."""

    def test_empty_sections(self):
        """Test confidence with empty sections."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        ctx = MockContext(
            query="test",
            sections=[],
            total_tokens=0,
            max_tokens=8000,
            metadata={"total_communities": 0},
        )

        assert engine._estimate_simple_confidence(ctx) == 0.0

    def test_many_communities_high_tokens(self):
        """Test confidence with many communities and high tokens."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        ctx = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=1500,
            max_tokens=8000,
            metadata={"total_communities": 3},
        )

        # Base 0.4 + 0.2 for >=3 communities + 0.2 for >1000 tokens
        assert engine._estimate_simple_confidence(ctx) == 0.8

    def test_one_community(self):
        """Test confidence with one community."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        ctx = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=500,
            max_tokens=8000,
            metadata={"total_communities": 1},
        )

        # Base 0.4 + 0.1 for >=1 community
        assert engine._estimate_simple_confidence(ctx) == 0.5


class TestGlobalSearchEnginePromptBuilding:
    """Tests for prompt building methods."""

    def test_build_map_prompt_with_full_content(self):
        """Test _build_map_prompt with full_content available."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

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

    def test_build_map_prompt_without_full_content(self):
        """Test _build_map_prompt falls back to summary."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

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

    def test_build_reduce_prompt(self):
        """Test _build_reduce_prompt with multiple answers."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        intermediate_answers = ["Answer from community 1", "Answer from community 2"]
        community_weights = [
            {"community_id": "c1", "title": "Community A", "weight": 0.95},
            {"community_id": "c2", "title": "Community B", "weight": 0.85},
        ]

        prompt = engine._build_reduce_prompt("Test query", intermediate_answers, community_weights)

        assert "Test query" in prompt
        assert "Community A" in prompt
        assert "Most Relevant Community: Community A" in prompt

    def test_build_reduce_prompt_empty_weights(self):
        """Test _build_reduce_prompt with empty weights."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        prompt = engine._build_reduce_prompt("Query", ["Answer"], [])

        assert "Most Relevant Community: N/A" in prompt

    def test_build_simple_prompt(self):
        """Test _build_simple_prompt builds correct prompt."""
        engine = GlobalSearchEngine(context_builder=MagicMock(), llm=MagicMock())

        mock_context = MockContext(
            query="test",
            sections=[],
            total_tokens=100,
            max_tokens=8000,
            metadata={},
        )

        prompt = engine._build_simple_prompt("What is the topic?", mock_context)

        assert "What is the topic?" in prompt
        assert "Mock context prompt" in prompt


class TestGlobalSearchEngineCollectEntities:
    """Tests for _collect_entities static method."""

    def test_collect_entities_with_key_entities(self):
        """Test collecting entities from communities with key_entities."""
        communities = [
            CommunityContext(
                id="c1",
                title="A",
                summary="",
                entity_count=5,
                rank=1.0,
                similarity_score=0.9,
                key_entities=["E1", "E2"],
            ),
            CommunityContext(
                id="c2",
                title="B",
                summary="",
                entity_count=3,
                rank=1.0,
                similarity_score=0.8,
                key_entities=["E2", "E3"],
            ),
        ]

        entities = GlobalSearchEngine._collect_entities(communities)

        assert "E1" in entities
        assert "E2" in entities
        assert "E3" in entities
        assert len(entities) == 3  # E2 deduplicated

    def test_collect_entities_no_key_entities(self):
        """Test collecting entities when key_entities is None."""
        communities = [
            CommunityContext(
                id="c1",
                title="A",
                summary="",
                entity_count=5,
                rank=1.0,
                similarity_score=0.9,
                key_entities=None,
            ),
        ]

        entities = GlobalSearchEngine._collect_entities(communities)
        assert entities == []


class TestGlobalSearchEngineGetTimeout:
    """Tests for _get_timeout method."""

    def test_get_timeout_with_settings(self):
        """Test _get_timeout with search settings."""
        settings = MagicMock()
        settings.global_map_community_timeout = 20.0

        engine = GlobalSearchEngine(
            context_builder=MagicMock(),
            llm=MagicMock(),
            search_settings=settings,
        )

        assert engine._get_timeout("global_map_community_timeout", 15.0) == 20.0

    def test_get_timeout_without_settings(self):
        """Test _get_timeout without search settings returns default."""
        engine = GlobalSearchEngine(
            context_builder=MagicMock(),
            llm=MagicMock(),
        )

        assert engine._get_timeout("global_map_community_timeout", 15.0) == 15.0

    def test_get_timeout_missing_field(self):
        """Test _get_timeout with missing field returns default."""
        settings = MagicMock(spec=[])  # No attributes

        engine = GlobalSearchEngine(
            context_builder=MagicMock(),
            llm=MagicMock(),
            search_settings=settings,
        )

        assert engine._get_timeout("nonexistent_field", 30.0) == 30.0


class TestCommunityContext:
    """Tests for CommunityContext dataclass."""

    def test_defaults(self):
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

    def test_all_fields(self):
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


class TestMapReduceResult:
    """Tests for MapReduceResult dataclass."""

    def test_creation(self):
        """Test creating a MapReduceResult."""
        result = MapReduceResult(
            query="test",
            final_answer="answer",
            intermediate_answers=["int1", "int2"],
            context_tokens=500,
            communities_searched=3,
            confidence=0.85,
            metadata={"key": "value"},
        )

        assert result.query == "test"
        assert result.final_answer == "answer"
        assert len(result.intermediate_answers) == 2
        assert result.communities_searched == 3
