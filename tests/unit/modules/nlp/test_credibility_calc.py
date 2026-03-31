# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for credibility calculation - updated for 3-signal algorithm."""

import pytest

from modules.processing.nodes.credibility_checker import CredibilityCheckerNode


class TestCredibilityWeights:
    """Tests for credibility weight configuration."""

    def test_category_weights_defined(self):
        """Test that category weights are defined."""
        assert hasattr(CredibilityCheckerNode, "CATEGORY_WEIGHTS")
        assert len(CredibilityCheckerNode.CATEGORY_WEIGHTS) > 0

    def test_default_weights_defined(self):
        """Test that default weights are defined."""
        assert hasattr(CredibilityCheckerNode, "DEFAULT_WEIGHTS")
        weights = CredibilityCheckerNode.DEFAULT_WEIGHTS
        assert "source" in weights
        assert "content" in weights
        assert "timeliness" in weights

    def test_all_category_weights_sum_to_one(self):
        """Test that all category weight configurations sum to 1.0."""
        for category, weights in CredibilityCheckerNode.CATEGORY_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.001, f"Weights for {category} don't sum to 1.0: {total}"

    def test_default_weights_sum_to_one(self):
        """Test that default weights sum to 1.0."""
        total = sum(CredibilityCheckerNode.DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_source_weight_percentage(self):
        """Test that source weight is within expected range."""
        for category, weights in CredibilityCheckerNode.CATEGORY_WEIGHTS.items():
            assert 0.0 <= weights["source"] <= 1.0, f"Source weight for {category} out of range"

    def test_content_weight_percentage(self):
        """Test that content weight is within expected range."""
        for category, weights in CredibilityCheckerNode.CATEGORY_WEIGHTS.items():
            assert 0.0 <= weights["content"] <= 1.0, f"Content weight for {category} out of range"

    def test_timeliness_weight_percentage(self):
        """Test that timeliness weight is within expected range."""
        for category, weights in CredibilityCheckerNode.CATEGORY_WEIGHTS.items():
            assert (
                0.0 <= weights["timeliness"] <= 1.0
            ), f"Timeliness weight for {category} out of range"


class TestCredibilityScoreRange:
    """Tests for credibility score range validation."""

    def test_score_minimum_zero(self):
        """Test that minimum possible score is 0.0."""
        # With all signals at 0, score should be 0
        weights = CredibilityCheckerNode.DEFAULT_WEIGHTS
        min_score = 0.0 * weights["source"] + 0.0 * weights["content"] + 0.0 * weights["timeliness"]
        assert min_score == 0.0

    def test_score_maximum_one(self):
        """Test that maximum possible score is 1.0."""
        # With all signals at 1, score should be 1
        weights = CredibilityCheckerNode.DEFAULT_WEIGHTS
        max_score = 1.0 * weights["source"] + 1.0 * weights["content"] + 1.0 * weights["timeliness"]
        assert abs(max_score - 1.0) < 0.001

    def test_score_range_zero_to_one(self):
        """Test that scores are always in [0, 1] range."""
        # Test with various signal combinations
        weights = CredibilityCheckerNode.DEFAULT_WEIGHTS
        for s1 in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for s2 in [0.0, 0.5, 1.0]:
                for s3 in [0.0, 0.5, 1.0]:
                    score = (
                        s1 * weights["source"]
                        + s2 * weights["content"]
                        + s3 * weights["timeliness"]
                    )
                    assert (
                        0.0 <= score <= 1.0
                    ), f"Score {score} out of range for signals {s1}, {s2}, {s3}"


class TestBreakingNewsWeights:
    """Tests for breaking news category weights."""

    def test_politics_prioritizes_timeliness(self):
        """Test that politics news prioritizes timeliness."""
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "政治", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["timeliness"] >= weights["source"]
        assert weights["timeliness"] >= weights["content"]

    def test_international_prioritizes_timeliness(self):
        """Test that international news prioritizes timeliness."""
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "国际", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["timeliness"] >= weights["source"]
        assert weights["timeliness"] >= weights["content"]

    def test_military_prioritizes_timeliness(self):
        """Test that military news prioritizes timeliness."""
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "军事", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["timeliness"] >= weights["source"]
        assert weights["timeliness"] >= weights["content"]


class TestEconomicWeights:
    """Tests for economic news category weights."""

    def test_economy_prioritizes_source(self):
        """Test that economic news prioritizes source authority."""
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "经济", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["source"] >= weights["content"]
        assert weights["source"] >= weights["timeliness"]


class TestTechWeights:
    """Tests for tech news category weights."""

    def test_tech_prioritizes_content(self):
        """Test that tech news prioritizes content quality."""
        weights = CredibilityCheckerNode.CATEGORY_WEIGHTS.get(
            "科技", CredibilityCheckerNode.DEFAULT_WEIGHTS
        )
        assert weights["content"] >= weights["source"]
        assert weights["content"] >= weights["timeliness"]
