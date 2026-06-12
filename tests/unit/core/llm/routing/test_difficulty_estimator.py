# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DifficultyEstimator: 4-factor difficulty scoring for LLM routing.

Covers:
- Short text <200 chars -> score < 0.3
- Long text >8000 chars -> score > 0.7
- Execution time < 1ms
- All four factors contribute to the score
"""

from __future__ import annotations

import time

import pytest

from core.llm.routing.difficulty_estimator import DifficultyEstimator


class TestDifficultyEstimatorBounds:
    """Guarantee that short/long text produce bounded scores."""

    def setup_method(self) -> None:
        self.estimator = DifficultyEstimator()

    def test_short_text_score_below_03(self) -> None:
        """Short text (<200 chars) should always produce score < 0.3."""
        short_text = "a" * 100  # 100 chars
        for cp in ["classifier", "categorizer", "analyze", "entity_extractor", "quality_scorer"]:
            score = self.estimator.estimate(cp, short_text)
            assert score < 0.3, f"call_point={cp}, score={score}"

    def test_short_text_with_entities_still_below_03(self) -> None:
        """Short text with high entity density should still be < 0.3."""
        short_text = "a" * 100
        score = self.estimator.estimate("entity_extractor", short_text, entity_count=50)
        assert score < 0.3, f"score={score}"

    def test_long_text_score_above_07(self) -> None:
        """Long text (>8000 chars) should always produce score > 0.7."""
        long_text = "a" * 9000
        for cp in ["classifier", "categorizer", "analyze", "entity_extractor", "quality_scorer"]:
            score = self.estimator.estimate(cp, long_text)
            assert score > 0.7, f"call_point={cp}, score={score}"

    def test_long_text_low_density_still_above_07(self) -> None:
        """Long text with zero entities should still be > 0.7."""
        long_text = "a" * 9000
        score = self.estimator.estimate("classifier", long_text, entity_count=0)
        assert score > 0.7, f"score={score}"


class TestDifficultyEstimatorFactors:
    """Verify that all four factors contribute to the score."""

    def setup_method(self) -> None:
        self.estimator = DifficultyEstimator()

    def test_length_factor_increases_with_text_length(self) -> None:
        """Longer text should produce higher difficulty score."""
        short = "a" * 100
        medium = "a" * 2000
        long_ = "a" * 9000
        score_s = self.estimator.estimate("classifier", short)
        score_m = self.estimator.estimate("classifier", medium)
        score_l = self.estimator.estimate("classifier", long_)
        assert score_s < score_m < score_l

    def test_entity_density_increases_score(self) -> None:
        """More entities per 1000 chars should increase difficulty."""
        text = "a" * 2000
        low = self.estimator.estimate("classifier", text, entity_count=1)
        high = self.estimator.estimate("classifier", text, entity_count=20)
        assert high > low

    def test_call_point_baseline_affects_score(self) -> None:
        """Higher baseline call_point should produce higher score."""
        text = "a" * 500
        classifier = self.estimator.estimate("classifier", text)
        entity_extractor = self.estimator.estimate("entity_extractor", text)
        assert entity_extractor > classifier

    def test_unknown_call_point_uses_default_baseline(self) -> None:
        """Unknown call_point should use default baseline (0.5)."""
        text = "a" * 500
        score = self.estimator.estimate("unknown_call_point", text)
        assert 0.0 <= score <= 1.0

    def test_score_always_in_0_1_range(self) -> None:
        """Score should always be in [0, 1] range."""
        for length in [0, 50, 200, 2000, 8000, 50000]:
            for cp in ["classifier", "entity_extractor", "unknown"]:
                for entities in [0, 5, 50]:
                    text = "a" * length
                    score = self.estimator.estimate(cp, text, entity_count=entities)
                    assert 0.0 <= score <= 1.0, f"length={length}, cp={cp}, entities={entities}"


class TestDifficultyEstimatorPerformance:
    """Verify execution time < 1ms."""

    def test_estimate_under_1ms(self) -> None:
        """estimate() should complete in < 1ms."""
        estimator = DifficultyEstimator()
        text = "这是一段测试文本。" * 100  # ~900 chars
        start = time.perf_counter()
        for _ in range(100):
            estimator.estimate("classifier", text, entity_count=5)
        elapsed = (time.perf_counter() - start) / 100
        assert elapsed < 0.001, f"Average time: {elapsed * 1000:.3f}ms"
