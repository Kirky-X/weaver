# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for DRIFTSearchEngine in knowledge module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.engines.drift_search import (
    DriftConfig,
    DriftHierarchy,
    DriftResult,
    DRIFTSearchEngine,
)


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


class TestDriftConfig:
    """Tests for DriftConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = DriftConfig()

        assert config.primer_k == 3
        assert config.max_follow_ups == 2
        assert config.confidence_threshold == 0.7
        assert config.max_concurrent == 5
        assert config.similarity_threshold == 0.5

    def test_custom_config(self):
        """Test custom configuration values."""
        config = DriftConfig(
            primer_k=5,
            max_follow_ups=3,
            confidence_threshold=0.8,
        )

        assert config.primer_k == 5
        assert config.max_follow_ups == 3
        assert config.confidence_threshold == 0.8


class TestDriftHierarchy:
    """Tests for DriftHierarchy dataclass."""

    def test_default_hierarchy(self):
        """Test default hierarchy values."""
        hierarchy = DriftHierarchy()

        assert hierarchy.primer == {}
        assert hierarchy.follow_ups == []

    def test_populated_hierarchy(self):
        """Test populated hierarchy."""
        hierarchy = DriftHierarchy(
            primer={"answer": "test"},
            follow_ups=[{"question": "Q1"}],
        )

        assert hierarchy.primer["answer"] == "test"
        assert len(hierarchy.follow_ups) == 1


class TestDriftResult:
    """Tests for DriftResult dataclass."""

    def test_default_result(self):
        """Test default result values."""
        result = DriftResult(
            query="test",
            answer="test answer",
            confidence=0.8,
            hierarchy=DriftHierarchy(),
            primer_communities=3,
            follow_up_iterations=2,
            total_llm_calls=5,
        )

        assert result.drift_mode == "normal"
        assert result.metadata == {}

    def test_result_with_metadata(self):
        """Test result with metadata."""
        result = DriftResult(
            query="test",
            answer="test",
            confidence=0.9,
            hierarchy=DriftHierarchy(),
            primer_communities=5,
            follow_up_iterations=3,
            total_llm_calls=10,
            drift_mode="fallback_local",
            metadata={"key": "value"},
        )

        assert result.drift_mode == "fallback_local"
        assert result.metadata["key"] == "value"


class TestDRIFTSearchEngineInit:
    """Tests for DRIFTSearchEngine initialization."""

    def test_init_with_required_params(self, mock_neo4j_pool, mock_llm):
        """Test initialization with required params."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        assert engine._pool is mock_neo4j_pool
        assert engine._llm is mock_llm
        assert engine._config is not None

    def test_init_with_custom_config(self, mock_neo4j_pool, mock_llm):
        """Test initialization with custom config."""
        config = DriftConfig(primer_k=10, max_follow_ups=5)
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            config=config,
        )

        assert engine._config.primer_k == 10
        assert engine._config.max_follow_ups == 5

    def test_init_with_local_engine(self, mock_neo4j_pool, mock_llm):
        """Test initialization with custom local engine."""
        mock_local = MagicMock()
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            local_engine=mock_local,
        )

        assert engine._local_engine is mock_local


class TestDRIFTSearchEngineExtraction:
    """Tests for text extraction methods."""

    @pytest.fixture
    def engine(self, mock_neo4j_pool, mock_llm):
        return DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

    def test_extract_follow_up_questions_numbered(self, engine):
        """Test extracting numbered questions."""
        text = """
        This is the answer.

        1. What is X?
        2. How does Y work?
        3. Why is Z important?
        """
        questions = engine._extract_follow_up_questions(text)

        assert len(questions) == 3
        assert "What is X?" in questions[0]

    def test_extract_follow_up_questions_bulleted(self, engine):
        """Test extracting bulleted questions."""
        text = """
        Answer here.

        - First question?
        - Second question?
        """
        questions = engine._extract_follow_up_questions(text)

        assert len(questions) == 2

    def test_extract_follow_up_questions_max_three(self, engine):
        """Test that only 3 questions are extracted."""
        text = """
        1. Q1?
        2. Q2?
        3. Q3?
        4. Q4?
        5. Q5?
        """
        questions = engine._extract_follow_up_questions(text)

        assert len(questions) == 3

    def test_extract_answer_with_marker(self, engine):
        """Test extracting answer before follow-up marker."""
        text = "This is the answer. 后续问题: 1. Q1?"
        answer = engine._extract_answer(text)

        assert "This is the answer." in answer
        assert "后续问题" not in answer

    def test_extract_answer_without_marker(self, engine):
        """Test extracting answer without marker."""
        text = "This is the complete answer."
        answer = engine._extract_answer(text)

        assert answer == "This is the complete answer."

    def test_extract_confidence_with_chinese_marker(self, engine):
        """Test extracting confidence with Chinese marker."""
        text = "Answer here. [置信度: 0.85]"
        confidence = engine._extract_confidence(text)

        assert confidence == 0.85

    def test_extract_confidence_with_english_marker(self, engine):
        """Test extracting confidence with English marker."""
        text = "Answer here. [confidence: 0.9]"
        confidence = engine._extract_confidence(text)

        assert confidence == 0.9

    def test_extract_confidence_default(self, engine):
        """Test default confidence when not found."""
        text = "Answer without confidence marker."
        confidence = engine._extract_confidence(text)

        assert confidence == 0.5

    def test_remove_confidence_marker(self, engine):
        """Test removing confidence marker from text."""
        text = "Answer text. [置信度: 0.85] More text."
        result = engine._remove_confidence_marker(text)

        assert "[置信度" not in result
        assert "Answer text." in result


