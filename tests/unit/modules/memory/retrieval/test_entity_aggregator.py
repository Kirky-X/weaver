# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for EntityAggregator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import AggregationType
from modules.memory.retrieval.entity_aggregator import EntityAggregator


class TestEntityAggregatorFacts:
    """Tests for FACTS aggregation mode."""

    @pytest.fixture
    def mock_entity_repo(self):
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
    async def test_facts_basic(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.FACTS,
        )

        assert result.entity_name == "腾讯"
        assert result.entity_type == "ORG"
        assert result.aggregation_type == AggregationType.FACTS
        assert len(result.facts) == 2
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_facts_limits_to_ten(self, mock_entity_repo, mock_llm):
        mock_llm.call_at = AsyncMock(
            return_value={
                "facts": [f"fact {i}" for i in range(15)],
                "entity_type": "ORG",
                "confidence": 0.8,
            }
        )

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.FACTS,
        )

        assert len(result.facts) == 10

    @pytest.mark.asyncio
    async def test_facts_llm_returns_string(self, mock_entity_repo, mock_llm):
        mock_llm.call_at = AsyncMock(return_value="Line1\nLine2\nLine3")

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.FACTS,
        )

        assert len(result.facts) == 3
        assert result.entity_type == "unknown"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_facts_llm_error(self, mock_entity_repo, mock_llm):
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM error"))

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.FACTS,
        )

        assert result.entity_name == "腾讯"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_facts_calls_llm_with_correct_params(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.FACTS,
        )

        mock_llm.call_at.assert_called_once()
        call_kwargs = mock_llm.call_at.call_args.kwargs
        assert call_kwargs["call_point"] == "ENTITY_FACTS"
        assert call_kwargs["payload"]["entity_name"] == "腾讯"
        assert call_kwargs["payload"]["task"] == "extract_facts"
        assert "腾讯" in call_kwargs["payload"]["context"]


