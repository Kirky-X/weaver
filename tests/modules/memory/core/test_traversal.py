# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for graph traversal algorithms."""

import math

import pytest

from modules.memory.core.event_node import EventNode
from modules.memory.core.graph_types import EdgeType, IntentType
from modules.memory.core.traversal import calculate_transition_score


@pytest.mark.unit
def test_calculate_transition_score_why_causal():
    """Test transition score for WHY intent with CAUSAL edge."""
    neighbor = EventNode(
        id="neighbor-1",
        content="Neighbor event",
        embedding=[1.0, 0.0, 0.0],
        timestamp=None,  # Will be set by fixture if needed
    )
    query_embedding = [1.0, 0.0, 0.0]  # Same as neighbor

    score = calculate_transition_score(
        neighbor=neighbor,
        query_embedding=query_embedding,
        query_intent=IntentType.WHY,
        edge_type=EdgeType.CAUSAL,
    )

    # Should be high: causal edge (5.0 weight) + perfect semantic similarity (1.0)
    # S = exp(λ1 * 5.0 + λ2 * 1.0) = exp(1.0 * 5.0 + 0.5 * 1.0) = exp(5.5)
    assert score > 100  # exp(5.5) ≈ 244


@pytest.mark.unit
def test_calculate_transition_score_when_temporal():
    """Test transition score for WHEN intent with TEMPORAL edge."""
    neighbor = EventNode(
        id="neighbor-2",
        content="Temporal neighbor",
        embedding=[0.8, 0.6, 0.0],
        timestamp=None,
    )
    query_embedding = [1.0, 0.0, 0.0]

    score = calculate_transition_score(
        neighbor=neighbor,
        query_embedding=query_embedding,
        query_intent=IntentType.WHEN,
        edge_type=EdgeType.TEMPORAL,
    )

    # Temporal edge weight is 5.0 for WHEN, semantic similarity is 0.8
    # S = exp(1.0 * 5.0 + 0.5 * 0.8) = exp(5.4)
    assert score > 100


@pytest.mark.unit
def test_calculate_transition_score_entity_entity():
    """Test transition score for ENTITY intent with ENTITY edge."""
    neighbor = EventNode(
        id="neighbor-3",
        content="Entity neighbor",
        embedding=[0.5, 0.5, 0.707],
        timestamp=None,
    )
    query_embedding = [0.5, 0.5, 0.707]  # Same as neighbor

    score = calculate_transition_score(
        neighbor=neighbor,
        query_embedding=query_embedding,
        query_intent=IntentType.ENTITY,
        edge_type=EdgeType.ENTITY,
    )

    # Entity edge weight is 5.0 for ENTITY, semantic similarity is 1.0
    assert score > 100


@pytest.mark.unit
def test_calculate_transition_score_low_semantic():
    """Test transition score with low semantic similarity."""
    neighbor = EventNode(
        id="neighbor-4",
        content="Dissimilar neighbor",
        embedding=[0.0, 0.0, 1.0],  # Orthogonal to query
        timestamp=None,
    )
    query_embedding = [1.0, 0.0, 0.0]

    score = calculate_transition_score(
        neighbor=neighbor,
        query_embedding=query_embedding,
        query_intent=IntentType.WHY,
        edge_type=EdgeType.SEMANTIC,  # Low weight for WHY
    )

    # Semantic edge weight is 0.5 for WHY, semantic similarity is 0
    # S = exp(1.0 * 0.5 + 0.5 * 0.0) = exp(0.5) ≈ 1.65
    assert 1.0 < score < 5.0


@pytest.mark.unit
def test_calculate_transition_score_missing_embedding():
    """Test transition score when neighbor has no embedding."""
    neighbor = EventNode(
        id="neighbor-5",
        content="No embedding",
        embedding=None,
        timestamp=None,
    )
    query_embedding = [1.0, 0.0, 0.0]

    score = calculate_transition_score(
        neighbor=neighbor,
        query_embedding=query_embedding,
        query_intent=IntentType.WHY,
        edge_type=EdgeType.CAUSAL,
    )

    # Should still work with zero semantic score
    assert score > 0


@pytest.mark.unit
def test_transition_score_exponential_growth():
    """Test that scores grow exponentially with higher weights."""
    neighbor = EventNode(
        id="neighbor-6",
        content="Test",
        embedding=[1.0, 0.0, 0.0],
        timestamp=None,
    )
    query_embedding = [1.0, 0.0, 0.0]

    score_low = calculate_transition_score(
        neighbor=neighbor,
        query_embedding=query_embedding,
        query_intent=IntentType.WHY,
        edge_type=EdgeType.SEMANTIC,  # weight 0.5
    )

    score_high = calculate_transition_score(
        neighbor=neighbor,
        query_embedding=query_embedding,
        query_intent=IntentType.WHY,
        edge_type=EdgeType.CAUSAL,  # weight 5.0
    )

    # High weight should give significantly higher score
    assert score_high > score_low * 10
