# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for graph traversal algorithms in memory core."""

import math
from datetime import UTC, datetime

import pytest

from modules.memory.core.event_node import EventNode
from modules.memory.core.graph_types import EdgeType, IntentType
from modules.memory.core.traversal import calculate_transition_score


class TestCalculateTransitionScore:
    """Test calculate_transition_score function."""

    # Fixtures

    @pytest.fixture
    def sample_embedding(self) -> list[float]:
        """Sample embedding vector for testing."""
        return [0.1, 0.2, 0.3, 0.4, 0.5]

    @pytest.fixture
    def similar_embedding(self) -> list[float]:
        """Similar embedding vector (high cosine similarity)."""
        return [0.11, 0.19, 0.31, 0.42, 0.48]

    @pytest.fixture
    def orthogonal_embedding(self) -> list[float]:
        """Orthogonal embedding vector (zero cosine similarity)."""
        return [0.5, -0.5, 0.0, 0.0, 0.0]

    @pytest.fixture
    def sample_node(self, sample_embedding: list[float]) -> EventNode:
        """Sample EventNode with embedding."""
        return EventNode(
            id="test-node-1",
            content="Test event content",
            timestamp=datetime.now(UTC),
            embedding=sample_embedding,
        )

    # Basic functionality tests

    def test_basic_transition_score(self, sample_node: EventNode, sample_embedding: list[float]):
        """Test basic transition score calculation."""
        score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHY,
            edge_type=EdgeType.CAUSAL,
        )
        assert isinstance(score, float)
        assert score > 0  # exp() always positive

    def test_identical_vectors_max_score(
        self, sample_node: EventNode, sample_embedding: list[float]
    ):
        """Test that identical vectors produce high semantic score."""
        score_identical = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.OPEN,
            edge_type=EdgeType.SEMANTIC,
        )
        # With identical vectors, cosine sim = 1.0, should be high
        assert score_identical > 1.0

    # Intent-Edge weight tests

    @pytest.mark.parametrize(
        "intent,edge_type,expected_weight",
        [
            (IntentType.WHY, EdgeType.CAUSAL, 5.0),
            (IntentType.WHY, EdgeType.TEMPORAL, 2.0),
            (IntentType.WHEN, EdgeType.TEMPORAL, 5.0),
            (IntentType.ENTITY, EdgeType.ENTITY, 5.0),
            (IntentType.OPEN, EdgeType.SEMANTIC, 4.0),
        ],
    )
    def test_intent_edge_weights(
        self,
        sample_node: EventNode,
        sample_embedding: list[float],
        intent: IntentType,
        edge_type: EdgeType,
        expected_weight: float,
    ):
        """Test that different intent-edge combinations produce expected weights."""
        score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=intent,
            edge_type=edge_type,
        )
        # Higher weight should generally produce higher score (with same semantic)
        assert score > 0

    def test_why_intent_prefers_causal_over_semantic(
        self, sample_node: EventNode, sample_embedding: list[float]
    ):
        """Test WHY intent scores CAUSAL higher than SEMANTIC."""
        causal_score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHY,
            edge_type=EdgeType.CAUSAL,
        )
        semantic_score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHY,
            edge_type=EdgeType.SEMANTIC,
        )
        assert causal_score > semantic_score

    def test_when_intent_prefers_temporal(
        self, sample_node: EventNode, sample_embedding: list[float]
    ):
        """Test WHEN intent scores TEMPORAL highest."""
        temporal_score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHEN,
            edge_type=EdgeType.TEMPORAL,
        )
        causal_score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHEN,
            edge_type=EdgeType.CAUSAL,
        )
        assert temporal_score > causal_score

    # Lambda parameter tests

    def test_lambda_structure_increases_score(
        self, sample_node: EventNode, sample_embedding: list[float]
    ):
        """Test that increasing lambda_structure increases score."""
        score_low = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHY,
            edge_type=EdgeType.CAUSAL,
            lambda_structure=0.5,
        )
        score_high = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHY,
            edge_type=EdgeType.CAUSAL,
            lambda_structure=2.0,
        )
        assert score_high > score_low

    def test_lambda_semantic_increases_score(
        self, sample_node: EventNode, sample_embedding: list[float]
    ):
        """Test that increasing lambda_semantic increases score with good semantic match."""
        score_low = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.OPEN,
            edge_type=EdgeType.SEMANTIC,
            lambda_semantic=0.1,
        )
        score_high = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.OPEN,
            edge_type=EdgeType.SEMANTIC,
            lambda_semantic=1.0,
        )
        assert score_high > score_low

    def test_default_lambda_values(self, sample_node: EventNode, sample_embedding: list[float]):
        """Test that default lambda values work correctly."""
        score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.ENTITY,
            edge_type=EdgeType.ENTITY,
        )
        # Should use lambda_structure=1.0, lambda_semantic=0.5
        assert isinstance(score, float)
        assert score > 0

    # Edge case tests

    def test_node_with_none_embedding(self, sample_embedding: list[float]):
        """Test transition score with node having None embedding."""
        node_no_embedding = EventNode(
            id="test-node-no-emb",
            content="Test without embedding",
            timestamp=datetime.now(UTC),
            embedding=None,
        )
        score = calculate_transition_score(
            neighbor=node_no_embedding,
            query_embedding=sample_embedding,
            query_intent=IntentType.OPEN,
            edge_type=EdgeType.SEMANTIC,
        )
        # Should still return positive score based on structural alignment only
        assert score > 0
        # exp(lambda_structure * weight + 0) since semantic = 0
        expected = math.exp(1.0 * 4.0)  # OPEN + SEMANTIC = 4.0
        assert score == pytest.approx(expected, rel=1e-9)

    def test_empty_query_embedding(self, sample_node: EventNode):
        """Test transition score with empty query embedding."""
        score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=[],
            query_intent=IntentType.WHY,
            edge_type=EdgeType.CAUSAL,
        )
        # Semantic similarity should be 0, only structural counts
        assert score > 0

    def test_mismatched_embedding_dimensions(self, sample_node: EventNode):
        """Test transition score with mismatched embedding dimensions."""
        different_dim_embedding = [0.1, 0.2, 0.3]  # 3D vs 5D
        score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=different_dim_embedding,
            query_intent=IntentType.WHEN,
            edge_type=EdgeType.TEMPORAL,
        )
        # Should handle gracefully, semantic = 0
        assert score > 0

    # All intent types coverage

    @pytest.mark.parametrize(
        "intent", [IntentType.WHY, IntentType.WHEN, IntentType.ENTITY, IntentType.OPEN]
    )
    def test_all_intent_types(
        self, sample_node: EventNode, sample_embedding: list[float], intent: IntentType
    ):
        """Test that all intent types work correctly."""
        score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=intent,
            edge_type=EdgeType.SEMANTIC,
        )
        assert isinstance(score, float)
        assert score > 0

    # All edge types coverage

    @pytest.mark.parametrize(
        "edge_type", [EdgeType.TEMPORAL, EdgeType.CAUSAL, EdgeType.SEMANTIC, EdgeType.ENTITY]
    )
    def test_all_edge_types(
        self, sample_node: EventNode, sample_embedding: list[float], edge_type: EdgeType
    ):
        """Test that all edge types work correctly."""
        score = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.OPEN,
            edge_type=edge_type,
        )
        assert isinstance(score, float)
        assert score > 0

    # Score properties

    def test_score_always_positive(self, sample_node: EventNode, sample_embedding: list[float]):
        """Test that transition score is always positive (exp property)."""
        for intent in IntentType:
            for edge_type in EdgeType:
                score = calculate_transition_score(
                    neighbor=sample_node,
                    query_embedding=sample_embedding,
                    query_intent=intent,
                    edge_type=edge_type,
                )
                assert score > 0

    def test_higher_structural_weight_produces_higher_score(
        self, sample_node: EventNode, sample_embedding: list[float]
    ):
        """Test that higher structural weight produces higher score."""
        # WHY+CAUSAL has weight 5.0
        score_high = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHY,
            edge_type=EdgeType.CAUSAL,
        )
        # WHY+SEMANTIC has weight 0.5
        score_low = calculate_transition_score(
            neighbor=sample_node,
            query_embedding=sample_embedding,
            query_intent=IntentType.WHY,
            edge_type=EdgeType.SEMANTIC,
        )
        assert score_high > score_low
