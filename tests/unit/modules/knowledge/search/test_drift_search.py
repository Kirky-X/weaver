# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for DRIFTSearchEngine."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.engines.drift_search import (
    DriftConfig,
    DriftHierarchy,
    DriftResult,
    DRIFTSearchEngine,
)


class TestDriftHierarchy:
    """Tests for DriftHierarchy dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        hierarchy = DriftHierarchy()
        assert hierarchy.primer == {}
        assert hierarchy.follow_ups == []

    def test_custom_values(self):
        """Test custom initialization."""
        hierarchy = DriftHierarchy(
            primer={"answer": "test"},
            follow_ups=[{"question": "q1"}],
        )
        assert hierarchy.primer == {"answer": "test"}
        assert len(hierarchy.follow_ups) == 1


class TestDriftResult:
    """Tests for DriftResult dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        result = DriftResult(
            query="test query",
            answer="test answer",
            confidence=0.8,
            hierarchy=DriftHierarchy(),
            primer_communities=2,
            follow_up_iterations=1,
            total_llm_calls=3,
        )
        assert result.query == "test query"
        assert result.answer == "test answer"
        assert result.confidence == 0.8
        assert result.drift_mode == "normal"
        assert result.metadata == {}

    def test_custom_metadata(self):
        """Test custom metadata."""
        result = DriftResult(
            query="test",
            answer="answer",
            confidence=0.5,
            hierarchy=DriftHierarchy(),
            primer_communities=0,
            follow_up_iterations=0,
            total_llm_calls=1,
            drift_mode="fallback_local",
            metadata={"key": "value"},
        )
        assert result.drift_mode == "fallback_local"
        assert result.metadata["key"] == "value"


class TestDriftConfig:
    """Tests for DriftConfig dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        config = DriftConfig()
        assert config.primer_k == 3
        assert config.max_follow_ups == 2
        assert config.confidence_threshold == 0.7
        assert config.max_concurrent == 5
        assert config.similarity_threshold == 0.5

    def test_custom_values(self):
        """Test custom initialization."""
        config = DriftConfig(
            primer_k=5,
            max_follow_ups=3,
            confidence_threshold=0.8,
        )
        assert config.primer_k == 5
        assert config.max_follow_ups == 3
        assert config.confidence_threshold == 0.8


class TestDRIFTSearchEngineInit:
    """Tests for DRIFTSearchEngine initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default config."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        with (
            patch(
                "modules.knowledge.search.engines.drift_search.GlobalContextBuilder"
            ) as mock_builder,
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine") as mock_local,
        ):
            engine = DRIFTSearchEngine(
                neo4j_pool=mock_pool,
                llm=mock_llm,
            )
            assert engine._pool is mock_pool
            assert engine._llm is mock_llm
            assert engine._config.primer_k == 3

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        config = DriftConfig(primer_k=10, max_follow_ups=5)

        with (
            patch("modules.knowledge.search.engines.drift_search.GlobalContextBuilder"),
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine"),
        ):
            engine = DRIFTSearchEngine(
                neo4j_pool=mock_pool,
                llm=mock_llm,
                config=config,
            )
            assert engine._config.primer_k == 10
            assert engine._config.max_follow_ups == 5


class TestDRIFTSearchEngineExtractMethods:
    """Tests for extraction helper methods."""

    def setup_engine(self):
        """Create engine for testing."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        with (
            patch("modules.knowledge.search.engines.drift_search.GlobalContextBuilder"),
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine"),
        ):
            return DRIFTSearchEngine(mock_pool, mock_llm)

    def test_extract_follow_up_questions_with_numbers(self):
        """Test extracting numbered questions."""
        engine = self.setup_engine()
        text = """这是答案。
1. 第一个问题？
2. 第二个问题？
3. 第三个问题？"""
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) == 3
        assert "第一个问题" in questions[0]

    def test_extract_follow_up_questions_with_bullets(self):
        """Test extracting bullet-point questions."""
        engine = self.setup_engine()
        text = """答案内容。
- 问题一？
* 问题二？"""
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) == 2

    def test_extract_follow_up_questions_max_three(self):
        """Test that only 3 questions are returned."""
        engine = self.setup_engine()
        text = """
