# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for RRF (Reciprocal Rank Fusion) algorithm."""

from __future__ import annotations

import pytest

from modules.search.fusion.rrf import (
    RRFResult,
    fusion_score_at_k,
    reciprocal_rank_fusion,
    reciprocal_rank_fusion_with_metadata,
    weighted_rrf,
)


class TestReciprocalRankFusion:
    """Tests for reciprocal_rank_fusion function."""

    def test_basic_fusion(self) -> None:
        """Test basic RRF fusion."""
        vector_results = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        bm25_results = [("doc2", 15.0), ("doc4", 12.0), ("doc1", 10.0)]

        fused = reciprocal_rank_fusion([vector_results, bm25_results])

        assert len(fused) == 4  # 4 unique documents
        assert all(score > 0 for _, score in fused)

        # Documents appearing in both lists should rank higher
        doc_ids = [doc_id for doc_id, _ in fused]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids

    def test_fusion_empty_lists(self) -> None:
        """Test fusion with empty input."""
        result = reciprocal_rank_fusion([])
        assert result == []

    def test_fusion_single_list(self) -> None:
        """Test fusion with single list."""
        results = [("doc1", 0.9), ("doc2", 0.8)]
        fused = reciprocal_rank_fusion([results])

        assert len(fused) == 2
        # Order should be preserved for single list
        assert fused[0][0] == "doc1"
        assert fused[1][0] == "doc2"

    def test_fusion_custom_k(self) -> None:
        """Test fusion with custom k parameter."""
        vector_results = [("doc1", 0.9), ("doc2", 0.8)]
        bm25_results = [("doc2", 15.0), ("doc1", 10.0)]

        # Default k=60
        fused_default = reciprocal_rank_fusion([vector_results, bm25_results], k=60)

        # Different k value
        fused_custom = reciprocal_rank_fusion([vector_results, bm25_results], k=10)

        # Both should produce results but with different scores
        assert len(fused_default) == len(fused_custom)

    def test_fusion_same_document_higher_rank(self) -> None:
        """Test that documents appearing in multiple lists rank higher."""
        # doc1 appears at top of both lists
        list1 = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        list2 = [("doc1", 10.0), ("doc4", 8.0), ("doc5", 6.0)]

        fused = reciprocal_rank_fusion([list1, list2])

        # doc1 should be first because it's at top of both lists
        assert fused[0][0] == "doc1"

        # RRF score should be higher for doc1
        doc1_score = next(score for doc_id, score in fused if doc_id == "doc1")
        doc4_score = next(score for doc_id, score in fused if doc_id == "doc4")
        assert doc1_score > doc4_score


class TestRRFWithMetadata:
    """Tests for reciprocal_rank_fusion_with_metadata function."""

    def test_fusion_with_metadata(self) -> None:
        """Test RRF fusion returning metadata."""
        list1 = [("doc1", 0.9), ("doc2", 0.8)]
        list2 = [("doc2", 15.0), ("doc1", 10.0)]

        results = reciprocal_rank_fusion_with_metadata([list1, list2])

        assert len(results) == 2
        assert all(isinstance(r, RRFResult) for r in results)
        assert all(r.rrf_score > 0 for r in results)
        assert all(len(r.ranks) > 0 for r in results)

    def test_result_contains_ranks(self) -> None:
        """Test that results contain rank information."""
        list1 = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        list2 = [("doc2", 15.0), ("doc1", 10.0)]

        results = reciprocal_rank_fusion_with_metadata([list1, list2])

        doc1_result = next(r for r in results if r.item == "doc1")
        doc2_result = next(r for r in results if r.item == "doc2")

        # doc1 is rank 1 in list1, rank 2 in list2
        assert 1 in doc1_result.ranks
        assert 2 in doc1_result.ranks

        # doc2 is rank 2 in list1, rank 1 in list2
        assert 2 in doc2_result.ranks
        assert 1 in doc2_result.ranks


