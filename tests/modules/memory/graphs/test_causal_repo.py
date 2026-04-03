# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for CausalGraphRepo."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import CausalRelationType
from modules.memory.graphs.causal import CausalGraphRepo


@pytest.fixture
def mock_pool():
    """Create mock Neo4j pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def repo(mock_pool):
    """Create CausalGraphRepo with mock pool."""
    return CausalGraphRepo(pool=mock_pool, confidence_threshold=0.7)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_causal_edge_creates_relationship(repo, mock_pool):
    """Test that add_causal_edge creates CAUSES relationship."""
    mock_pool.execute_query.return_value = [{"r": {}}]

    result = await repo.add_causal_edge(
        source_id="event-001",
        target_id="event-002",
        relation_type=CausalRelationType.CAUSES,
        confidence=0.85,
        evidence="Test evidence",
    )

    assert result is True
    mock_pool.execute_query.assert_called_once()

    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0] if call_args[0] else call_args.kwargs.get("query", "")
    assert "CAUSES" in query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_causal_edge_filters_low_confidence(repo, mock_pool):
    """Test that low confidence edges are filtered."""
    result = await repo.add_causal_edge(
        source_id="event-001",
        target_id="event-002",
        relation_type=CausalRelationType.CAUSES,
        confidence=0.5,  # Below threshold
        evidence="Test evidence",
    )

    assert result is False
    # Should not call Neo4j
    mock_pool.execute_query.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_causal_chain(repo, mock_pool):
    """Test retrieving causal chain."""
    mock_pool.execute_query.return_value = [
        {"id": "event-001", "content": "Root cause"},
        {"id": "event-002", "content": "Intermediate"},
        {"id": "event-003", "content": "Final event"},
    ]

    chain = await repo.get_causal_chain("event-003", max_depth=3)

    assert len(chain) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_causes(repo, mock_pool):
    """Test getting causes of an event."""
    mock_pool.execute_query.return_value = [
        {
            "id": "cause-001",
            "content": "Cause 1",
            "relation_type": "CAUSES",
            "confidence": 0.9,
        },
        {
            "id": "cause-002",
            "content": "Cause 2",
            "relation_type": "ENABLES",
            "confidence": 0.8,
        },
    ]

    causes = await repo.get_causes("event-003")

    assert len(causes) == 2
    assert causes[0]["relation_type"] == "CAUSES"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_effects(repo, mock_pool):
    """Test getting effects of an event."""
    mock_pool.execute_query.return_value = [
        {
            "id": "effect-001",
            "content": "Effect 1",
            "relation_type": "CAUSES",
            "confidence": 0.85,
        },
    ]

    effects = await repo.get_effects("event-001")

    assert len(effects) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_constraints(repo, mock_pool):
    """Test that indexes are created."""
    mock_pool.execute_query.return_value = []

    await repo.ensure_constraints()

    assert mock_pool.execute_query.call_count >= 1
