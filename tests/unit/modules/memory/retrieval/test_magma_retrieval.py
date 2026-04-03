# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for MAGMA memory retrieval components."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.memory.core.graph_types import AggregationType, OutputMode


class TestEntityAggregator:
    """Tests for EntityAggregator."""

    @pytest.fixture
    def mock_entity_repo(self):
        """Create mock entity repository."""
        repo = MagicMock()
        repo.get_entity_neighborhood = AsyncMock(
            return_value={
                "center": "腾讯",
                "hops": 2,
                "events": [
                    {"content": "腾讯发布新AI产品", "timestamp": "2026-01-15"},
                    {"content": "腾讯股价上涨", "timestamp": "2026-01-20"},
                ],
                "related_entities": [
                    {"canonical_name": "AI", "type": "TECH"},
                    {"canonical_name": "马化腾", "type": "PERSON"},
                ],
                "relations": [
                    {"source": "腾讯", "target": "AI", "type": "develops"},
                ],
            }
        )
        return repo

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client."""
        llm = MagicMock()
        llm.call_at = AsyncMock(
            return_value={
                "facts": ["腾讯是中国互联网巨头", "腾讯在AI领域有重要布局"],
                "entity_type": "ORG",
                "reasoning": "Based on events and relations",
                "confidence": 0.85,
            }
        )
        return llm

    @pytest.mark.asyncio
    async def test_aggregate_facts(self, mock_entity_repo, mock_llm):
        """Test FACTS aggregation extracts key facts."""
        from modules.memory.retrieval.entity_aggregator import EntityAggregator

        aggregator = EntityAggregator(
            entity_repo=mock_entity_repo,
            llm=mock_llm,
        )

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.FACTS,
        )

        assert result.entity_name == "腾讯"
        assert result.entity_type == "ORG"
        assert result.aggregation_type == AggregationType.FACTS
        assert len(result.facts) > 0
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_aggregate_count(self, mock_entity_repo, mock_llm):
        """Test COUNT aggregation returns event counts."""
        from modules.memory.retrieval.entity_aggregator import EntityAggregator

        aggregator = EntityAggregator(
            entity_repo=mock_entity_repo,
            llm=mock_llm,
        )

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        assert result.entity_name == "腾讯"
        assert result.aggregation_type == AggregationType.COUNT
        assert result.count == 2  # Two events in mock
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_aggregate_timeline(self, mock_entity_repo, mock_llm):
        """Test TIMELINE aggregation returns chronological events."""
        from modules.memory.retrieval.entity_aggregator import EntityAggregator

        aggregator = EntityAggregator(
            entity_repo=mock_entity_repo,
            llm=mock_llm,
        )

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        assert result.entity_name == "腾讯"
        assert result.aggregation_type == AggregationType.TIMELINE
        assert len(result.facts) > 0
        # Timeline facts should contain timestamps
        assert any("[" in fact for fact in result.facts)

    @pytest.mark.asyncio
    async def test_aggregate_entity_not_found(self, mock_entity_repo, mock_llm):
        """Test aggregation when entity not found."""
        from modules.memory.retrieval.entity_aggregator import EntityAggregator

        mock_entity_repo.get_entity_neighborhood = AsyncMock(return_value=None)

        aggregator = EntityAggregator(
            entity_repo=mock_entity_repo,
            llm=mock_llm,
        )

        result = await aggregator.aggregate(
            entity_name="不存在实体",
            aggregation_type=AggregationType.FACTS,
        )

        assert result.entity_name == "不存在实体"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_aggregate_handles_llm_error(self, mock_entity_repo, mock_llm):
        """Test aggregation handles LLM errors gracefully."""
        from modules.memory.retrieval.entity_aggregator import EntityAggregator

        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM error"))

        aggregator = EntityAggregator(
            entity_repo=mock_entity_repo,
            llm=mock_llm,
        )

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.FACTS,
        )

        # Should return fallback result
        assert result.entity_name == "腾讯"
        assert result.confidence == 0.0


class TestNarrativeSynthesizer:
    """Tests for NarrativeSynthesizer."""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client."""
        llm = MagicMock()
        llm.call_at = AsyncMock(
            return_value={
                "answer": "腾讯作为中国领先的互联网公司，在AI领域持续创新...",
                "tokens_used": 150,
            }
        )
        return llm

    @pytest.fixture
    def mock_context_nodes(self):
        """Create mock context nodes."""
        return [
            {
                "id": "node-1",
                "content": "腾讯是中国领先的互联网公司",
                "score": 0.9,
                "source": "news",
            },
            {"id": "node-2", "content": "腾讯在AI领域有重要布局", "score": 0.85, "source": "tech"},
        ]

    @pytest.mark.asyncio
    async def test_synthesize_context_mode(self, mock_llm, mock_context_nodes):
        """Test CONTEXT mode returns structured context."""
        from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer

        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="腾讯是什么公司？",
            context_nodes=mock_context_nodes,
            mode=OutputMode.CONTEXT,
        )

        assert result.mode == OutputMode.CONTEXT
        assert result.node_count > 0
        assert result.output != ""

    @pytest.mark.asyncio
    async def test_synthesize_narrative_mode(self, mock_llm, mock_context_nodes):
        """Test NARRATIVE mode generates LLM synthesis."""
        from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer

        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="腾讯是什么公司？",
            context_nodes=mock_context_nodes,
            mode=OutputMode.NARRATIVE,
        )

        assert result.mode == OutputMode.NARRATIVE
        assert result.output != ""
        mock_llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_synthesize_handles_empty_result(self, mock_llm):
        """Test synthesis handles empty context nodes."""
        from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer

        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="查询无结果",
            context_nodes=[],
            mode=OutputMode.CONTEXT,
        )

        assert result.mode == OutputMode.CONTEXT
        assert result.node_count == 0
        assert "No relevant" in result.output