1. 问题1？
2. 问题2？
3. 问题3？
4. 问题4？
5. 问题5？"""
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) == 3

    def test_extract_follow_up_questions_empty(self):
        """Test extracting from text without questions."""
        engine = self.setup_engine()
        text = "这只是普通文本，没有问题。"
        questions = engine._extract_follow_up_questions(text)
        assert len(questions) == 0

    def test_extract_answer_with_marker(self):
        """Test extracting answer with follow-up marker."""
        engine = self.setup_engine()
        text = "这是答案内容。\n\n后续问题：\n1. 问题？"
        answer = engine._extract_answer(text)
        assert "这是答案内容" in answer
        assert "后续问题" not in answer

    def test_extract_answer_without_marker(self):
        """Test extracting answer without marker."""
        engine = self.setup_engine()
        text = "这是完整的答案内容。"
        answer = engine._extract_answer(text)
        assert answer == "这是完整的答案内容。"

    def test_extract_confidence_with_chinese_marker(self):
        """Test extracting confidence with Chinese marker."""
        engine = self.setup_engine()
        text = "答案内容 [置信度: 0.85]"
        confidence = engine._extract_confidence(text)
        assert confidence == 0.85

    def test_extract_confidence_with_english_marker(self):
        """Test extracting confidence with English marker."""
        engine = self.setup_engine()
        text = "Answer content [confidence: 0.75]"
        confidence = engine._extract_confidence(text)
        assert confidence == 0.75

    def test_extract_confidence_without_marker(self):
        """Test default confidence when no marker."""
        engine = self.setup_engine()
        text = "答案内容，没有置信度标记"
        confidence = engine._extract_confidence(text)
        assert confidence == 0.5

    def test_extract_confidence_invalid_value(self):
        """Test confidence extraction with invalid value."""
        engine = self.setup_engine()
        text = "答案 [置信度: abc]"
        confidence = engine._extract_confidence(text)
        assert confidence == 0.5

    def test_remove_confidence_marker_chinese(self):
        """Test removing Chinese confidence marker."""
        engine = self.setup_engine()
        text = "答案内容 [置信度: 0.85] 结尾"
        result = engine._remove_confidence_marker(text)
        assert "[置信度" not in result
        assert "答案内容" in result
        assert "结尾" in result

    def test_remove_confidence_marker_english(self):
        """Test removing English confidence marker."""
        engine = self.setup_engine()
        text = "Answer [confidence: 0.9] end"
        result = engine._remove_confidence_marker(text)
        assert "[confidence" not in result


class TestDRIFTSearchEnginePrimerPhase:
    """Tests for _primer_phase method."""

    @pytest.mark.asyncio
    async def test_primer_phase_no_communities(self):
        """Test primer phase when no communities found."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        with (
            patch(
                "modules.knowledge.search.engines.drift_search.GlobalContextBuilder"
            ) as mock_builder,
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine"),
        ):
            mock_context_builder = MagicMock()
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 0}
            mock_context_builder.build = AsyncMock(return_value=mock_context)
            mock_builder.return_value = mock_context_builder

            engine = DRIFTSearchEngine(mock_pool, mock_llm)
            result = await engine._primer_phase("test query")

            assert result["fallback"] is True
            assert result.get("community_count", 0) == 0

    @pytest.mark.asyncio
    async def test_primer_phase_with_communities(self):
        """Test primer phase with communities found."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        mock_llm.call_at = AsyncMock(return_value="答案内容\n\n1. 后续问题？")

        with (
            patch(
                "modules.knowledge.search.engines.drift_search.GlobalContextBuilder"
            ) as mock_builder,
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine"),
        ):
            mock_context_builder = MagicMock()
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 3, "community_ids": ["c1", "c2", "c3"]}
            mock_context.to_string.return_value = "context text"
            mock_context_builder.build = AsyncMock(return_value=mock_context)
            mock_builder.return_value = mock_context_builder

            engine = DRIFTSearchEngine(mock_pool, mock_llm)
            result = await engine._primer_phase("test query")

            assert result["fallback"] is False
            assert result["community_count"] == 3
            assert result["llm_calls"] == 1


class TestDRIFTSearchEngineFollowUpPhase:
    """Tests for _follow_up_phase method."""

    @pytest.mark.asyncio
    async def test_follow_up_phase_empty_questions(self):
        """Test follow-up phase with no questions."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        with (
            patch("modules.knowledge.search.engines.drift_search.GlobalContextBuilder"),
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine") as mock_local,
        ):
            mock_local_engine = MagicMock()
            mock_local.return_value = mock_local_engine

            engine = DRIFTSearchEngine(mock_pool, mock_llm)
            result = await engine._follow_up_phase(
                query="test",
                initial_answer="initial",
                follow_up_questions=[],
            )

            assert result["results"] == []
            assert result["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_follow_up_phase_with_questions(self):
        """Test follow-up phase with questions."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        # Create a proper mock result with answer and confidence attributes
        mock_local_result = MagicMock()
        mock_local_result.answer = "local answer"
        mock_local_result.confidence = 0.6
        mock_local_result.source_entities = []

        with (
            patch("modules.knowledge.search.engines.drift_search.GlobalContextBuilder"),
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine") as mock_local,
        ):
            mock_local_engine = MagicMock()
            mock_local_engine.search = AsyncMock(return_value=mock_local_result)
            mock_local.return_value = mock_local_engine

            engine = DRIFTSearchEngine(mock_pool, mock_llm)
            result = await engine._follow_up_phase(
                query="test",
                initial_answer="initial",
                follow_up_questions=["问题1？", "问题2？"],
            )

            assert len(result["results"]) == 2
            assert result["llm_calls"] == 2

    @pytest.mark.asyncio
    async def test_follow_up_phase_early_termination(self):
        """Test follow-up phase early termination on high confidence."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        # Create a result with high confidence
        mock_high_conf_result = MagicMock()
        mock_high_conf_result.answer = "confident answer"
        mock_high_conf_result.confidence = 0.9
        mock_high_conf_result.source_entities = []

        mock_low_conf_result = MagicMock()
        mock_low_conf_result.answer = "low confidence answer"
        mock_low_conf_result.confidence = 0.5
        mock_low_conf_result.source_entities = []

        with (
            patch("modules.knowledge.search.engines.drift_search.GlobalContextBuilder"),
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine") as mock_local,
        ):
            mock_local_engine = MagicMock()
            mock_local_engine.search = AsyncMock(return_value=mock_high_conf_result)
            mock_local.return_value = mock_local_engine

            config = DriftConfig(confidence_threshold=0.8, max_follow_ups=3)
            engine = DRIFTSearchEngine(mock_pool, mock_llm, config=config)

            result = await engine._follow_up_phase(
                query="test",
                initial_answer="initial",
                follow_up_questions=["问题1？", "问题2？", "问题3？"],
            )

            # Should stop after first high-confidence result
            assert len(result["results"]) == 1


class TestDRIFTSearchEngineAggregateResults:
    """Tests for _aggregate_results method."""

    @pytest.mark.asyncio
    async def test_aggregate_results(self):
        """Test result aggregation."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        mock_llm.call_at = AsyncMock(return_value="最终答案 [置信度: 0.8]")

        with (
            patch("modules.knowledge.search.engines.drift_search.GlobalContextBuilder"),
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine"),
        ):
            engine = DRIFTSearchEngine(mock_pool, mock_llm)

            result = await engine._aggregate_results(
                query="test query",
                primer={"answer": "初始答案"},
                follow_ups=[
                    {"question": "问题1？", "answer": "答案1"},
                ],
            )

            assert "answer" in result
            assert result["confidence"] == 0.8


class TestDRIFTSearchEngineSearch:
    """Tests for the main search method."""

    @pytest.mark.asyncio
    async def test_search_fallback_to_local(self):
        """Test search fallback to local when no communities."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()

        # Create mock for local search result
        mock_local_result = MagicMock()
        mock_local_result.answer = "local answer"
        mock_local_result.confidence = 0.7

        with (
            patch(
                "modules.knowledge.search.engines.drift_search.GlobalContextBuilder"
            ) as mock_builder,
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine") as mock_local,
        ):
            # Setup context builder to return no communities
            mock_context_builder = MagicMock()
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 0}
            mock_context_builder.build = AsyncMock(return_value=mock_context)
            mock_builder.return_value = mock_context_builder

            # Setup local engine
            mock_local_engine = MagicMock()
            mock_local_engine.search = AsyncMock(return_value=mock_local_result)
            mock_local.return_value = mock_local_engine

            engine = DRIFTSearchEngine(mock_pool, mock_llm)
            result = await engine.search("test query")

            assert result.drift_mode == "fallback_local"
            assert result.answer == "local answer"

    @pytest.mark.asyncio
    async def test_search_full_drift(self):
        """Test full DRIFT search flow."""
        mock_pool = MagicMock()
        mock_llm = MagicMock()
        mock_llm.call_at = AsyncMock(
            side_effect=[
                "初始答案\n\n1. 后续问题？",
                "最终答案 [置信度: 0.85]",
            ]
        )

        # Create mock for local search result
        mock_local_result = MagicMock()
        mock_local_result.answer = "local follow-up answer"
        mock_local_result.confidence = 0.6
        mock_local_result.source_entities = []

        with (
            patch(
                "modules.knowledge.search.engines.drift_search.GlobalContextBuilder"
            ) as mock_builder,
            patch("modules.knowledge.search.engines.drift_search.LocalSearchEngine") as mock_local,
        ):
            # Setup context builder
            mock_context_builder = MagicMock()
            mock_context = MagicMock()
            mock_context.metadata = {"total_communities": 2, "community_ids": ["c1", "c2"]}
            mock_context.to_string.return_value = "context"
            mock_context_builder.build = AsyncMock(return_value=mock_context)
            mock_builder.return_value = mock_context_builder

            # Setup local engine
            mock_local_engine = MagicMock()
            mock_local_engine.search = AsyncMock(return_value=mock_local_result)
            mock_local.return_value = mock_local_engine

            engine = DRIFTSearchEngine(mock_pool, mock_llm)
            result = await engine.search("test query")

            assert result.drift_mode == "normal"
            assert result.primer_communities == 2
            assert result.confidence == 0.85
