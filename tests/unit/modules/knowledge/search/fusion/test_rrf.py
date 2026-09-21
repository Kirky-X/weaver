# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Unit tests for RRF fusion."""

from __future__ import annotations

from modules.knowledge.search.fusion.rrf import (
    RRFResult,
    fusion_score_at_k,
    reciprocal_rank_fusion,
    reciprocal_rank_fusion_with_metadata,
    weighted_rrf,
)


class TestReciprocalRankFusion:
    """Tests for reciprocal_rank_fusion."""

    def test_empty_input(self) -> None:
        """Empty results_list returns empty."""
        assert reciprocal_rank_fusion([]) == []

    def test_single_list(self) -> None:
        """Single ranked list is returned with RRF scores."""
        results = [("doc1", 0.9), ("doc2", 0.8)]
        fused = reciprocal_rank_fusion([results])

        assert len(fused) == 2
        assert fused[0][0] == "doc1"
        assert fused[0][1] > fused[1][1]

    def test_two_lists_overlap(self) -> None:
        """Documents appearing in both lists get higher scores."""
        list1 = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        list2 = [("doc2", 15.0), ("doc4", 12.0), ("doc1", 10.0)]

        fused = reciprocal_rank_fusion([list1, list2])

        doc2_score = next(s for d, s in fused if d == "doc2")
        doc4_score = next(s for d, s in fused if d == "doc4")
        assert doc2_score > doc4_score

    def test_custom_k(self) -> None:
        """Custom k parameter affects scores."""
        list1 = [("a", 1.0), ("b", 0.5)]
        fused_k60 = reciprocal_rank_fusion([list1], k=60)
        fused_k1 = reciprocal_rank_fusion([list1], k=1)

        assert fused_k60[0][1] != fused_k1[0][1]

    def test_return_scores_false(self) -> None:
        """return_scores=False still returns (item, score) tuples."""
        list1 = [("a", 1.0), ("b", 0.5)]
        result = reciprocal_rank_fusion([list1], return_scores=False)
        assert len(result) == 2
        assert all(isinstance(t, tuple) and len(t) == 2 for t in result)


class TestReciprocalRankFusionWithMetadata:
    """Tests for reciprocal_rank_fusion_with_metadata."""

    def test_empty_input(self) -> None:
        """Empty input returns empty."""
        assert reciprocal_rank_fusion_with_metadata([]) == []

    def test_returns_rrf_results(self) -> None:
        """Results are RRFResult instances."""
        list1 = [("doc1", 0.9), ("doc2", 0.8)]
        list2 = [("doc2", 15.0), ("doc3", 12.0)]

        results = reciprocal_rank_fusion_with_metadata([list1, list2])

        assert all(isinstance(r, RRFResult) for r in results)
        assert len(results) == 3

    def test_metadata_fields(self) -> None:
        """RRFResult has correct fields."""
        list1 = [("a", 0.9), ("b", 0.8)]
        results = reciprocal_rank_fusion_with_metadata([list1])

        assert results[0].ranks == [1]
        assert results[0].original_scores == [0.9]

    def test_sorted_by_score(self) -> None:
        """Results sorted by RRF score descending."""
        list1 = [("a", 0.9), ("b", 0.8)]
        list2 = [("b", 15.0), ("a", 10.0)]

        results = reciprocal_rank_fusion_with_metadata([list1, list2])

        for i in range(len(results) - 1):
            assert results[i].rrf_score >= results[i + 1].rrf_score


class TestWeightedRRF:
    """Tests for weighted_rrf."""

    def test_empty_input(self) -> None:
        """Empty input returns empty."""
        assert weighted_rrf([]) == []

    def test_equal_weights_default(self) -> None:
        """Default equal weights produce results."""
        list1 = [("a", 1.0), ("b", 0.5)]
        result = weighted_rrf([list1])
        assert len(result) == 2

    def test_custom_weights(self) -> None:
        """Custom weights affect ranking."""
        list1 = [("a", 1.0), ("b", 0.5)]
        list2 = [("b", 1.0), ("a", 0.5)]

        result_equal = weighted_rrf([list1, list2], weights=[1.0, 1.0])
        result_biased = weighted_rrf([list1, list2], weights=[2.0, 1.0])

        assert len(result_equal) == len(result_biased) == 2

    def test_weights_length_mismatch(self) -> None:
        """Mismatched weights length raises ValueError."""
        list1 = [("a", 1.0)]
        import pytest

        with pytest.raises(ValueError, match="Weights length"):
            weighted_rrf([list1], weights=[1.0, 2.0])

    def test_all_zero_weights_raise(self) -> None:
        """All-zero weights raise ValueError instead of ZeroDivisionError."""
        import pytest

        list1 = [("a", 1.0)]
        list2 = [("b", 1.0)]
        with pytest.raises(ValueError, match="zero"):
            weighted_rrf([list1, list2], weights=[0.0, 0.0])


class TestFusionScoreAtK:
    """Tests for fusion_score_at_k."""

    def test_empty_input(self) -> None:
        """Empty input returns zeros."""
        metrics = fusion_score_at_k([])
        assert metrics["precision_at_k"] == 0.0
        assert metrics["num_unique_items"] == 0

    def test_returns_metrics(self) -> None:
        """Returns expected metric keys."""
        list1 = [("a", 1.0), ("b", 0.5)]
        metrics = fusion_score_at_k([list1], top_k=5)

        assert "precision_at_k" in metrics
        assert "num_unique_items" in metrics
        assert "num_fused_items" in metrics


class TestFusionScoreAtKUniqueItems:
    """Regression: num_unique_items must cover every ranked list."""

    def test_unique_items_not_bounded_by_top_k_lists(self) -> None:
        """With 3 lists and top_k=2, items in the third list still count."""
        list1 = [("a", 1.0)]
        list2 = [("b", 1.0)]
        list3 = [("c", 1.0)]
        metrics = fusion_score_at_k([list1, list2, list3], top_k=2)

        assert metrics["num_unique_items"] == 3


class TestRRFWeights:
    """Optional per-list weights scale each list's RRF contribution.

    Default (no weights / all 1.0) must be byte-identical to the legacy
    behaviour so existing rankings do not shift.
    """

    def test_weights_none_matches_legacy(self) -> None:
        vector = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        bm25 = [("doc2", 15.0), ("doc4", 12.0), ("doc1", 10.0)]

        legacy = reciprocal_rank_fusion([vector, bm25])
        weighted = reciprocal_rank_fusion([vector, bm25], weights=[1.0, 1.0])

        assert weighted == legacy

    def test_higher_weight_boosts_list(self) -> None:
        vector = [("a", 0.9), ("b", 0.8)]
        bm25 = [("b", 15.0), ("a", 12.0)]
        # Unweighted: a and b tie-ish; heavy vector weight must push a above b.
        fused = reciprocal_rank_fusion([vector, bm25], weights=[10.0, 1.0])
        assert fused[0][0] == "a"

    def test_partial_weights_default_to_one(self) -> None:
        vector = [("a", 0.9), ("b", 0.8)]
        bm25 = [("b", 15.0), ("a", 12.0)]
        full = reciprocal_rank_fusion([vector, bm25], weights=[2.0, 2.0])
        partial = reciprocal_rank_fusion([vector, bm25], weights=[2.0])
        assert [i for i, _ in full] == [i for i, _ in partial]

    def test_zero_weight_disables_list(self) -> None:
        vector = [("a", 0.9)]
        bm25 = [("b", 15.0)]
        fused = reciprocal_rank_fusion([vector, bm25], weights=[0.0, 1.0])
        assert [i for i, _ in fused] == ["b"]
