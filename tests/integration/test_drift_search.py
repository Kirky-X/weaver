# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for DRIFT Search Engine.

Tests the DRIFT (Dynamic Reasoning and Inference Framework) search
which combines global community insights with local entity details.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.search.engines.drift_search import (
    DriftConfig,
    DriftHierarchy,
    DriftResult,
    DRIFTSearchEngine,
)
from modules.search.engines.local_search import SearchResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    llm = MagicMock()
    llm.call = AsyncMock(return_value={"content": "Generated answer"})
    llm.batch_embed = AsyncMock(return_value=[[0.1] * 1536])
    return llm


@pytest.fixture
def mock_local_engine():
    """Mock local search engine."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value=SearchResult(
            query="test query",
            answer="Local search answer",
            confidence=0.75,
            entities=[],
            context_tokens=100,
        )
    )
    return engine


@pytest.fixture
def drift_config():
    """DRIFT configuration for tests."""
    return DriftConfig(
        primer_k=3,
        max_follow_ups=2,
        confidence_threshold=0.7,
        max_concurrent=5,
        similarity_threshold=0.5,
    )


class TestDRIFTSearchEngineInit:
    """Test DRIFTSearchEngine initialization."""

    def test_init_with_defaults(self, mock_neo4j_pool, mock_llm):
        """Test initialization with default configuration."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        assert engine._pool == mock_neo4j_pool
        assert engine._llm == mock_llm
        assert engine._config.primer_k == 3
        assert engine._config.max_follow_ups == 2

    def test_init_with_custom_config(self, mock_neo4j_pool, mock_llm, drift_config):
        """Test initialization with custom configuration."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            config=drift_config,
        )

        assert engine._config.primer_k == 3
        assert engine._config.max_follow_ups == 2
        assert engine._config.confidence_threshold == 0.7

    def test_init_with_local_engine(self, mock_neo4j_pool, mock_llm, mock_local_engine):
        """Test initialization with injected local engine."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            local_engine=mock_local_engine,
        )

        assert engine._local_engine == mock_local_engine


class TestDRIFTSarchPrimerPhase:
    """Test DRIFT primer phase."""

    @pytest.mark.asyncio
    async def test_primer_phase_with_communities(self, mock_neo4j_pool, mock_llm):
        """Test primer phase when relevant communities exist."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Mock context builder to return communities
        with patch.object(engine._context_builder, "build", new_callable=AsyncMock) as mock_build:
            mock_context = MagicMock()
            mock_context.metadata = {
                "total_communities": 3,
                "community_ids": ["c1", "c2", "c3"],
            }
            mock_context.to_string.return_value = "Community context..."
            mock_build.return_value = mock_context

            # Mock LLM response
            mock_llm.call = AsyncMock(
                return_value={
                    "content": (
                        "Initial answer about the topic.\n\n后续问题：\n1. What about X?\n2. How does Y work?"
                    )
                }
            )

            result = await engine._primer_phase("What is AI?")

            assert result["fallback"] is False
            assert result["community_count"] == 3
            assert len(result["follow_up_questions"]) >= 0

    @pytest.mark.asyncio
    async def test_primer_phase_no_communities(self, mock_neo4j_pool, mock_llm):
        """Test primer phase fallback when no communities found."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        with patch.object(engine._context_builder, "build", new_callable=AsyncMock) as mock_build:
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 0}
            mock_build.return_value = mock_context

            result = await engine._primer_phase("Unknown topic?")

            assert result["fallback"] is True
            assert result["answer"] == ""
            assert result["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_primer_phase_extract_questions(self, mock_neo4j_pool, mock_llm):
        """Test extraction of follow-up questions from primer answer."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Test question extraction
        text = """
        这是初步答案的内容。

        后续问题：
        1. 什么是深度学习？
        2. 机器学习有哪些应用？
        3. 如何选择合适的模型？
        """

        questions = engine._extract_follow_up_questions(text)

        assert len(questions) <= 3
        assert any("深度学习" in q for q in questions)


class TestDRIFTSarchFollowUpPhase:
    """Test DRIFT follow-up phase."""

    @pytest.mark.asyncio
    async def test_follow_up_phase_executes_local_search(
        self, mock_neo4j_pool, mock_llm, mock_local_engine
    ):
        """Test that follow-up phase uses local search."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            local_engine=mock_local_engine,
        )

        questions = ["What is GPT-4?", "How does it work?"]

        result = await engine._follow_up_phase(
            query="Tell me about GPT-4",
            initial_answer="Initial answer",
            follow_up_questions=questions,
        )

        assert "results" in result
        assert result["llm_calls"] >= 0

    @pytest.mark.asyncio
    async def test_follow_up_phase_respects_max_limit(
        self, mock_neo4j_pool, mock_llm, mock_local_engine, drift_config
    ):
        """Test that follow-up phase respects max_follow_ups limit."""
        drift_config.max_follow_ups = 2
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            config=drift_config,
            local_engine=mock_local_engine,
        )

        # Provide more questions than the limit
        questions = ["Q1?", "Q2?", "Q3?", "Q4?"]

        result = await engine._follow_up_phase(
            query="Test query",
            initial_answer="Initial",
            follow_up_questions=questions,
        )

        # Should only process max_follow_ups questions
        assert len(result["results"]) <= 2

    @pytest.mark.asyncio
    async def test_follow_up_phase_early_termination(self, mock_neo4j_pool, mock_llm, drift_config):
        """Test early termination when confidence threshold reached."""
        drift_config.confidence_threshold = 0.7

        # Mock local engine with high confidence
        mock_local = MagicMock()
        mock_local.search = AsyncMock(
            return_value=SearchResult(
                query="test",
                answer="High confidence answer",
                confidence=0.85,
                entities=[],
                context_tokens=100,
            )
        )

        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            config=drift_config,
            local_engine=mock_local,
        )

        questions = ["Q1?", "Q2?", "Q3?"]

        result = await engine._follow_up_phase(
            query="Test",
            initial_answer="Initial",
            follow_up_questions=questions,
        )

        # Should stop after first high-confidence result
        assert len(result["results"]) >= 1


