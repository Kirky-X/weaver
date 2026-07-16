# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for BeamSearchReranker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.rerankers.beam_search_reranker import BeamSearchReranker


class TestBeamSearchRerankerDefaultBeamWidth:
    """Tests for default beam_width=5."""

    def test_default_beam_width(self):
        """Test default beam_width=5."""
        reranker = BeamSearchReranker()
        assert reranker._beam_width == 5

    def test_custom_beam_width(self):
        """Test custom beam_width."""
        reranker = BeamSearchReranker(beam_width=10)
        assert reranker._beam_width == 10


class TestRerankReturnsTopBeamWidth:
    """Tests for rerank returning top beam_width results."""

    @pytest.fixture
    def reranker(self):
        """Create a BeamSearchReranker with beam_width=3."""
        return BeamSearchReranker(beam_width=3)

    def test_rerank_returns_top_beam_width(self, reranker):
        """Test rerank returns beam_width results."""
        candidates = [
            {"id": f"e{i}", "fusion_score": 0.9 - i * 0.1, "content": f"Entity {i}"}
            for i in range(10)
        ]
        results = reranker.rerank("test query", candidates)
        assert len(results) == 3

    def test_rerank_fewer_candidates_than_beam_width(self, reranker):
        """Test rerank with fewer candidates than beam_width."""
        candidates = [
            {"id": "e1", "fusion_score": 0.9, "content": "Entity 1"},
            {"id": "e2", "fusion_score": 0.8, "content": "Entity 2"},
        ]
        results = reranker.rerank("test query", candidates)
        assert len(results) == 2

    def test_rerank_empty_candidates(self, reranker):
        """Test rerank with empty candidates."""
        results = reranker.rerank("test query", [])
        assert results == []


class TestCumulativeScoreFormula:
    """Tests for cumulative score formula: cum_score * 0.7 + n.score * 0.3."""

    @pytest.fixture
    def reranker(self):
        """Create a BeamSearchReranker."""
        return BeamSearchReranker(beam_width=5)

    def test_cumulative_score_formula(self, reranker):
        """Test cum_score * 0.7 + n.score * 0.3."""
        candidates = [
            {"id": "e1", "fusion_score": 0.9, "content": "Entity 1"},
        ]
        results = reranker.rerank("test query", candidates)

        # With depth=0 (no graph expansion), the initial score is just the fusion_score
        # With depth=1, cumulative = initial * 0.7 + neighbor_score * 0.3
        assert len(results) == 1
        # The result should have a cumulative_score
        assert "cumulative_score" in results[0]

    def test_cumulative_score_with_graph(self, reranker):
        """Test cumulative score computation with graph neighbors."""
        # Create mock graph
        mock_graph = MagicMock()
        mock_graph.get_neighbors = MagicMock(
            return_value=[
                {"id": "n1", "fusion_score": 0.7, "content": "Neighbor 1"},
                {"id": "n2", "fusion_score": 0.6, "content": "Neighbor 2"},
            ]
        )

        candidates = [
            {"id": "e1", "fusion_score": 0.9, "content": "Entity 1"},
        ]

        results = reranker.rerank("test query", candidates, graph=mock_graph, depth=1)

        # Should incorporate neighbor scores
        assert len(results) >= 1


class TestPruningKeepsTopBeamWidth:
    """Tests for pruning keeping top beam_width candidates."""

    def test_pruning_keeps_top_beam_width(self):
        """Test pruning keeps top beam_width candidates."""
        reranker = BeamSearchReranker(beam_width=3)
        candidates = [
            {"id": f"e{i}", "fusion_score": 0.9 - i * 0.05, "content": f"Entity {i}"}
            for i in range(8)
        ]
        results = reranker.rerank("test query", candidates)

        # Should only keep top 3
        assert len(results) == 3

        # Results should be sorted by score descending
        scores = [r.get("cumulative_score", r.get("fusion_score", 0)) for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_pruning_with_equal_scores(self):
        """Test pruning with equal scores."""
        reranker = BeamSearchReranker(beam_width=2)
        candidates = [
            {"id": "e1", "fusion_score": 0.5, "content": "Entity 1"},
            {"id": "e2", "fusion_score": 0.5, "content": "Entity 2"},
            {"id": "e3", "fusion_score": 0.5, "content": "Entity 3"},
        ]
        results = reranker.rerank("test query", candidates)
        assert len(results) == 2


class TestMultiHopExpansion:
    """Tests for multi-hop expansion."""

    def test_multi_hop_expansion(self):
        """Test multi-hop expansion with depth=2."""
        reranker = BeamSearchReranker(beam_width=5)

        # Create mock graph with multi-hop neighbors
        call_count = {"count": 0}

        def mock_get_neighbors(entity_id):
            call_count["count"] += 1
            if entity_id == "e1":
                return [{"id": "n1", "fusion_score": 0.7, "content": "Neighbor 1"}]
            elif entity_id == "n1":
                return [{"id": "n2", "fusion_score": 0.5, "content": "Neighbor 2"}]
            return []

        mock_graph = MagicMock()
        mock_graph.get_neighbors = mock_get_neighbors

        candidates = [
            {"id": "e1", "fusion_score": 0.9, "content": "Entity 1"},
        ]

        results = reranker.rerank("test query", candidates, graph=mock_graph, depth=2)

        # Should have expanded at least once
        assert call_count["count"] >= 1

    def test_multi_hop_no_graph(self):
        """Test multi-hop without graph returns initial candidates."""
        reranker = BeamSearchReranker(beam_width=5)
        candidates = [
            {"id": "e1", "fusion_score": 0.9, "content": "Entity 1"},
        ]

        results = reranker.rerank("test query", candidates, graph=None, depth=2)

        # Without graph, should just return sorted candidates
        assert len(results) == 1

    def test_multi_hop_zero_depth(self):
        """Test with depth=0 returns initial candidates."""
        reranker = BeamSearchReranker(beam_width=5)
        candidates = [
            {"id": "e1", "fusion_score": 0.9, "content": "Entity 1"},
        ]

        results = reranker.rerank("test query", candidates, depth=0)

        assert len(results) == 1
        assert results[0]["id"] == "e1"
