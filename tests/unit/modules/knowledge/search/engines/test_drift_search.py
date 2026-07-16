# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for DRIFTSearchEngine - comprehensive coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.engines.drift_search import (
    DriftConfig,
    DriftHierarchy,
    DriftResult,
    DRIFTSearchEngine,
)
from modules.knowledge.search.engines.local_search import SearchResult


def _make_mock_context_builder(total_communities=0, community_ids=None):
    """Create a mock context builder."""
    builder = MagicMock()
    mock_context = MagicMock()
    mock_context.metadata = {
        "total_communities": total_communities,
        "community_ids": community_ids or [],
    }
    mock_context.to_prompt = MagicMock(return_value="Community context prompt")
    mock_context.to_string = MagicMock(return_value="Community context string")
    builder.build = AsyncMock(return_value=mock_context)
    return builder


def _make_mock_llm(response_text="Test answer"):
    """Create a mock LLM client."""
    llm = MagicMock()
    llm.call_at = AsyncMock(return_value=response_text)
    llm.call = AsyncMock(return_value=response_text)
    return llm


def _make_mock_local_engine(answer="Local answer", confidence=0.75, source_entities=None):
    """Create a mock LocalSearchEngine."""
    engine = MagicMock()
    result = SearchResult(
        query="test question",
        answer=answer,
        context_tokens=100,
        confidence=confidence,
    )
    # Add source_entities as attribute
    result.source_entities = source_entities or []
    engine.search = AsyncMock(return_value=result)
    return engine


class TestDriftSearchEngineSearch:
    """Tests for the main search() method."""

    @pytest.mark.asyncio
    async def test_search_fallback_to_local(self):
        """Test search falls back to local when no communities found."""
        context_builder = _make_mock_context_builder(total_communities=0)
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(answer="Local fallback answer")

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
        )

        result = await engine.search("test query")

        assert result.drift_mode == "fallback_local"
        assert result.answer == "Local fallback answer"
        assert result.primer_communities == 0
        assert result.follow_up_iterations == 0

    @pytest.mark.asyncio
    async def test_search_full_drift_flow(self):
        """Test full DRIFT search flow with primer + follow-up + aggregate."""
        context_builder = _make_mock_context_builder(
            total_communities=3, community_ids=["c1", "c2", "c3"]
        )
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(confidence=0.6)

        # Mock call_at for primer and aggregate phases
        llm.call_at = AsyncMock(
            side_effect=[
                "Initial answer\n\n1. Follow up question one?\n2. Follow up question two?",
                "Final aggregated answer [置信度: 0.85]",
            ]
        )

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
            config=DriftConfig(max_follow_ups=2, confidence_threshold=0.99),
        )

        result = await engine.search("complex query")

        assert result.query == "complex query"
        assert result.drift_mode == "normal"
        assert result.primer_communities == 3
        assert result.confidence == 0.85
        assert result.total_llm_calls >= 2  # primer + aggregate at minimum

    @pytest.mark.asyncio
    async def test_search_returns_drift_result(self):
        """Test that search returns a DriftResult instance."""
        context_builder = _make_mock_context_builder(total_communities=0)
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine()

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
        )

        result = await engine.search("test")

        assert isinstance(result, DriftResult)

    @pytest.mark.asyncio
    async def test_search_metadata_populated(self):
        """Test that search result metadata is populated."""
        context_builder = _make_mock_context_builder(
            total_communities=2, community_ids=["c1", "c2"]
        )
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(confidence=0.6)

        llm.call_at = AsyncMock(
            side_effect=[
                "Answer\n1. Question?",
                "Final [置信度: 0.7]",
            ]
        )

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
            config=DriftConfig(max_follow_ups=1, confidence_threshold=0.99),
        )

        result = await engine.search("query")

        assert "primer_communities" in result.metadata
        assert "follow_up_iterations" in result.metadata
        assert "total_llm_calls" in result.metadata


