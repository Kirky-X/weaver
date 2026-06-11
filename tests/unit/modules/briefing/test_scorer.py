# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for BriefingScorer — five-dimensional weighted scoring."""

from __future__ import annotations

import math

import pytest

from modules.briefing.scorer import BRIEFING_WEIGHTS, BriefingScorer


class TestBriefingWeights:
    """Tests for five-dimensional BRIEFING_WEIGHTS."""

    def test_weights_sum_to_one(self):
        """Test that weights sum to approximately 1.0."""
        weight_sum = sum(BRIEFING_WEIGHTS.values())
        assert abs(weight_sum - 1.0) < 0.001

    def test_quality_weight(self):
        """Test quality weight is 0.30."""
        assert BRIEFING_WEIGHTS["quality"] == 0.30

    def test_cross_reference_weight(self):
        """Test cross_reference weight is 0.20."""
        assert BRIEFING_WEIGHTS["cross_reference"] == 0.20

    def test_novelty_weight(self):
        """Test novelty weight is 0.20."""
        assert BRIEFING_WEIGHTS["novelty"] == 0.20

    def test_user_preference_weight(self):
        """Test user_preference weight is 0.15."""
        assert BRIEFING_WEIGHTS["user_preference"] == 0.15

    def test_composite_weight(self):
        """Test composite weight is 0.15."""
        assert BRIEFING_WEIGHTS["composite"] == 0.15

    def test_exactly_five_dimensions(self):
        """Test there are exactly five scoring dimensions."""
        assert len(BRIEFING_WEIGHTS) == 5

    def test_dimension_names(self):
        """Test the five dimension names match spec."""
        expected = {"quality", "cross_reference", "novelty", "user_preference", "composite"}
        assert set(BRIEFING_WEIGHTS.keys()) == expected


class TestBriefingScorerScore:
    """Tests for BriefingScorer.score method."""

    def test_score_returns_float(self):
        """Test score returns a composite float as first element of tuple."""
        article = {}
        result = BriefingScorer.score(article)
        assert isinstance(result, tuple)
        composite, breakdown = result
        assert isinstance(composite, float)

    def test_score_returns_breakdown(self):
        """Test score returns a tuple of (composite, breakdown_dict)."""
        article = {"quality_score": 0.8}
        result = BriefingScorer.score(article)
        # score now returns (float, dict)
        assert isinstance(result, tuple)
        composite, breakdown = result
        assert isinstance(composite, float)
        assert isinstance(breakdown, dict)

    def test_score_breakdown_has_five_keys(self):
        """Test score_breakdown has all five dimension keys."""
        article = {}
        _, breakdown = BriefingScorer.score(article)
        expected_keys = {"quality", "cross_reference", "novelty", "user_preference", "composite"}
        assert set(breakdown.keys()) == expected_keys

    def test_score_breakdown_values_are_floats(self):
        """Test all breakdown values are floats between 0 and 1."""
        article = {"quality_score": 0.7}
        _, breakdown = BriefingScorer.score(article)
        for key, value in breakdown.items():
            assert isinstance(value, float), f"{key} is not float"
            assert 0.0 <= value <= 1.0, f"{key}={value} not in [0,1]"

    def test_score_composite_matches_weighted_sum(self):
        """Test composite score equals weighted sum of breakdown dimensions."""
        article = {"quality_score": 0.9}
        composite, breakdown = BriefingScorer.score(article)
        expected = (
            breakdown["quality"] * BRIEFING_WEIGHTS["quality"]
            + breakdown["cross_reference"] * BRIEFING_WEIGHTS["cross_reference"]
            + breakdown["novelty"] * BRIEFING_WEIGHTS["novelty"]
            + breakdown["user_preference"] * BRIEFING_WEIGHTS["user_preference"]
            + breakdown["composite"] * BRIEFING_WEIGHTS["composite"]
        )
        assert abs(composite - expected) < 0.001

    def test_score_default_values(self):
        """Test score with all default values."""
        article = {}
        composite, breakdown = BriefingScorer.score(article)
        assert 0.0 <= composite <= 1.0
        assert breakdown["quality"] == 0.5
        assert breakdown["cross_reference"] == 0.5
        assert breakdown["novelty"] == 0.5
        assert breakdown["user_preference"] == 0.5
        assert breakdown["composite"] == 0.5

    def test_score_high_quality(self):
        """Test score with high quality_score."""
        article = {"quality_score": 1.0}
        composite, breakdown = BriefingScorer.score(article)
        assert breakdown["quality"] == 1.0
        assert composite > 0.5

    def test_score_zero_quality(self):
        """Test score with zero quality_score."""
        article = {"quality_score": 0.0}
        composite, breakdown = BriefingScorer.score(article)
        assert breakdown["quality"] == 0.0

    def test_score_between_zero_and_one(self):
        """Test composite score is always between 0 and 1."""
        article = {"quality_score": 1.0, "score": 1.0, "credibility_score": 1.0}
        composite, _ = BriefingScorer.score(article)
        assert 0.0 <= composite <= 1.0


