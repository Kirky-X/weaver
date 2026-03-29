# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for DRIFT Search Engine."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.search.engines.drift_search import (
    DriftConfig,
    DriftHierarchy,
    DriftResult,
    DRIFTSearchEngine,
)


class TestDriftConfig:
    """Tests for DriftConfig dataclass."""

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
            max_follow_ups=3,
            confidence_threshold=0.8,
            max_concurrent=10,
            similarity_threshold=0.6,
        )

        assert config.primer_k == 5
        assert config.max_follow_ups == 3
        assert config.confidence_threshold == 0.8
        assert config.max_concurrent == 10
        assert config.similarity_threshold == 0.6


class TestDriftHierarchy:
    """Tests for DriftHierarchy dataclass."""

    def test_default_values(self):
        """Test default hierarchy values."""
        hierarchy = DriftHierarchy()

        assert hierarchy.primer == {}
        assert hierarchy.follow_ups == []

    def test_custom_values(self):
        """Test custom hierarchy values."""
        hierarchy = DriftHierarchy(
            primer={"answer": "test answer"},
            follow_ups=[{"question": "Q1", "answer": "A1"}],
        )

        assert hierarchy.primer["answer"] == "test answer"
        assert len(hierarchy.follow_ups) == 1


class TestDriftResult:
    """Tests for DriftResult dataclass."""

    def test_default_values(self):
        """Test default result values."""
        result = DriftResult(
            query="test query",
            answer="test answer",
            confidence=0.8,
            hierarchy=DriftHierarchy(),
            primer_communities=3,
            follow_up_iterations=2,
            total_llm_calls=5,
        )

        assert result.query == "test query"
        assert result.answer == "test answer"
        assert result.confidence == 0.8
        assert result.drift_mode == "normal"
        assert result.metadata == {}

    def test_custom_values(self):
        """Test custom result values."""
        result = DriftResult(
            query="test query",
            answer="test answer",
            confidence=0.8,
            hierarchy=DriftHierarchy(),
            primer_communities=3,
            follow_up_iterations=2,
            total_llm_calls=5,
            drift_mode="fallback_local",
            metadata={"key": "value"},
        )

        assert result.drift_mode == "fallback_local"
        assert result.metadata["key"] == "value"