class TestDriftSearchEnginePrimerPhase:
    """Tests for _primer_phase method."""

    @pytest.mark.asyncio
    async def test_primer_phase_no_communities(self):
        """Test primer phase returns fallback when no communities."""
        context_builder = _make_mock_context_builder(total_communities=0)
        llm = _make_mock_llm()

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)
        result = await engine._primer_phase("test query")

        assert result["fallback"] is True
        assert result["answer"] == ""
        assert result["follow_up_questions"] == []
        assert result["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_primer_phase_with_communities(self):
        """Test primer phase with communities found."""
        context_builder = _make_mock_context_builder(
            total_communities=2, community_ids=["c1", "c2"]
        )
        llm = _make_mock_llm("Initial answer\n\n1. Follow up question?")

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)
        result = await engine._primer_phase("test query")

        assert result["fallback"] is False
        assert result["community_count"] == 2
        assert result["llm_calls"] == 1
        assert len(result["follow_up_questions"]) > 0

    @pytest.mark.asyncio
    async def test_primer_phase_llm_none_response(self):
        """Test primer phase handles None LLM response."""
        context_builder = _make_mock_context_builder(total_communities=2, community_ids=["c1"])
        llm = _make_mock_llm()
        llm.call_at = AsyncMock(return_value=None)

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)
        result = await engine._primer_phase("test query")

        assert result["fallback"] is False
        assert result["answer"] == ""

    @pytest.mark.asyncio
    async def test_primer_phase_source_communities_tracked(self):
        """Test primer phase tracks source community IDs."""
        context_builder = _make_mock_context_builder(
            total_communities=2, community_ids=["c1", "c2"]
        )
        llm = _make_mock_llm("Answer text")

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)
        result = await engine._primer_phase("test query")

        assert result["source_communities"] == ["c1", "c2"]


class TestDriftSearchEngineFollowUpPhase:
    """Tests for _follow_up_phase method."""

    @pytest.mark.asyncio
    async def test_follow_up_empty_questions(self):
        """Test follow-up phase with no questions."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine()

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
        )

        result = await engine._follow_up_phase(
            query="test", initial_answer="answer", follow_up_questions=[]
        )

        assert result["results"] == []
        assert result["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_follow_up_processes_questions(self):
        """Test follow-up phase processes questions."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(confidence=0.6)

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
            config=DriftConfig(max_follow_ups=3, confidence_threshold=0.99),
        )

        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=["Question 1?", "Question 2?"],
        )

        assert len(result["results"]) == 2
        assert result["llm_calls"] == 2

    @pytest.mark.asyncio
    async def test_follow_up_early_termination(self):
        """Test follow-up phase stops on high confidence."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(confidence=0.9)

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
            config=DriftConfig(confidence_threshold=0.8, max_follow_ups=3),
        )

        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=["Q1?", "Q2?", "Q3?"],
        )

        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_follow_up_skips_blank_questions(self):
        """Test follow-up phase skips empty/whitespace questions."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(confidence=0.5)

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
            config=DriftConfig(max_follow_ups=5, confidence_threshold=0.99),
        )

        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=["", "   ", "Valid question?"],
        )

        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_follow_up_respects_max_follow_ups(self):
        """Test follow-up phase respects max_follow_ups config."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(confidence=0.5)

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
            config=DriftConfig(max_follow_ups=1, confidence_threshold=0.99),
        )

        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=["Q1?", "Q2?", "Q3?"],
        )

        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_follow_up_result_structure(self):
        """Test follow-up result contains expected fields."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        local_engine = _make_mock_local_engine(
            answer="Local answer", confidence=0.7, source_entities=["E1"]
        )

        engine = DRIFTSearchEngine(
            context_builder=context_builder,
            llm=llm,
            local_engine=local_engine,
            config=DriftConfig(max_follow_ups=1, confidence_threshold=0.99),
        )

        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=["Q1?"],
        )

        fu = result["results"][0]
        assert fu["question"] == "Q1?"
        assert fu["answer"] == "Local answer"
        assert fu["confidence"] == 0.7