class TestCalcNovelty:
    """Tests for BriefingScorer._calc_novelty — embedding distance based."""

    def test_novelty_returns_float(self):
        """Test _calc_novelty returns a float."""
        article = {}
        result = BriefingScorer._calc_novelty(article)
        assert isinstance(result, float)

    def test_novelty_between_zero_and_one(self):
        """Test _calc_novelty returns value in [0, 1]."""
        article = {}
        result = BriefingScorer._calc_novelty(article)
        assert 0.0 <= result <= 1.0

    def test_novelty_default_without_embedding(self):
        """Test _calc_novelty returns 0.5 when no embedding data."""
        article = {}
        result = BriefingScorer._calc_novelty(article)
        assert result == 0.5

    def test_novelty_high_with_distant_embedding(self):
        """Test _calc_novelty returns high value for distant embeddings."""
        article = {
            "embedding": [1.0, 0.0, 0.0],
            "recent_embeddings": [[-1.0, 0.0, 0.0]],  # opposite direction
        }
        result = BriefingScorer._calc_novelty(article)
        assert result > 0.5  # distant from recent → more novel

    def test_novelty_low_with_similar_embedding(self):
        """Test _calc_novelty returns low value for similar embeddings."""
        article = {
            "embedding": [1.0, 0.0, 0.0],
            "recent_embeddings": [[0.99, 0.01, 0.0], [0.98, 0.02, 0.0]],
        }
        result = BriefingScorer._calc_novelty(article)
        assert result < 0.5  # similar to recent → less novel

    def test_novelty_with_empty_recent_embeddings(self):
        """Test _calc_novelty returns 0.5 when recent_embeddings is empty."""
        article = {"embedding": [1.0, 0.0, 0.0], "recent_embeddings": []}
        result = BriefingScorer._calc_novelty(article)
        assert result == 0.5

    def test_novelty_with_single_recent_embedding(self):
        """Test _calc_novelty works with a single recent embedding."""
        article = {
            "embedding": [1.0, 0.0],
            "recent_embeddings": [[0.0, 1.0]],
        }
        result = BriefingScorer._calc_novelty(article)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


class TestCalcUserPreference:
    """Tests for BriefingScorer._calc_user_preference — category history based."""

    def test_user_preference_returns_float(self):
        """Test _calc_user_preference returns a float."""
        article = {"category": "tech"}
        result = BriefingScorer._calc_user_preference(article)
        assert isinstance(result, float)

    def test_user_preference_between_zero_and_one(self):
        """Test _calc_user_preference returns value in [0, 1]."""
        article = {"category": "tech"}
        result = BriefingScorer._calc_user_preference(article)
        assert 0.0 <= result <= 1.0

    def test_user_preference_default_without_category(self):
        """Test _calc_user_preference returns 0.5 when no category."""
        article = {}
        result = BriefingScorer._calc_user_preference(article)
        assert result == 0.5

    def test_user_preference_high_for_preferred_category(self):
        """Test _calc_user_preference returns high value for frequently read category."""
        article = {
            "category": "tech",
            "category_history": {"tech": 50, "sports": 5, "politics": 2},
        }
        result = BriefingScorer._calc_user_preference(article)
        assert result > 0.5

    def test_user_preference_low_for_unpreferred_category(self):
        """Test _calc_user_preference returns low value for rarely read category."""
        article = {
            "category": "sports",
            "category_history": {"tech": 50, "politics": 30, "sports": 2},
        }
        result = BriefingScorer._calc_user_preference(article)
        assert result < 0.5

    def test_user_preference_with_empty_history(self):
        """Test _calc_user_preference returns 0.5 when no history."""
        article = {"category": "tech", "category_history": {}}
        result = BriefingScorer._calc_user_preference(article)
        assert result == 0.5

    def test_user_preference_with_no_history_key(self):
        """Test _calc_user_preference returns 0.5 when category_history key missing."""
        article = {"category": "tech"}
        result = BriefingScorer._calc_user_preference(article)
        assert result == 0.5


class TestCalcCrossReference:
    """Tests for BriefingScorer._calc_cross_reference."""

    def test_cross_reference_returns_float(self):
        """Test _calc_cross_reference returns a float."""
        article = {}
        result = BriefingScorer._calc_cross_reference(article)
        assert isinstance(result, float)

    def test_cross_reference_between_zero_and_one(self):
        """Test _calc_cross_reference returns value in [0, 1]."""
        article = {}
        result = BriefingScorer._calc_cross_reference(article)
        assert 0.0 <= result <= 1.0

    def test_cross_reference_default_without_data(self):
        """Test _calc_cross_reference returns 0.5 when no reference data."""
        article = {}
        result = BriefingScorer._calc_cross_reference(article)
        assert result == 0.5

    def test_cross_reference_high_with_many_references(self):
        """Test _calc_cross_reference returns high value for well-referenced article."""
        article = {"reference_count": 10, "max_references": 10}
        result = BriefingScorer._calc_cross_reference(article)
        assert result >= 0.8

    def test_cross_reference_low_with_no_references(self):
        """Test _calc_cross_reference returns low value for unreferenced article."""
        article = {"reference_count": 0, "max_references": 10}
        result = BriefingScorer._calc_cross_reference(article)
        assert result < 0.5


class TestCalcComposite:
    """Tests for BriefingScorer._calc_composite."""

    def test_composite_returns_float(self):
        """Test _calc_composite returns a float."""
        article = {}
        result = BriefingScorer._calc_composite(article)
        assert isinstance(result, float)

    def test_composite_between_zero_and_one(self):
        """Test _calc_composite returns value in [0, 1]."""
        article = {}
        result = BriefingScorer._calc_composite(article)
        assert 0.0 <= result <= 1.0

    def test_composite_default_without_data(self):
        """Test _calc_composite returns 0.5 when no composite data."""
        article = {}
        result = BriefingScorer._calc_composite(article)
        assert result == 0.5

    def test_composite_uses_score_and_credibility(self):
        """Test _calc_composite uses article score and credibility."""
        article = {"score": 1.0, "credibility_score": 1.0}
        result = BriefingScorer._calc_composite(article)
        assert result == 1.0

    def test_composite_zero_scores(self):
        """Test _calc_composite with zero scores."""
        article = {"score": 0.0, "credibility_score": 0.0}
        result = BriefingScorer._calc_composite(article)
        assert result == 0.0