class TestSearchResponseBuilder:
    """Tests for SearchResponseBuilder."""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client."""
        llm = MagicMock()
        llm.call_at = AsyncMock(
            return_value={
                "answer": "综合回答...",
                "tokens_used": 100,
            }
        )
        return llm

    @pytest.fixture
    def mock_search_engine(self):
        """Create mock search engine."""
        engine = MagicMock()
        engine.search = AsyncMock(
            return_value=[
                {"id": "node-1", "content": "腾讯是互联网公司", "score": 0.9, "entities": ["腾讯"]},
            ]
        )
        return engine

    @pytest.fixture
    def mock_entity_aggregator(self):
        """Create mock entity aggregator."""
        aggregator = MagicMock()
        aggregator.aggregate = AsyncMock(
            return_value=MagicMock(
                entity_name="腾讯",
                entity_type="ORG",
                facts=["腾讯是互联网公司"],
                count=1,
                confidence=0.85,
            )
        )
        return aggregator

    @pytest.fixture
    def mock_synthesizer(self):
        """Create mock synthesizer."""
        synthesizer = MagicMock()
        synthesizer.synthesize = AsyncMock(
            return_value=MagicMock(
                output="综合叙述内容",
                mode=OutputMode.CONTEXT,
                total_tokens=100,
                node_count=1,
                included_nodes=["node-1"],
                summarized_nodes=[],
            )
        )
        return synthesizer

    @pytest.mark.asyncio
    async def test_build_response_basic(
        self, mock_llm, mock_search_engine, mock_entity_aggregator, mock_synthesizer
    ):
        """Test basic response building."""
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=mock_entity_aggregator,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        result = await builder.build(
            query="腾讯是什么？",
            output_mode=OutputMode.CONTEXT,
            enrich_entities=False,
        )

        assert result is not None
        assert "query" in result
        assert result["query"] == "腾讯是什么？"

    @pytest.mark.asyncio
    async def test_build_response_with_entity_enrichment(
        self, mock_llm, mock_search_engine, mock_entity_aggregator, mock_synthesizer
    ):
        """Test response building with entity enrichment."""
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=mock_entity_aggregator,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        result = await builder.build(
            query="腾讯和AI的关系？",
            output_mode=OutputMode.CONTEXT,
            enrich_entities=True,
        )

        # Entity aggregator should be called
        assert mock_entity_aggregator.aggregate.call_count >= 1
        assert len(result["entities"]) > 0


class TestGraphTypes:
    """Tests for MAGMA graph type definitions."""

    def test_aggregation_type_values(self):
        """Test AggregationType enum values."""
        assert AggregationType.FACTS.value == "FACTS"
        assert AggregationType.COUNT.value == "COUNT"
        assert AggregationType.TIMELINE.value == "TIMELINE"

    def test_output_mode_values(self):
        """Test OutputMode enum values."""
        assert OutputMode.CONTEXT.value == "CONTEXT"
        assert OutputMode.NARRATIVE.value == "NARRATIVE"

    def test_entity_neighborhood_dataclass(self):
        """Test EntityNeighborhood dataclass."""
        from modules.memory.core.graph_types import EntityNeighborhood

        neighborhood = EntityNeighborhood(
            center="腾讯",
            events=[{"content": "test"}],
            related_entities=[{"name": "AI"}],
            relations=[],
            hops=2,
        )

        assert neighborhood.center == "腾讯"
        assert len(neighborhood.events) == 1
        assert neighborhood.hops == 2

    def test_aggregation_result_dataclass(self):
        """Test AggregationResult dataclass."""
        from modules.memory.core.graph_types import AggregationResult

        result = AggregationResult(
            entity_name="腾讯",
            entity_type="ORG",
            aggregation_type=AggregationType.FACTS,
            facts=["fact1", "fact2"],
            count=0,
            reasoning_trace="reasoning",
            confidence=0.85,
        )

        assert result.entity_name == "腾讯"
        assert len(result.facts) == 2
        assert result.confidence == 0.85

    def test_synthesis_result_dataclass(self):
        """Test SynthesisResult dataclass."""
        from modules.memory.core.graph_types import SynthesisResult

        result = SynthesisResult(
            output="narrative output",
            mode=OutputMode.NARRATIVE,
            total_tokens=100,
            node_count=5,
            included_nodes=["node1"],
            summarized_nodes=["node2"],
        )

        assert result.output == "narrative output"
        assert result.mode == OutputMode.NARRATIVE
        assert result.total_tokens == 100
