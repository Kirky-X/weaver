# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for StructuralConsolidationWorker."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import CausalRelationType
from modules.memory.evolution.result import ConsolidationResult
from modules.memory.evolution.slow_path import StructuralConsolidationWorker


@pytest.fixture
def mock_temporal_repo():
    """Create mock temporal repository."""
    repo = MagicMock()
    repo.get_neighbors = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_causal_repo():
    """Create mock causal repository."""
    repo = MagicMock()
    repo.add_causal_edge = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_queue():
    """Create mock consolidation queue."""
    queue = MagicMock()
    queue.dequeue = AsyncMock(return_value=None)
    return queue


@pytest.fixture
def mock_llm():
    """Create mock LLM client."""
    llm = MagicMock()
    llm.call = AsyncMock(return_value={"causal_edges": []})
    return llm


@pytest.fixture
def worker(mock_temporal_repo, mock_causal_repo, mock_queue, mock_llm):
    """Create StructuralConsolidationWorker with mocks."""
    return StructuralConsolidationWorker(
        temporal_repo=mock_temporal_repo,
        causal_repo=mock_causal_repo,
        consolidation_queue=mock_queue,
        llm_client=mock_llm,
        confidence_threshold=0.7,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_event_no_neighbors(worker, mock_temporal_repo):
    """Test processing event with no neighbors."""
    mock_temporal_repo.get_neighbors.return_value = []

    result = await worker.process_event("event-001")

    assert result.event_id == "event-001"
    assert result.causal_edges_added == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_event_with_causal_edges(
    worker, mock_temporal_repo, mock_llm, mock_causal_repo
):
    """Test processing event with inferred causal edges."""
    mock_temporal_repo.get_neighbors.return_value = [
        {"id": "event-001", "content": "First event"},
        {"id": "event-002", "content": "Second event"},
    ]

    mock_llm.call.return_value = {
        "causal_edges": [
            {
                "source_id": "event-001",
                "target_id": "event-002",
                "relation_type": "CAUSES",
                "confidence": 0.85,
                "evidence": "Test evidence",
            }
        ]
    }

    result = await worker.process_event("event-001")

    assert result.causal_edges_added == 1
    mock_causal_repo.add_causal_edge.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_event_filters_low_confidence(
    worker, mock_temporal_repo, mock_llm, mock_causal_repo
):
    """Test that low confidence edges are filtered."""
    mock_temporal_repo.get_neighbors.return_value = [
        {"id": "event-001", "content": "First event"},
    ]

    mock_llm.call.return_value = {
        "causal_edges": [
            {
                "source_id": "event-001",
                "target_id": "event-002",
                "relation_type": "CAUSES",
                "confidence": 0.5,  # Below threshold
                "evidence": "Test",
            }
        ]
    }

    result = await worker.process_event("event-001")

    assert result.causal_edges_added == 0
    mock_causal_repo.add_causal_edge.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_infer_causal_relations(worker, mock_llm):
    """Test LLM causal inference."""
    mock_llm.call.return_value = {
        "causal_edges": [
            {
                "source_id": "a",
                "target_id": "b",
                "relation_type": "CAUSES",
                "confidence": 0.9,
            }
        ]
    }

    edges = await worker._infer_causal_relations("center", [{"id": "a"}, {"id": "b"}])

    assert len(edges) == 1
    assert edges[0]["source_id"] == "a"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_batch(worker, mock_queue):
    """Test batch processing."""
    mock_queue.dequeue.side_effect = ["event-001", "event-002", None]

    results = await worker.process_batch(batch_size=5)

    assert len(results) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_batch_empty_queue(worker, mock_queue):
    """Test batch processing with empty queue."""
    mock_queue.dequeue.return_value = None

    results = await worker.process_batch(batch_size=5)

    assert len(results) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_event_handles_llm_error(worker, mock_temporal_repo, mock_llm):
    """Test handling LLM errors gracefully."""
    mock_temporal_repo.get_neighbors.return_value = [{"id": "event-001"}]
    mock_llm.call.side_effect = Exception("LLM error")

    result = await worker.process_event("event-001")

    # Should return empty result, not raise
    assert result.event_id == "event-001"
    assert result.causal_edges_added == 0