class TestDRIFTSearchEngineSearch:
    """Tests for search method."""

    @pytest.fixture
    def engine(self, mock_neo4j_pool, mock_llm):
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )
        return engine

    @pytest.mark.asyncio
    async def test_search_fallback_to_local(self, engine, mock_llm):
        """Test search falls back to local when no communities."""
        mock_context = MockContext(
            query="test",
            sections=[],
            total_tokens=0,
            max_tokens=4000,
            metadata={"total_communities": 0},
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)
        engine._local_engine.search = AsyncMock(
            return_value=MagicMock(answer="Local answer", confidence=0.7)
        )

        result = await engine.search("test query")

        assert result.drift_mode == "fallback_local"
        assert result.answer == "Local answer"

    @pytest.mark.asyncio
    async def test_search_with_primer(self, engine, mock_llm):
        """Test search with primer phase."""
        mock_context = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=500,
            max_tokens=4000,
            metadata={"total_communities": 3, "community_ids": ["c1", "c2", "c3"]},
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        # Mock LLM call for primer
        mock_llm.call_at = AsyncMock(
            return_value="Initial answer.\n\n1. Follow up Q1?\n2. Follow up Q2?"
        )

        # Mock local engine for follow-ups
        mock_local_result = MagicMock()
        mock_local_result.answer = "Follow-up answer"
        mock_local_result.confidence = 0.8
        mock_local_result.source_entities = []
        engine._local_engine.search = AsyncMock(return_value=mock_local_result)

        result = await engine.search("test query")

        assert result.primer_communities == 3
        assert result.total_llm_calls > 0


class TestDRIFTSearchEnginePrimer:
    """Tests for _primer_phase method."""

    @pytest.fixture
    def engine(self, mock_neo4j_pool, mock_llm):
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )
        return engine

    @pytest.mark.asyncio
    async def test_primer_no_communities(self, engine):
        """Test primer phase with no communities."""
        mock_context = MockContext(
            query="test",
            sections=[],
            total_tokens=0,
            max_tokens=4000,
            metadata={"total_communities": 0},
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine._primer_phase("test query")

        assert result["fallback"] is True
        assert result["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_primer_with_communities(self, engine, mock_llm):
        """Test primer phase with communities."""
        mock_context = MockContext(
            query="test",
            sections=[MagicMock()],
            total_tokens=500,
            max_tokens=4000,
            metadata={"total_communities": 5, "community_ids": ["c1"]},
        )

        engine._context_builder.build = AsyncMock(return_value=mock_context)
        mock_llm.call_at = AsyncMock(return_value="Answer. 1. Q1?")

        result = await engine._primer_phase("test query")

        assert result["fallback"] is False
        assert result["community_count"] == 5
        assert result["llm_calls"] == 1


class TestDRIFTSearchEngineFollowUp:
    """Tests for _follow_up_phase method."""

    @pytest.fixture
    def engine(self, mock_neo4j_pool, mock_llm):
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )
        return engine

    @pytest.mark.asyncio
    async def test_follow_up_empty_questions(self, engine):
        """Test follow-up phase with empty questions."""
        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=[],
        )

        assert result["results"] == []
        assert result["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_follow_up_processes_questions(self, engine):
        """Test follow-up phase processes questions."""
        mock_result = MagicMock()
        mock_result.answer = "Follow-up answer"
        mock_result.confidence = 0.6
        mock_result.source_entities = []
        engine._local_engine.search = AsyncMock(return_value=mock_result)

        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=["Q1?", "Q2?"],
        )

        assert len(result["results"]) == 2
        assert result["llm_calls"] == 2

    @pytest.mark.asyncio
    async def test_follow_up_early_termination(self, engine):
        """Test follow-up stops at confidence threshold."""
        # Configure threshold
        engine._config.confidence_threshold = 0.7

        # First result has high confidence
        mock_result_high = MagicMock()
        mock_result_high.answer = "High confidence answer"
        mock_result_high.confidence = 0.85
        mock_result_high.source_entities = []
        engine._local_engine.search = AsyncMock(return_value=mock_result_high)

        result = await engine._follow_up_phase(
            query="test",
            initial_answer="initial",
            follow_up_questions=["Q1?", "Q2?", "Q3?"],
        )

        # Should stop after first question due to high confidence
        assert len(result["results"]) == 1


class TestDRIFTSearchEngineAggregate:
    """Tests for _aggregate_results method."""

    @pytest.fixture
    def engine(self, mock_neo4j_pool, mock_llm):
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )
        return engine

    @pytest.mark.asyncio
    async def test_aggregate_results(self, engine, mock_llm):
        """Test aggregating results."""
        mock_llm.call_at = AsyncMock(return_value="Final answer. [置信度: 0.85]")

        primer = {"answer": "Initial answer"}
        follow_ups = [{"question": "Q1?", "answer": "A1"}]

        result = await engine._aggregate_results(
            query="test",
            primer=primer,
            follow_ups=follow_ups,
        )

        assert result["confidence"] == 0.85
        assert "Final answer" in result["answer"]