class TestEntityAggregatorCount:
    """Tests for COUNT aggregation mode."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.get_entity_neighborhood = AsyncMock(
            return_value={
                "center": "腾讯",
                "hops": 2,
                "events": [
                    {"content": "Event 1", "timestamp": "2026-01-01"},
                    {"content": "Event 2", "timestamp": "2026-01-02"},
                    {"content": "Event 3", "timestamp": "2026-01-03"},
                ],
                "related_entities": [
                    {"canonical_name": "AI", "type": "TECH"},
                    {"canonical_name": "马化腾", "type": "PERSON"},
                    {"canonical_name": "微信", "type": "PRODUCT"},
                ],
                "relations": [
                    {"source": "腾讯", "target": "AI", "type": "develops"},
                    {"source": "腾讯", "target": "微信", "type": "owns"},
                ],
            }
        )
        return repo

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_count_basic(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        assert result.entity_name == "腾讯"
        assert result.aggregation_type == AggregationType.COUNT
        assert result.count == 3
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_count_confidence_scales_with_events(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        assert result.confidence == min(1.0, 3 / 10)

    @pytest.mark.asyncio
    async def test_count_entity_type_from_related_entities(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        assert result.entity_type == "TECH"

    @pytest.mark.asyncio
    async def test_count_no_related_entities(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(
            return_value={
                "center": "腾讯",
                "events": [],
                "related_entities": [],
                "relations": [],
            }
        )

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        assert result.entity_type == "unknown"
        assert result.count == 0
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_count_reasoning_trace(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        assert "3 events" in result.reasoning_trace
        assert "3 related entities" in result.reasoning_trace
        assert "2 relationships" in result.reasoning_trace

    @pytest.mark.asyncio
    async def test_count_does_not_call_llm(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        mock_llm.call_at.assert_not_called()


class TestEntityAggregatorTimeline:
    """Tests for TIMELINE aggregation mode."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.get_entity_neighborhood = AsyncMock(
            return_value={
                "center": "腾讯",
                "hops": 2,
                "events": [
                    {"content": "First event", "timestamp": "2026-01-01"},
                    {"content": "Second event", "timestamp": "2026-02-01"},
                    {"content": "Third event", "timestamp": "2026-03-01"},
                ],
                "related_entities": [
                    {"canonical_name": "AI", "type": "TECH"},
                ],
                "relations": [],
            }
        )
        return repo

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_timeline_basic(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        assert result.entity_name == "腾讯"
        assert result.aggregation_type == AggregationType.TIMELINE
        assert len(result.facts) == 3

    @pytest.mark.asyncio
    async def test_timeline_facts_contain_timestamps(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        for fact in result.facts:
            assert fact.startswith("[")
            assert "]" in fact

    @pytest.mark.asyncio
    async def test_timeline_sorted_by_timestamp(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(
            return_value={
                "center": "腾讯",
                "events": [
                    {"content": "Later event", "timestamp": "2026-03-01"},
                    {"content": "Earlier event", "timestamp": "2026-01-01"},
                ],
                "related_entities": [],
                "relations": [],
            }
        )

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        assert "2026-01-01" in result.facts[0]
        assert "2026-03-01" in result.facts[1]

    @pytest.mark.asyncio
    async def test_timeline_limits_to_ten(self, mock_entity_repo, mock_llm):
        events = [
            {"content": f"Event {i}", "timestamp": f"2026-{i % 12 + 1:02d}-01"} for i in range(15)
        ]
        mock_entity_repo.get_entity_neighborhood = AsyncMock(
            return_value={
                "center": "腾讯",
                "events": events,
                "related_entities": [],
                "relations": [],
            }
        )

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        assert len(result.facts) <= 10

    @pytest.mark.asyncio
    async def test_timeline_skips_events_without_timestamp(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(
            return_value={
                "center": "腾讯",
                "events": [
                    {"content": "No timestamp event"},
                    {"content": "With timestamp", "timestamp": "2026-01-01"},
                ],
                "related_entities": [],
                "relations": [],
            }
        )

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        assert len(result.facts) == 1

    @pytest.mark.asyncio
    async def test_timeline_confidence_scales(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        assert result.confidence == min(1.0, 3 / 5)

    @pytest.mark.asyncio
    async def test_timeline_does_not_call_llm(self, mock_entity_repo, mock_llm):
        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.TIMELINE,
        )

        mock_llm.call_at.assert_not_called()


class TestEntityAggregatorEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def mock_entity_repo(self):
        return MagicMock()

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_entity_not_found(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(return_value=None)

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="不存在实体",
            aggregation_type=AggregationType.FACTS,
        )

        assert result.entity_name == "不存在实体"
        assert result.confidence == 0.0
        assert result.entity_type == "unknown"

    @pytest.mark.asyncio
    async def test_repo_exception(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(side_effect=Exception("DB error"))

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=AggregationType.COUNT,
        )

        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_unknown_aggregation_type(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(
            return_value={"center": "腾讯", "events": [], "related_entities": [], "relations": []}
        )

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        result = await aggregator.aggregate(
            entity_name="腾讯",
            aggregation_type=MagicMock(value="UNKNOWN"),
        )

        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_custom_max_events(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(
            return_value={"center": "test", "events": [], "related_entities": [], "relations": []}
        )

        aggregator = EntityAggregator(
            entity_repo=mock_entity_repo,
            llm=mock_llm,
            max_events=5,
        )

        await aggregator.aggregate(
            entity_name="test",
            aggregation_type=AggregationType.COUNT,
        )

        mock_entity_repo.get_entity_neighborhood.assert_called_once_with(
            entity_name="test",
            hops=2,
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_custom_hops(self, mock_entity_repo, mock_llm):
        mock_entity_repo.get_entity_neighborhood = AsyncMock(
            return_value={"center": "test", "events": [], "related_entities": [], "relations": []}
        )

        aggregator = EntityAggregator(entity_repo=mock_entity_repo, llm=mock_llm)

        await aggregator.aggregate(
            entity_name="test",
            aggregation_type=AggregationType.COUNT,
            hops=3,
        )

        mock_entity_repo.get_entity_neighborhood.assert_called_once_with(
            entity_name="test",
            hops=3,
            limit=20,
        )


class TestEntityAggregatorBuildContext:
    """Tests for _build_neighborhood_context helper."""

    @pytest.fixture
    def aggregator(self):
        return EntityAggregator(
            entity_repo=MagicMock(),
            llm=MagicMock(),
        )

    def test_build_context_basic(self, aggregator):
        neighborhood = {
            "center": "腾讯",
            "hops": 2,
            "events": [
                {"content": "Event 1", "timestamp": "2026-01-01"},
            ],
            "related_entities": [
                {"canonical_name": "AI", "type": "TECH"},
            ],
            "relations": [
                {"source": "腾讯", "target": "AI", "type": "develops"},
            ],
        }

        context = aggregator._build_neighborhood_context(neighborhood)

        assert "Entity: 腾讯" in context
        assert "Hops: 2" in context
        assert "Related Events:" in context
        assert "Event 1" in context
        assert "Related Entities:" in context
        assert "AI (TECH)" in context
        assert "Relations:" in context
        assert "develops" in context

    def test_build_context_empty_neighborhood(self, aggregator):
        neighborhood = {"center": "test"}

        context = aggregator._build_neighborhood_context(neighborhood)

        assert "Entity: test" in context

    def test_build_context_uses_name_fallback(self, aggregator):
        neighborhood = {
            "center": "test",
            "related_entities": [
                {"name": "EntityName", "type": "TYPE"},
            ],
        }

        context = aggregator._build_neighborhood_context(neighborhood)

        assert "EntityName (TYPE)" in context

    def test_build_context_limits_events_to_ten(self, aggregator):
        neighborhood = {
            "center": "test",
            "events": [{"content": f"Event {i}", "timestamp": "2026-01-01"} for i in range(15)],
        }

        context = aggregator._build_neighborhood_context(neighborhood)

        assert "10." in context
        assert "11." not in context
