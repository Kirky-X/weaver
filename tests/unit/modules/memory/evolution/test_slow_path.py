# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for StructuralConsolidationWorker (Slow Path)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import CausalRelationType
from modules.memory.evolution.result import ConsolidationResult
from modules.memory.evolution.slow_path import StructuralConsolidationWorker


class TestSlowPathProcessEvent:
    """Tests for StructuralConsolidationWorker.process_event()."""

    @pytest.fixture
    def mock_temporal_repo(self):
        repo = MagicMock()
        repo.get_neighbors = AsyncMock(
            return_value=[
                {"id": "neighbor-1", "content": "Event 1"},
                {"id": "neighbor-2", "content": "Event 2"},
            ]
        )
        return repo

    @pytest.fixture
    def mock_causal_repo(self):
        repo = MagicMock()
        repo.add_causal_edge = AsyncMock(return_value=True)
        return repo

    @pytest.fixture
    def mock_queue(self):
        queue = MagicMock()
        queue.dequeue = AsyncMock(return_value=None)
        return queue

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.call = AsyncMock(
            return_value={
                "causal_edges": [
                    {
                        "source_id": "event-1",
                        "target_id": "event-2",
                        "relation_type": "CAUSES",
                        "confidence": 0.8,
                        "evidence": "test evidence",
                    }
                ]
            }
        )
        return llm

    @pytest.mark.asyncio
    async def test_process_event_basic(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )

        result = await worker.process_event("event-1")

        assert isinstance(result, ConsolidationResult)
        assert result.event_id == "event-1"

    @pytest.mark.asyncio
    async def test_process_event_no_neighbors(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        mock_temporal_repo.get_neighbors = AsyncMock(return_value=[])

        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )

        result = await worker.process_event("event-1")

        assert result.causal_edges_added == 0
        assert result.entity_links_added == 0

    @pytest.mark.asyncio
    async def test_process_event_with_causal_edges(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )

        result = await worker.process_event("event-1")

        assert result.causal_edges_added == 1
        assert result.confidence_avg == 0.8

    @pytest.mark.asyncio
    async def test_process_event_filters_below_threshold(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        mock_llm.call = AsyncMock(
            return_value={
                "causal_edges": [
                    {
                        "source_id": "event-1",
                        "target_id": "event-2",
                        "relation_type": "CAUSES",
                        "confidence": 0.3,
                        "evidence": "low confidence",
                    }
                ]
            }
        )

        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
            confidence_threshold=0.7,
        )

        result = await worker.process_event("event-1")

        assert result.causal_edges_added == 0

    @pytest.mark.asyncio
    async def test_process_event_causal_repo_failure(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        mock_causal_repo.add_causal_edge = AsyncMock(return_value=False)

        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )

        result = await worker.process_event("event-1")

        assert result.causal_edges_added == 0

    @pytest.mark.asyncio
    async def test_process_event_exception_handling(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        mock_temporal_repo.get_neighbors = AsyncMock(side_effect=Exception("DB error"))

        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )

        result = await worker.process_event("event-1")

        assert result.causal_edges_added == 0
        assert result.entity_links_added == 0

    @pytest.mark.asyncio
    async def test_process_event_with_entity_links(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        mock_entity_repo = MagicMock()
        mock_entity_repo.extract_entities_from_text = AsyncMock(
            return_value=[{"name": "EntityA", "type": "ORG"}]
        )
        mock_entity_repo.link_event_to_entities = AsyncMock(return_value=2)

        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
            entity_repo=mock_entity_repo,
        )

        result = await worker.process_event("event-1")

        assert result.entity_links_added == 2

    @pytest.mark.asyncio
    async def test_process_event_without_entity_repo(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
            entity_repo=None,
        )

        result = await worker.process_event("event-1")

        assert result.entity_links_added == 0