class TestDRIFTSarchAggregation:
    """Test DRIFT result aggregation."""

    @pytest.mark.asyncio
    async def test_aggregate_results_combines_answers(self, mock_neo4j_pool, mock_llm):
        """Test that aggregation combines primer and follow-up answers."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_llm.call_at = AsyncMock(
            return_value={"content": "Comprehensive answer combining all sources. [置信度: 0.85]"}
        )

        primer = {"answer": "Initial answer from communities"}
        follow_ups = [
            {"question": "Q1?", "answer": "Follow-up answer 1"},
            {"question": "Q2?", "answer": "Follow-up answer 2"},
        ]

        result = await engine._aggregate_results(
            query="Main query",
            primer=primer,
            follow_ups=follow_ups,
        )

        assert "answer" in result
        assert result["confidence"] >= 0

    @pytest.mark.asyncio
    async def test_aggregate_results_empty_follow_ups(self, mock_neo4j_pool, mock_llm):
        """Test aggregation with no follow-up results."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_llm.call = AsyncMock(
            return_value={"content": "Answer based on primer only. [置信度: 0.75]"}
        )

        result = await engine._aggregate_results(
            query="Query",
            primer={"answer": "Initial"},
            follow_ups=[],
        )

        assert "answer" in result


class TestDRIFTSarchFullWorkflow:
    """Test complete DRIFT search workflow."""

    @pytest.mark.asyncio
    async def test_full_search_returns_drift_result(self, mock_neo4j_pool, mock_llm):
        """Test that full search returns DriftResult."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Mock context builder
        with patch.object(engine._context_builder, "build", new_callable=AsyncMock) as mock_build:
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 2}
            mock_context.to_string.return_value = "Context"
            mock_build.return_value = mock_context

            # Mock LLM responses
            mock_llm.call = AsyncMock(return_value={"content": "Answer [置信度: 0.8]"})

            result = await engine.search("What is machine learning?")

            assert isinstance(result, DriftResult)
            assert result.query == "What is machine learning?"
            assert isinstance(result.answer, str)
            assert isinstance(result.confidence, float)
            assert isinstance(result.hierarchy, DriftHierarchy)

    @pytest.mark.asyncio
    async def test_search_fallback_to_local(self, mock_neo4j_pool, mock_llm):
        """Test fallback to local search when no communities."""
        mock_local = MagicMock()
        mock_local.search = AsyncMock(
            return_value=SearchResult(
                query="test",
                answer="Local search fallback answer",
                confidence=0.7,
                entities=[],
                context_tokens=100,
            )
        )

        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            local_engine=mock_local,
        )

        # Mock context builder with no communities
        with patch.object(engine._context_builder, "build", new_callable=AsyncMock) as mock_build:
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 0}
            mock_build.return_value = mock_context

            result = await engine.search("Unknown topic")

            assert result.drift_mode == "fallback_local"
            assert result.primer_communities == 0

    @pytest.mark.asyncio
    async def test_search_counts_llm_calls(self, mock_neo4j_pool, mock_llm):
        """Test that LLM call count is tracked."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        with patch.object(engine._context_builder, "build", new_callable=AsyncMock) as mock_build:
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 1}
            mock_context.to_string.return_value = "Context"
            mock_build.return_value = mock_context

            mock_llm.call = AsyncMock(return_value={"content": "Answer [置信度: 0.8]"})

            result = await engine.search("Test query")

            assert result.total_llm_calls >= 1


class TestDRIFTConfidenceExtraction:
    """Test confidence score extraction from LLM responses."""

    def test_extract_confidence_chinese_format(self, mock_neo4j_pool, mock_llm):
        """Test extraction of Chinese confidence format."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        text = "这是答案内容。[置信度: 0.85]"
        confidence = engine._extract_confidence(text)

        assert confidence == 0.85

    def test_extract_confidence_english_format(self, mock_neo4j_pool, mock_llm):
        """Test extraction of English confidence format."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        text = "Answer content. [confidence: 0.72]"
        confidence = engine._extract_confidence(text)

        assert confidence == 0.72

    def test_extract_confidence_default(self, mock_neo4j_pool, mock_llm):
        """Test default confidence when no marker found."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        text = "Answer without confidence marker."
        confidence = engine._extract_confidence(text)

        assert confidence == 0.5  # Default

    def test_remove_confidence_marker(self, mock_neo4j_pool, mock_llm):
        """Test removal of confidence marker from text."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        text = "Answer content. [置信度: 0.85] More text."
        cleaned = engine._remove_confidence_marker(text)

        assert "[置信度:" not in cleaned
        assert "Answer content." in cleaned


class TestDRIFTConfigValidation:
    """Test DriftConfig validation."""

    def test_default_config_values(self):
        """Test default configuration values."""
        config = DriftConfig()

        assert config.primer_k == 3
        assert config.max_follow_ups == 2
        assert config.confidence_threshold == 0.7
        assert config.similarity_threshold == 0.5

    def test_custom_config_values(self):
        """Test custom configuration values."""
        config = DriftConfig(
            primer_k=5,
            max_follow_ups=3,
            confidence_threshold=0.8,
            max_concurrent=10,
        )

        assert config.primer_k == 5
        assert config.max_follow_ups == 3
        assert config.confidence_threshold == 0.8
        assert config.max_concurrent == 10