class TestDriftSearchEngineAggregateResults:
    """Tests for _aggregate_results method."""

    @pytest.mark.asyncio
    async def test_aggregate_basic(self):
        """Test basic result aggregation."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm("Aggregated answer [置信度: 0.8]")

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)

        result = await engine._aggregate_results(
            query="test",
            primer={"answer": "Initial"},
            follow_ups=[{"question": "Q1?", "answer": "A1"}],
        )

        assert "answer" in result
        assert "confidence" in result
        assert result["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_aggregate_no_follow_ups(self):
        """Test aggregation with no follow-up results."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm("Final answer [置信度: 0.6]")

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)

        result = await engine._aggregate_results(
            query="test",
            primer={"answer": "Initial answer"},
            follow_ups=[],
        )

        assert result["confidence"] == 0.6

    @pytest.mark.asyncio
    async def test_aggregate_none_llm_response(self):
        """Test aggregation with None LLM response."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm()
        llm.call_at = AsyncMock(return_value=None)

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)

        result = await engine._aggregate_results(
            query="test",
            primer={"answer": "Initial"},
            follow_ups=[],
        )

        assert result["confidence"] == 0.5  # default

    @pytest.mark.asyncio
    async def test_aggregate_multiple_follow_ups(self):
        """Test aggregation with multiple follow-up results."""
        context_builder = _make_mock_context_builder()
        llm = _make_mock_llm("Combined answer [置信度: 0.9]")

        engine = DRIFTSearchEngine(context_builder=context_builder, llm=llm)

        result = await engine._aggregate_results(
            query="test",
            primer={"answer": "Initial"},
            follow_ups=[
                {"question": "Q1?", "answer": "A1"},
                {"question": "Q2?", "answer": "A2"},
                {"question": "Q3?", "answer": "A3"},
            ],
        )

        assert result["confidence"] == 0.9


class TestDriftSearchEngineExtractMethods:
    """Tests for text extraction helper methods."""

    @pytest.fixture
    def engine(self):
        """Create engine for testing extract methods."""
        return DRIFTSearchEngine(context_builder=MagicMock(), llm=MagicMock())

    def test_extract_follow_up_questions_numbered(self, engine):
        """Test extraction of numbered questions."""
        text = "Answer\n\n1. First question?\n2. Second question?\n3. Third question?"
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) == 3

    def test_extract_follow_up_questions_dash_markers(self, engine):
        """Test extraction with dash markers."""
        text = "Answer\n\n- Question one?\n- Question two?"
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) >= 1

    def test_extract_follow_up_questions_asterisk_markers(self, engine):
        """Test extraction with asterisk markers."""
        text = "Answer\n\n* Question one?\n* Question two?"
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) >= 1

    def test_extract_follow_up_questions_max_three(self, engine):
        """Test that extraction returns at most 3 questions."""
        text = "1. Q1?\n2. Q2?\n3. Q3?\n4. Q4?\n5. Q5?"
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) == 3

    def test_extract_follow_up_questions_no_questions(self, engine):
        """Test extraction with no questions in text."""
        text = "This is just an answer with no questions."
        questions = engine._extract_follow_up_questions(text)
        assert questions == []

    def test_extract_follow_up_questions_chinese_question_mark(self, engine):
        """Test extraction with Chinese question marks."""
        text = "1. 第一个问题？\n2. 第二个问题？"
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) == 2

    def test_extract_answer_with_marker(self, engine):
        """Test answer extraction with follow-up marker."""
        text = "This is the answer.\n\n后续问题：\n1. Q1?"
        answer = engine._extract_answer(text)
        assert "This is the answer" in answer
        assert "后续问题" not in answer

    def test_extract_answer_with_english_marker(self, engine):
        """Test answer extraction with English follow-up marker."""
        text = "Answer content\n\nFollow-up questions:\n1. Q1?"
        answer = engine._extract_answer(text)
        assert "Answer content" in answer

    def test_extract_answer_no_marker(self, engine):
        """Test answer extraction when no marker found."""
        text = "This is the complete answer."
        answer = engine._extract_answer(text)
        assert answer == "This is the complete answer."

    def test_extract_confidence_chinese_colon(self, engine):
        """Test confidence extraction with Chinese colon."""
        assert engine._extract_confidence("Answer [置信度：0.85]") == 0.85

    def test_extract_confidence_english_colon(self, engine):
        """Test confidence extraction with English colon."""
        assert engine._extract_confidence("Answer [置信度: 0.75]") == 0.75

    def test_extract_confidence_english_marker(self, engine):
        """Test confidence extraction with English marker."""
        assert engine._extract_confidence("Answer [confidence: 0.65]") == 0.65

    def test_extract_confidence_no_marker(self, engine):
        """Test confidence extraction without marker returns default."""
        assert engine._extract_confidence("Answer without confidence") == 0.5

    def test_extract_confidence_invalid_value(self, engine):
        """Test confidence extraction with invalid value returns default."""
        assert engine._extract_confidence("Answer [置信度: invalid]") == 0.5

    def test_extract_confidence_standalone(self, engine):
        """Test confidence extraction with standalone pattern."""
        assert engine._extract_confidence("Answer 置信度：0.9") == 0.9

    def test_remove_confidence_marker_chinese(self, engine):
        """Test removal of Chinese confidence marker."""
        result = engine._remove_confidence_marker("Answer [置信度: 0.85]")
        assert "[置信度" not in result
        assert "Answer" in result

    def test_remove_confidence_marker_english(self, engine):
        """Test removal of English confidence marker."""
        result = engine._remove_confidence_marker("Answer [confidence: 0.75]")
        assert "[confidence" not in result.lower()

    def test_remove_confidence_marker_multiple(self, engine):
        """Test removal of multiple confidence markers."""
        result = engine._remove_confidence_marker("Part1 [置信度: 0.8] Part2 [confidence: 0.9]")
        assert "[置信度" not in result
        assert "[confidence" not in result.lower()
        assert "Part1" in result
        assert "Part2" in result

    def test_remove_confidence_marker_none(self, engine):
        """Test removal when no marker present."""
        text = "Answer without markers"
        result = engine._remove_confidence_marker(text)
        assert result == text


class TestDriftConfigExtended:
    """Extended tests for DriftConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DriftConfig()
        assert config.primer_k == 3
        assert config.max_follow_ups == 2
        assert config.confidence_threshold == 0.7
        assert config.max_concurrent == 5
        assert config.similarity_threshold == 0.5

    def test_custom_values(self):
        """Test custom configuration values."""
        config = DriftConfig(
            primer_k=5,
            max_follow_ups=4,
            confidence_threshold=0.9,
            max_concurrent=10,
            similarity_threshold=0.7,
        )
        assert config.primer_k == 5
        assert config.max_follow_ups == 4
        assert config.confidence_threshold == 0.9