class TestSlowPathInferCausalRelations:
    """Tests for _infer_causal_relations."""

    @pytest.fixture
    def worker(self):
        return StructuralConsolidationWorker(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            consolidation_queue=MagicMock(),
            llm_client=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_infer_causal_dict_response(self, worker):
        worker._llm.call = AsyncMock(
            return_value={
                "causal_edges": [
                    {
                        "source_id": "e1",
                        "target_id": "e2",
                        "relation_type": "CAUSES",
                        "confidence": 0.9,
                        "evidence": "test",
                    }
                ]
            }
        )

        result = await worker._infer_causal_relations("center-1", [{"id": "e1"}])

        assert len(result) == 1
        assert result[0]["source_id"] == "e1"

    @pytest.mark.asyncio
    async def test_infer_causal_string_response(self, worker):
        import json

        response = json.dumps(
            {
                "causal_edges": [
                    {
                        "source_id": "e1",
                        "target_id": "e2",
                        "relation_type": "ENABLES",
                        "confidence": 0.7,
                        "evidence": "test",
                    }
                ]
            }
        )
        worker._llm.call = AsyncMock(return_value=response)

        result = await worker._infer_causal_relations("center-1", [{"id": "e1"}])

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_infer_causal_llm_error(self, worker):
        worker._llm.call = AsyncMock(side_effect=Exception("LLM error"))

        result = await worker._infer_causal_relations("center-1", [{"id": "e1"}])

        assert result == []

    @pytest.mark.asyncio
    async def test_infer_causal_invalid_json(self, worker):
        worker._llm.call = AsyncMock(return_value="not valid json")

        result = await worker._infer_causal_relations("center-1", [{"id": "e1"}])

        assert result == []


class TestSlowPathProcessBatch:
    """Tests for process_batch."""

    @pytest.fixture
    def mock_temporal_repo(self):
        return MagicMock()

    @pytest.fixture
    def mock_causal_repo(self):
        return MagicMock()

    @pytest.fixture
    def mock_queue(self):
        queue = MagicMock()
        queue.dequeue = AsyncMock(side_effect=["event-1", "event-2", None])
        return queue

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_process_batch_processes_events(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )
        worker.process_event = AsyncMock(return_value=ConsolidationResult(event_id="test"))

        results = await worker.process_batch(batch_size=5)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_process_batch_stops_on_empty_queue(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        mock_queue.dequeue = AsyncMock(return_value=None)

        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )

        results = await worker.process_batch(batch_size=5)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_process_batch_respects_batch_size(
        self, mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm
    ):
        mock_queue.dequeue = AsyncMock(side_effect=["e1", "e2", "e3"])

        worker = StructuralConsolidationWorker(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            consolidation_queue=mock_queue,
            llm_client=mock_llm,
        )
        worker.process_event = AsyncMock(return_value=ConsolidationResult(event_id="test"))

        results = await worker.process_batch(batch_size=2)

        assert len(results) == 2


class TestSlowPathDiscoverEntityLinks:
    """Tests for _discover_entity_links."""

    @pytest.fixture
    def worker_with_entity_repo(self):
        entity_repo = MagicMock()
        entity_repo.extract_entities_from_text = AsyncMock(return_value=[{"name": "EntityA"}])
        entity_repo.link_event_to_entities = AsyncMock(return_value=1)

        return StructuralConsolidationWorker(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            consolidation_queue=MagicMock(),
            llm_client=MagicMock(),
            entity_repo=entity_repo,
        )

    @pytest.mark.asyncio
    async def test_discover_entity_links_basic(self, worker_with_entity_repo):
        neighborhood = [
            {"id": "e1", "content": "Event about EntityA"},
        ]

        result = await worker_with_entity_repo._discover_entity_links("event-1", neighborhood)

        assert result == 1

    @pytest.mark.asyncio
    async def test_discover_entity_links_no_content(self, worker_with_entity_repo):
        neighborhood = [{"id": "e1"}]

        result = await worker_with_entity_repo._discover_entity_links("event-1", neighborhood)

        assert result == 0

    @pytest.mark.asyncio
    async def test_discover_entity_links_no_entities_extracted(self, worker_with_entity_repo):
        worker_with_entity_repo._entity_repo.extract_entities_from_text = AsyncMock(return_value=[])

        neighborhood = [{"id": "e1", "content": "Some text"}]

        result = await worker_with_entity_repo._discover_entity_links("event-1", neighborhood)

        assert result == 0

    @pytest.mark.asyncio
    async def test_discover_entity_links_exception(self, worker_with_entity_repo):
        worker_with_entity_repo._entity_repo.extract_entities_from_text = AsyncMock(
            side_effect=Exception("NLP error")
        )

        neighborhood = [{"id": "e1", "content": "Some text"}]

        result = await worker_with_entity_repo._discover_entity_links("event-1", neighborhood)

        assert result == 0

    @pytest.mark.asyncio
    async def test_discover_entity_links_without_repo(self):
        worker = StructuralConsolidationWorker(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            consolidation_queue=MagicMock(),
            llm_client=MagicMock(),
            entity_repo=None,
        )

        result = await worker._discover_entity_links("event-1", [{"content": "test"}])

        assert result == 0