class TestDRIFTSearchEngine:
    """Tests for DRIFTSearchEngine."""

    @pytest.fixture
    def mock_neo4j_pool(self):
        """Create mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value={"content": "Test answer"})
        llm.batch_embed = AsyncMock(return_value=[[0.1] * 1024])
        return llm

    @pytest.fixture
    def mock_context_builder(self):
        """Create mock GlobalContextBuilder."""
        builder = MagicMock()
        builder.build = AsyncMock()
        return builder

    @pytest.fixture
    def mock_local_engine(self):
        """Create mock LocalSearchEngine."""
        from modules.search.engines.local_search import SearchResult

        engine = MagicMock()
        engine.search = AsyncMock(
            return_value=SearchResult(
                query="test question",
                answer="Local answer",
                context_tokens=100,
                confidence=0.75,
            )
        )
        return engine

    @pytest.fixture
    def engine(self, mock_neo4j_pool, mock_llm):
        """Create DRIFTSearchEngine instance."""
        return DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

    @pytest.fixture
    def engine_with_mocks(self, mock_neo4j_pool, mock_llm, mock_local_engine):
        """Create DRIFTSearchEngine with mocked dependencies."""
        return DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            local_engine=mock_local_engine,
        )

    def test_init_default_config(self, mock_neo4j_pool, mock_llm):
        """Test initialization with default config."""
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        assert engine._config.primer_k == 3
        assert engine._config.max_follow_ups == 2

    def test_init_custom_config(self, mock_neo4j_pool, mock_llm):
        """Test initialization with custom config."""
        config = DriftConfig(primer_k=5, max_follow_ups=4)
        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            config=config,
        )

        assert engine._config.primer_k == 5
        assert engine._config.max_follow_ups == 4

    @pytest.mark.asyncio
    async def test_search_full_flow(self, engine_with_mocks, mock_llm):
        """Test full DRIFT search flow."""
        mock_context = MagicMock()
        mock_context.metadata = {"total_communities": 2, "community_ids": ["c1", "c2"]}
        mock_context.to_string = MagicMock(return_value="Context text")

        with patch.object(
            engine_with_mocks._context_builder, "build", AsyncMock(return_value=mock_context)
        ):
            # Mock LLM responses
            mock_llm.call = AsyncMock(
                side_effect=[
                    {"content": "初始答案\n\n1. 后续问题一？\n2. 后续问题二？"},
                    {"content": "综合答案 [置信度: 0.85]"},
                ]
            )

            result = await engine_with_mocks.search("测试查询")

        assert result.query == "测试查询"
        assert result.confidence >= 0
        assert result.total_llm_calls >= 1

    @pytest.mark.asyncio
    async def test_search_fallback_to_local(self, engine_with_mocks, mock_llm):
        """Test search falls back to local when no communities."""
        mock_context = MagicMock()
        mock_context.metadata = {"total_communities": 0}
        mock_context.to_string = MagicMock(return_value="")

        with patch.object(
            engine_with_mocks._context_builder, "build", AsyncMock(return_value=mock_context)
        ):
            result = await engine_with_mocks.search("测试查询")

        assert result.drift_mode == "fallback_local"
        assert result.primer_communities == 0

    @pytest.mark.asyncio
    async def test_primer_phase_no_communities(self, engine):
        """Test primer phase with no communities."""
        mock_context = MagicMock()
        mock_context.metadata = {"total_communities": 0}

        with patch.object(engine._context_builder, "build", AsyncMock(return_value=mock_context)):
            result = await engine._primer_phase("测试查询")

        assert result["fallback"] is True

    @pytest.mark.asyncio
    async def test_primer_phase_with_communities(self, engine, mock_llm):
        """Test primer phase with communities found."""
        mock_context = MagicMock()
        mock_context.metadata = {
            "total_communities": 2,
            "community_ids": ["c1", "c2"],
        }
        mock_context.to_string = MagicMock(return_value="Community reports")

        mock_llm.call = AsyncMock(
            return_value={"content": "初步答案\n\n1. 后续问题一？\n2. 后续问题二？"}
        )

        with patch.object(engine._context_builder, "build", AsyncMock(return_value=mock_context)):
            result = await engine._primer_phase("测试查询")

        assert result["fallback"] is False
        assert result["community_count"] == 2
        assert len(result["follow_up_questions"]) > 0

    @pytest.mark.asyncio
    async def test_follow_up_phase_empty_questions(self, engine_with_mocks):
        """Test follow-up phase with empty questions."""
        result = await engine_with_mocks._follow_up_phase(
            query="测试查询",
            initial_answer="初始答案",
            follow_up_questions=[],
        )

        assert result["results"] == []
        assert result["llm_calls"] == 0

    @pytest.mark.asyncio
    async def test_follow_up_phase_with_questions(self, engine_with_mocks, mock_local_engine):
        """Test follow-up phase processes questions."""
        # Use config with high confidence threshold to avoid early termination
        engine_with_mocks._config.confidence_threshold = 0.99
        result = await engine_with_mocks._follow_up_phase(
            query="测试查询",
            initial_answer="初始答案",
            follow_up_questions=["问题一？", "问题二？"],
        )

        assert len(result["results"]) == 2
        assert result["llm_calls"] == 2

    @pytest.mark.asyncio
    async def test_follow_up_phase_early_termination(self, mock_neo4j_pool, mock_llm):
        """Test follow-up phase terminates early on high confidence."""
        from modules.search.engines.local_search import SearchResult

        config = DriftConfig(confidence_threshold=0.7)
        mock_local = MagicMock()
        mock_local.search = AsyncMock(
            return_value=SearchResult(
                query="问题",
                answer="高置信度答案",
                context_tokens=100,
                confidence=0.85,  # Above threshold
            )
        )

        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            config=config,
            local_engine=mock_local,
        )

        result = await engine._follow_up_phase(
            query="测试查询",
            initial_answer="初始答案",
            follow_up_questions=["问题一？", "问题二？"],
        )

        # Should stop after first high-confidence result
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_aggregate_results(self, engine, mock_llm):
        """Test result aggregation."""
        mock_llm.call = AsyncMock(return_value={"content": "综合答案 [置信度: 0.8]"})

        result = await engine._aggregate_results(
            query="测试查询",
            primer={"answer": "初始答案"},
            follow_ups=[
                {"question": "问题一？", "answer": "答案一"},
                {"question": "问题二？", "answer": "答案二"},
            ],
        )

        assert "answer" in result
        assert "confidence" in result

    def test_extract_follow_up_questions(self, engine):
        """Test extraction of follow-up questions from text."""
        text = """
        这是初步答案。

        后续问题：
        1. 第一个问题是什么？
        2. 第二个问题是什么？
        3. 第三个问题是什么？
        """

        questions = engine._extract_follow_up_questions(text)

        assert len(questions) == 3
        assert "第一个问题是什么" in questions[0]

    def test_extract_follow_up_questions_with_markers(self, engine):
        """Test extraction with different markers."""
        text = """
        答案内容。

        - 问题一？
        * 问题二？
        3. 问题三？
        """

        questions = engine._extract_follow_up_questions(text)

        assert len(questions) >= 1

    def test_extract_follow_up_questions_max_three(self, engine):
        """Test extraction returns max 3 questions."""
        text = """
        1. 问题一？
        2. 问题二？
        3. 问题三？
        4. 问题四？
        5. 问题五？
        """

        questions = engine._extract_follow_up_questions(text)

        assert len(questions) == 3

    def test_extract_answer(self, engine):
        """Test answer extraction from text."""
        text = "这是答案内容。\n\n后续问题：\n1. 问题一？"

        answer = engine._extract_answer(text)

        assert "这是答案内容" in answer
        assert "后续问题" not in answer

    def test_extract_answer_no_marker(self, engine):
        """Test answer extraction when no marker found."""
        text = "这是完整答案内容。"

        answer = engine._extract_answer(text)

        assert answer == "这是完整答案内容。"

    def test_extract_confidence_with_chinese_marker(self, engine):
        """Test confidence extraction with Chinese marker."""
        text = "答案内容 [置信度: 0.85]"

        confidence = engine._extract_confidence(text)

        assert confidence == 0.85

    def test_extract_confidence_with_english_marker(self, engine):
        """Test confidence extraction with English marker."""
        text = "Answer content [confidence: 0.75]"

        confidence = engine._extract_confidence(text)

        assert confidence == 0.75

    def test_extract_confidence_without_marker(self, engine):
        """Test confidence extraction without marker returns default."""
        text = "答案内容"

        confidence = engine._extract_confidence(text)

        assert confidence == 0.5  # Default confidence

    def test_extract_confidence_invalid_value(self, engine):
        """Test confidence extraction with invalid value."""
        text = "答案内容 [置信度: invalid]"

        confidence = engine._extract_confidence(text)

        assert confidence == 0.5  # Default on parsing error

    def test_remove_confidence_marker_chinese(self, engine):
        """Test removal of Chinese confidence marker."""
        text = "答案内容 [置信度: 0.85]"

        result = engine._remove_confidence_marker(text)

        assert "[置信度" not in result
        assert "答案内容" in result

    def test_remove_confidence_marker_english(self, engine):
        """Test removal of English confidence marker."""
        text = "Answer content [confidence: 0.75]"

        result = engine._remove_confidence_marker(text)

        assert "[confidence" not in result.lower()

    def test_remove_confidence_marker_multiple(self, engine):
        """Test removal of multiple confidence markers."""
        text = "答案 [置信度: 0.8] 更多内容 [confidence: 0.9]"

        result = engine._remove_confidence_marker(text)

        assert "[置信度" not in result
        assert "[confidence" not in result.lower()

    @pytest.mark.asyncio
    async def test_search_with_custom_config(self, mock_neo4j_pool, mock_llm):
        """Test search with custom configuration."""
        config = DriftConfig(
            primer_k=5,
            max_follow_ups=1,
            confidence_threshold=0.9,
        )

        engine = DRIFTSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            config=config,
        )

        mock_context = MagicMock()
        mock_context.metadata = {"total_communities": 0}

        with patch.object(engine._context_builder, "build", AsyncMock(return_value=mock_context)):
            result = await engine.search("测试查询")

        assert result is not None

    @pytest.mark.asyncio
    async def test_follow_up_phase_skips_empty_questions(
        self, engine_with_mocks, mock_local_engine
    ):
        """Test follow-up phase skips empty questions."""
        # Use config with high confidence threshold and max_follow_ups to avoid early termination
        engine_with_mocks._config.confidence_threshold = 0.99
        engine_with_mocks._config.max_follow_ups = 5  # Allow processing all questions
        # Set up mock to return lower confidence to avoid early termination
        mock_local_engine.search = AsyncMock(
            return_value=MagicMock(
                answer="Answer",
                confidence=0.5,
                source_entities=[],
            )
        )
        result = await engine_with_mocks._follow_up_phase(
            query="测试查询",
            initial_answer="初始答案",
            follow_up_questions=["", "   ", "有效问题？"],
        )

        # Only one valid question should be processed (empty strings skipped)
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_primer_phase_llm_error(self, engine, mock_llm):
        """Test primer phase handles LLM error."""
        mock_context = MagicMock()
        mock_context.metadata = {"total_communities": 2}
        mock_context.to_string = MagicMock(return_value="Context")

        mock_llm.call = AsyncMock(side_effect=Exception("LLM error"))

        with patch.object(engine._context_builder, "build", AsyncMock(return_value=mock_context)):
            with pytest.raises(Exception, match="LLM 错误"):
                await engine._primer_phase("测试查询")
