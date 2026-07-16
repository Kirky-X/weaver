# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for SearchResponseBuilder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import AggregationType, OutputMode


class TestSearchResponseBuilderBuild:
    """Tests for SearchResponseBuilder.build()."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.call_at = AsyncMock(return_value={"answer": "test", "tokens_used": 50})
        return llm

    @pytest.fixture
    def mock_search_engine(self):
        engine = MagicMock()
        engine.search = AsyncMock(
            return_value=[
                {
                    "id": "node-1",
                    "content": "Test content",
                    "score": 0.9,
                    "entities": [{"name": "EntityA"}],
                    "timestamp": "2026-01-01",
                },
                {
                    "id": "node-2",
                    "content": "More content",
                    "score": 0.7,
                    "entities": [{"name": "EntityB"}],
                    "timestamp": "2026-01-02",
                },
            ]
        )
        return engine

    @pytest.fixture
    def mock_entity_aggregator(self):
        aggregator = MagicMock()
        aggregator.aggregate = AsyncMock(
            return_value=MagicMock(
                entity_name="EntityA",
                entity_type="ORG",
                facts=["fact1"],
                count=1,
                confidence=0.85,
            )
        )
        return aggregator

    @pytest.fixture
    def mock_synthesizer(self):
        synthesizer = MagicMock()
        synthesizer.synthesize = AsyncMock(
            return_value=MagicMock(
                output="Synthesized output",
                mode=OutputMode.CONTEXT,
                total_tokens=100,
                node_count=2,
                included_nodes=["node-1", "node-2"],
                summarized_nodes=[],
            )
        )
        return synthesizer

    @pytest.mark.asyncio
    async def test_build_basic_response(
        self, mock_llm, mock_search_engine, mock_entity_aggregator, mock_synthesizer
    ):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=mock_entity_aggregator,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        result = await builder.build(query="test query", output_mode=OutputMode.CONTEXT)

        assert result["query"] == "test query"
        assert result["answer"] == "Synthesized output"
        assert result["output_mode"] == "CONTEXT"
        assert result["context_tokens"] == 100
        assert result["node_count"] == 2
        assert result["included_nodes"] == ["node-1", "node-2"]
        assert result["entities"] == []
        assert "sources" in result
        assert "metadata" in result
        assert result["metadata"]["search_nodes"] == 2
        assert result["metadata"]["enriched_entities"] == 0

    @pytest.mark.asyncio
    async def test_build_with_entity_enrichment(
        self, mock_llm, mock_search_engine, mock_entity_aggregator, mock_synthesizer
    ):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=mock_entity_aggregator,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        result = await builder.build(
            query="test query",
            output_mode=OutputMode.CONTEXT,
            enrich_entities=True,
        )

        assert len(result["entities"]) > 0
        assert result["entities"][0]["entity"] == "EntityA"
        assert result["metadata"]["enriched_entities"] > 0

    @pytest.mark.asyncio
    async def test_build_with_narrative_mode(
        self, mock_llm, mock_search_engine, mock_entity_aggregator, mock_synthesizer
    ):
        mock_synthesizer.synthesize = AsyncMock(
            return_value=MagicMock(
                output="Narrative answer",
                mode=OutputMode.NARRATIVE,
                total_tokens=200,
                node_count=2,
                included_nodes=["node-1", "node-2"],
                summarized_nodes=[],
            )
        )

        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=mock_entity_aggregator,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        result = await builder.build(query="test query", output_mode=OutputMode.NARRATIVE)

        assert result["output_mode"] == "NARRATIVE"
        assert result["answer"] == "Narrative answer"

    @pytest.mark.asyncio
    async def test_build_with_specific_entity_names(
        self, mock_llm, mock_search_engine, mock_entity_aggregator, mock_synthesizer
    ):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=mock_entity_aggregator,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        result = await builder.build(
            query="test query",
            enrich_entities=True,
            entity_names=["EntityA", "EntityB"],
        )

        assert mock_entity_aggregator.aggregate.call_count == 2

    @pytest.mark.asyncio
    async def test_build_without_entity_aggregator(
        self, mock_llm, mock_search_engine, mock_synthesizer
    ):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=None,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        result = await builder.build(
            query="test query",
            enrich_entities=True,
        )

        assert result["entities"] == []

    @pytest.mark.asyncio
    async def test_build_calls_search_engine(self, mock_llm, mock_search_engine, mock_synthesizer):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=None,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        await builder.build(query="find this")

        mock_search_engine.search.assert_called_once_with(query="find this")

    @pytest.mark.asyncio
    async def test_build_calls_synthesizer(
        self, mock_llm, mock_search_engine, mock_entity_aggregator, mock_synthesizer
    ):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=mock_search_engine,
            entity_aggregator=mock_entity_aggregator,
            synthesizer=mock_synthesizer,
            llm=mock_llm,
        )

        search_results = await mock_search_engine.search()
        await builder.build(query="test", output_mode=OutputMode.NARRATIVE)

        mock_synthesizer.synthesize.assert_called_once_with(
            query="test",
            context_nodes=search_results,
            mode=OutputMode.NARRATIVE,
            include_provenance=True,
        )


class TestSearchResponseBuilderEnrichEntities:
    """Tests for SearchResponseBuilder._enrich_entities()."""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.fixture
    def mock_entity_aggregator(self):
        aggregator = MagicMock()
        aggregator.aggregate = AsyncMock(
            return_value=MagicMock(
                entity_name="EntityA",
                entity_type="ORG",
                facts=["fact1", "fact2"],
                count=3,
                confidence=0.9,
            )
        )
        return aggregator

    @pytest.fixture
    def builder(self, mock_llm, mock_entity_aggregator):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        return SearchResponseBuilder(
            search_engine=MagicMock(),
            entity_aggregator=mock_entity_aggregator,
            synthesizer=MagicMock(),
            llm=mock_llm,
        )

    @pytest.mark.asyncio
    async def test_enrich_with_entity_names(self, builder, mock_entity_aggregator):
        search_results = [{"id": "1", "entities": []}]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=["EntityA", "EntityB"],
        )

        assert mock_entity_aggregator.aggregate.call_count == 2
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_enrich_extracts_entities_from_search_results_dict(
        self, builder, mock_entity_aggregator
    ):
        search_results = [
            {"id": "1", "entities": [{"name": "EntityA"}, {"name": "EntityB"}]},
        ]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        assert len(result) == 2
        calls = mock_entity_aggregator.aggregate.call_args_list
        assert calls[0].kwargs["entity_name"] == "EntityA"
        assert calls[1].kwargs["entity_name"] == "EntityB"

    @pytest.mark.asyncio
    async def test_enrich_extracts_entities_from_search_results_str(
        self, builder, mock_entity_aggregator
    ):
        search_results = [
            {"id": "1", "entities": ["EntityA"]},
        ]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_enrich_limits_to_five_entities(self, builder, mock_entity_aggregator):
        search_results = [
            {
                "id": "1",
                "entities": [
                    {"name": "E1"},
                    {"name": "E2"},
                    {"name": "E3"},
                    {"name": "E4"},
                    {"name": "E5"},
                    {"name": "E6"},
                ],
            },
        ]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        assert mock_entity_aggregator.aggregate.call_count == 5

    @pytest.mark.asyncio
    async def test_enrich_limits_entity_names_to_five(self, builder, mock_entity_aggregator):
        search_results = []

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=["E1", "E2", "E3", "E4", "E5", "E6"],
        )

        assert mock_entity_aggregator.aggregate.call_count == 5

    @pytest.mark.asyncio
    async def test_enrich_deduplicates_entities(self, builder, mock_entity_aggregator):
        search_results = [
            {"id": "1", "entities": [{"name": "EntityA"}, {"name": "EntityA"}]},
        ]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        assert mock_entity_aggregator.aggregate.call_count == 1

    @pytest.mark.asyncio
    async def test_enrich_handles_aggregation_error(self, builder, mock_entity_aggregator):
        mock_entity_aggregator.aggregate = AsyncMock(side_effect=Exception("Aggregation error"))

        search_results = [{"id": "1", "entities": [{"name": "EntityA"}]}]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_enrich_without_aggregator(self, mock_llm):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        builder = SearchResponseBuilder(
            search_engine=MagicMock(),
            entity_aggregator=None,
            synthesizer=MagicMock(),
            llm=mock_llm,
        )

        result = await builder._enrich_entities(
            query="test",
            search_results=[],
            entity_names=None,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_enrich_uses_facts_aggregation_type(self, builder, mock_entity_aggregator):
        search_results = [{"id": "1", "entities": [{"name": "EntityA"}]}]

        await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        call_kwargs = mock_entity_aggregator.aggregate.call_args.kwargs
        assert call_kwargs["aggregation_type"] == AggregationType.FACTS
        assert call_kwargs["hops"] == 2

    @pytest.mark.asyncio
    async def test_enrich_skips_non_dict_non_str_entities(self, builder, mock_entity_aggregator):
        search_results = [
            {"id": "1", "entities": [123, None, {"name": "EntityA"}]},
        ]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        assert mock_entity_aggregator.aggregate.call_count == 1

    @pytest.mark.asyncio
    async def test_enrich_result_structure(self, builder, mock_entity_aggregator):
        search_results = [{"id": "1", "entities": [{"name": "EntityA"}]}]

        result = await builder._enrich_entities(
            query="test",
            search_results=search_results,
            entity_names=None,
        )

        assert len(result) == 1
        assert result[0]["entity"] == "EntityA"
        assert result[0]["type"] == "ORG"
        assert result[0]["facts"] == ["fact1", "fact2"]
        assert result[0]["count"] == 3
        assert result[0]["confidence"] == 0.9


class TestSearchResponseBuilderExtractSources:
    """Tests for SearchResponseBuilder._extract_sources()."""

    @pytest.fixture
    def builder(self):
        from modules.memory.retrieval.response_builder import SearchResponseBuilder

        return SearchResponseBuilder(
            search_engine=MagicMock(),
            entity_aggregator=None,
            synthesizer=MagicMock(),
            llm=MagicMock(),
        )

    def test_extract_sources_basic(self, builder):
        search_results = [
            {"id": "node-1", "score": 0.9, "timestamp": "2026-01-01"},
            {"id": "node-2", "score": 0.7, "timestamp": "2026-01-02"},
        ]

        sources = builder._extract_sources(search_results)

        assert len(sources) == 2
        assert sources[0]["id"] == "node-1"
        assert sources[0]["score"] == 0.9
        assert sources[0]["timestamp"] == "2026-01-01"

    def test_extract_sources_deduplicates(self, builder):
        search_results = [
            {"id": "node-1", "score": 0.9},
            {"id": "node-1", "score": 0.8},
        ]

        sources = builder._extract_sources(search_results)

        assert len(sources) == 1

    def test_extract_sources_limits_to_twenty(self, builder):
        search_results = [{"id": f"node-{i}", "score": 0.5} for i in range(25)]

        sources = builder._extract_sources(search_results)

        assert len(sources) == 20

    def test_extract_sources_skips_empty_ids(self, builder):
        search_results = [
            {"id": "", "score": 0.9},
            {"id": "node-1", "score": 0.7},
        ]

        sources = builder._extract_sources(search_results)

        assert len(sources) == 1
        assert sources[0]["id"] == "node-1"

    def test_extract_sources_default_score(self, builder):
        search_results = [{"id": "node-1"}]

        sources = builder._extract_sources(search_results)

        assert sources[0]["score"] == 0.0

    def test_extract_sources_empty_results(self, builder):
        sources = builder._extract_sources([])

        assert sources == []

    def test_extract_sources_no_id_field(self, builder):
        search_results = [{"score": 0.9}]

        sources = builder._extract_sources(search_results)

        assert len(sources) == 0

    def test_extract_sources_preserves_timestamp_none(self, builder):
        search_results = [{"id": "node-1", "score": 0.9}]

        sources = builder._extract_sources(search_results)

        assert sources[0]["timestamp"] is None