class TestDriftHierarchyExtended:
    """Extended tests for DriftHierarchy."""

    def test_default_values(self):
        """Test default hierarchy values."""
        h = DriftHierarchy()
        assert h.primer == {}
        assert h.follow_ups == []

    def test_custom_values(self):
        """Test custom hierarchy values."""
        h = DriftHierarchy(
            primer={"answer": "test"},
            follow_ups=[{"q": "Q1?"}],
        )
        assert h.primer["answer"] == "test"
        assert len(h.follow_ups) == 1


class TestDriftResultExtended:
    """Extended tests for DriftResult."""

    def test_default_values(self):
        """Test default result values."""
        r = DriftResult(
            query="q",
            answer="a",
            confidence=0.8,
            hierarchy=DriftHierarchy(),
            primer_communities=3,
            follow_up_iterations=2,
            total_llm_calls=5,
        )
        assert r.drift_mode == "normal"
        assert r.metadata == {}

    def test_custom_values(self):
        """Test custom result values."""
        r = DriftResult(
            query="q",
            answer="a",
            confidence=0.8,
            hierarchy=DriftHierarchy(),
            primer_communities=3,
            follow_up_iterations=2,
            total_llm_calls=5,
            drift_mode="fallback_local",
            metadata={"key": "value"},
        )
        assert r.drift_mode == "fallback_local"
        assert r.metadata["key"] == "value"