class TestWeightedRRF:
    """Tests for weighted_rrf function."""

    def test_equal_weights(self) -> None:
        """Test weighted RRF with equal weights (should be same as regular RRF)."""
        list1 = [("doc1", 0.9), ("doc2", 0.8)]
        list2 = [("doc2", 15.0), ("doc3", 10.0)]

        weighted = weighted_rrf([list1, list2], weights=[1.0, 1.0])
        regular = reciprocal_rank_fusion([list1, list2])

        # Same documents should appear
        weighted_ids = {doc_id for doc_id, _ in weighted}
        regular_ids = {doc_id for doc_id, _ in regular}
        assert weighted_ids == regular_ids

    def test_custom_weights(self) -> None:
        """Test weighted RRF with custom weights."""
        list1 = [("doc1", 0.9), ("doc2", 0.8)]
        list2 = [("doc3", 15.0), ("doc4", 10.0)]

        # Higher weight for first list
        weighted = weighted_rrf([list1, list2], weights=[2.0, 1.0])

        assert len(weighted) == 4

    def test_invalid_weights(self) -> None:
        """Test weighted RRF with invalid weights."""
        list1 = [("doc1", 0.9)]
        list2 = [("doc2", 15.0)]

        with pytest.raises(ValueError):
            weighted_rrf([list1, list2], weights=[1.0])  # Should have 2 weights

    def test_none_weights(self) -> None:
        """Test weighted RRF with None weights (should use equal weights)."""
        list1 = [("doc1", 0.9), ("doc2", 0.8)]
        list2 = [("doc2", 15.0), ("doc3", 10.0)]

        weighted = weighted_rrf([list1, list2], weights=None)

        assert len(weighted) == 3


class TestFusionScoreAtK:
    """Tests for fusion_score_at_k function."""

    def test_score_at_k(self) -> None:
        """Test quality metrics calculation."""
        list1 = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        list2 = [("doc2", 15.0), ("doc1", 10.0), ("doc4", 5.0)]

        metrics = fusion_score_at_k([list1, list2], top_k=3)

        assert "precision_at_k" in metrics
        assert "num_unique_items" in metrics
        assert "num_fused_items" in metrics
        assert metrics["num_fused_items"] == 4

    def test_empty_lists(self) -> None:
        """Test metrics with empty input."""
        metrics = fusion_score_at_k([])

        assert metrics["precision_at_k"] == 0.0
        assert metrics["num_unique_items"] == 0


class TestRRFFormula:
    """Tests verifying the RRF formula implementation."""

    def test_rrf_formula_calculation(self) -> None:
        """Test that RRF formula is correctly implemented.

        RRF_score(d) = Σ (1 / (k + rank_i(d)))

        For k=60:
        - doc1 at rank 1: 1/(60+1) = 1/61
        - doc1 at rank 2: 1/(60+2) = 1/62
        - Total for doc1: 1/61 + 1/62 ≈ 0.0325
        """
        list1 = [("doc1", 0.9)]  # doc1 at rank 1
        list2 = [("doc1", 10.0)]  # doc1 at rank 1

        fused = reciprocal_rank_fusion([list1, list2], k=60)

        # With k=60 and doc1 at rank 1 in both lists:
        # RRF = 1/61 + 1/61 = 2/61 ≈ 0.0328
        expected_score = 2 / 61

        assert len(fused) == 1
        assert fused[0][0] == "doc1"
        assert abs(fused[0][1] - expected_score) < 0.0001

    def test_different_ranks_different_scores(self) -> None:
        """Test that different ranks produce different scores."""
        # All documents appear once, at different ranks
        list1 = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7), ("doc4", 0.6)]

        fused = reciprocal_rank_fusion([list1], k=60)

        # Higher rank should have higher score
        scores = [score for _, score in fused]
        assert scores == sorted(scores, reverse=True)
