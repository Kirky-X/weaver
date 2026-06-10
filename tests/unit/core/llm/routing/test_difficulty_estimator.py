# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DifficultyEstimator: 4-factor difficulty scoring."""

from __future__ import annotations

import pytest

from core.llm.routing.difficulty_estimator import DifficultyEstimator


@pytest.fixture
def estimator() -> DifficultyEstimator:
    return DifficultyEstimator()


class TestLengthFactor:
    """Tests for the input-length factor."""

    def test_short_text_low_difficulty(self, estimator: DifficultyEstimator) -> None:
        """< 200 chars → length_factor ≈ 0.1."""
        text = "a" * 100
        score = estimator.estimate(text, call_point="classifier")
        # length_factor = 0.1, baseline=0.2, others default
        # We verify _length_factor directly
        assert estimator._length_factor(len(text)) == 0.1

    def test_medium_text_medium_difficulty(self, estimator: DifficultyEstimator) -> None:
        """200-2000 chars → length_factor ≈ 0.4."""
        text = "a" * 500
        assert estimator._length_factor(len(text)) == 0.4

    def test_long_text_high_difficulty(self, estimator: DifficultyEstimator) -> None:
        """> 8000 chars → length_factor ≈ 0.9."""
        text = "a" * 10000
        assert estimator._length_factor(len(text)) == 0.9


class TestDensityFactor:
    """Tests for the entity-density factor."""

    def test_low_entity_density_low_difficulty(self, estimator: DifficultyEstimator) -> None:
        """< 1 per 1000 chars → density_factor ≈ 0.1."""
        # 2000 chars, 1 entity → 0.5 per 1000
        assert estimator._density_factor(entity_count=1, char_count=2000) == 0.1

    def test_high_entity_density_high_difficulty(self, estimator: DifficultyEstimator) -> None:
        """> 5 per 1000 chars → density_factor ≈ 0.7."""
        # 1000 chars, 6 entities → 6 per 1000
        assert estimator._density_factor(entity_count=6, char_count=1000) == 0.7


class TestComplexityFactor:
    """Tests for the language-complexity factor."""

    def test_short_sentences_low_difficulty(self, estimator: DifficultyEstimator) -> None:
        """avg sentence length < 50 → complexity_factor ≈ 0.1."""
        # Each sentence ~20 chars
        text = "短句子内容。短句子内容。短句子内容。"
        assert estimator._complexity_factor(text) == 0.1


class TestCallPointBaseline:
    """Tests for the call-point baseline factor."""

    def test_call_point_baseline(self, estimator: DifficultyEstimator) -> None:
        """classifier=0.2, analyze=0.6, entity_extractor=0.7."""
        assert estimator.CALL_POINT_BASELINES["classifier"] == 0.2
        assert estimator.CALL_POINT_BASELINES["analyze"] == 0.6
        assert estimator.CALL_POINT_BASELINES["entity_extractor"] == 0.7


class TestFinalScore:
    """Tests for the final aggregated difficulty score."""

    def test_final_score_is_average_of_factors(self, estimator: DifficultyEstimator) -> None:
        """4 factors averaged to produce final score."""
        # Construct a text where we know all 4 factors:
        # length=100 → length_factor=0.1
        # entity_count=0, char_count=100 → density: 0/(0.1)=0 → per_k=0 < 1 → 0.1
        # text with short sentences → complexity=0.1
        # call_point="classifier" → baseline=0.2
        # Expected: (0.1 + 0.1 + 0.1 + 0.2) / 4 = 0.125
        text = "短。短。短。短。短。短。短。短。短。短。"  # ~30 chars, short sentences
        # Pad to exactly 100 chars
        text = text + "a" * (100 - len(text))
        score = estimator.estimate(text, call_point="classifier", entity_count=0)
        expected = (0.1 + 0.1 + 0.1 + 0.2) / 4.0
        assert abs(score - expected) < 0.01
