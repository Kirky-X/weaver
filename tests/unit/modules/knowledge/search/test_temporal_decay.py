# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for temporal decay functionality."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from modules.knowledge.search.temporal_decay import (
    TemporalDecayConfig,
    apply_temporal_decay,
    calculate_age_in_days,
    calculate_decay_multiplier,
)


class TestCalculateDecayMultiplier:
    """Tests for calculate_decay_multiplier function."""

    def test_zero_age_returns_one(self) -> None:
        """Zero age should return multiplier of 1.0."""
        assert calculate_decay_multiplier(0, 30) == 1.0

    def test_half_life_returns_half(self) -> None:
        """Age equal to half-life should return approximately 0.5."""
        result = calculate_decay_multiplier(30, 30)
        assert abs(result - 0.5) < 0.01

    def test_double_half_life_returns_quarter(self) -> None:
        """Age equal to 2x half-life should return approximately 0.25."""
        result = calculate_decay_multiplier(60, 30)
        assert abs(result - 0.25) < 0.01

    def test_quarter_half_life(self) -> None:
        """Age equal to 0.5x half-life should return approximately 0.707."""
        result = calculate_decay_multiplier(15, 30)
        expected = math.exp(-math.log(2) * 0.5)  # exp(-ln(2) * 0.5) ≈ 0.707
        assert abs(result - expected) < 0.01

    def test_negative_age_returns_one(self) -> None:
        """Negative age should be treated as zero and return 1.0."""
        assert calculate_decay_multiplier(-10, 30) == 1.0

    def test_zero_half_life_returns_one(self) -> None:
        """Zero half-life should disable decay and return 1.0."""
        assert calculate_decay_multiplier(100, 0) == 1.0

    def test_negative_half_life_returns_one(self) -> None:
        """Negative half-life should disable decay and return 1.0."""
        assert calculate_decay_multiplier(50, -30) == 1.0

    def test_infinite_age_returns_near_zero(self) -> None:
        """Very large age should approach zero but never reach it."""
        result = calculate_decay_multiplier(10000, 30)
        assert result > 0
        assert result < 0.001

    def test_small_half_life_decays_faster(self) -> None:
        """Smaller half-life should decay faster."""
        result_7_days = calculate_decay_multiplier(7, 7)
        result_30_days = calculate_decay_multiplier(7, 30)
        # 7 days with half-life of 7 days should decay more than with half-life of 30 days
        assert result_7_days < result_30_days


class TestApplyTemporalDecay:
    """Tests for apply_temporal_decay function."""

    def test_applies_multiplier_to_score(self) -> None:
        """Score should be multiplied by the decay multiplier."""
        # With half-life of 30 days and age of 30, multiplier should be ~0.5
        result = apply_temporal_decay(1.0, 30, 30)
        assert abs(result - 0.5) < 0.01

    def test_zero_age_no_change(self) -> None:
        """Zero age should not change the score."""
        assert apply_temporal_decay(0.8, 0, 30) == 0.8

    def test_preserves_score_proportion(self) -> None:
        """Decay should preserve score proportions."""
        result_1 = apply_temporal_decay(1.0, 30, 30)
        result_2 = apply_temporal_decay(2.0, 30, 30)
        # Both should be halved
        assert abs(result_1 - 0.5) < 0.01
        assert abs(result_2 - 1.0) < 0.01

    def test_zero_score_remains_zero(self) -> None:
        """Zero score should remain zero after decay."""
        assert apply_temporal_decay(0.0, 30, 30) == 0.0

    def test_disabled_decay_returns_original(self) -> None:
        """Disabled decay (zero half-life) should return original score."""
        assert apply_temporal_decay(0.75, 100, 0) == 0.75


class TestCalculateAgeInDays:
    """Tests for calculate_age_in_days function."""

    def test_returns_correct_age(self) -> None:
        """Should return correct age in days."""
        now = datetime.now(UTC)
        timestamp = now - timedelta(days=10)

        age = calculate_age_in_days(timestamp, now)
        assert abs(age - 10) < 0.01

    def test_none_timestamp_returns_zero(self) -> None:
        """None timestamp should return 0."""
        assert calculate_age_in_days(None, datetime.now(UTC)) == 0.0

    def test_future_timestamp_returns_zero(self) -> None:
        """Future timestamp should return 0 (clamped)."""
        now = datetime.now(UTC)
        future = now + timedelta(days=10)

        age = calculate_age_in_days(future, now)
        assert age == 0.0

    def test_fractional_days(self) -> None:
        """Should handle fractional days correctly."""
        now = datetime.now(UTC)
        timestamp = now - timedelta(hours=12)  # 0.5 days

        age = calculate_age_in_days(timestamp, now)
        assert abs(age - 0.5) < 0.01

    def test_uses_current_time_if_not_provided(self) -> None:
        """Should use current UTC time if 'now' is not provided."""
        timestamp = datetime.now(UTC) - timedelta(days=5)

        age = calculate_age_in_days(timestamp)
        # Should be approximately 5 days
        assert 4.9 < age < 5.1


class TestTemporalDecayConfig:
    """Tests for TemporalDecayConfig dataclass."""

    def test_default_values(self) -> None:
        """Default config should have decay disabled."""
        config = TemporalDecayConfig()
        assert config.enabled is False
        assert config.half_life_days == 30.0

    def test_custom_values(self) -> None:
        """Should accept custom values."""
        config = TemporalDecayConfig(enabled=True, half_life_days=7.0)
        assert config.enabled is True
        assert config.half_life_days == 7.0


class TestIntegration:
    """Integration tests for temporal decay workflow."""

    def test_full_decay_workflow(self) -> None:
        """Test the complete decay workflow."""
        now = datetime.now(UTC)

        # Create timestamps for documents of different ages
        doc1_time = now - timedelta(days=1)  # 1 day old
        doc2_time = now - timedelta(days=30)  # 30 days old
        doc3_time = now - timedelta(days=60)  # 60 days old

        half_life = 30.0

        # Calculate ages
        age1 = calculate_age_in_days(doc1_time, now)
        age2 = calculate_age_in_days(doc2_time, now)
        age3 = calculate_age_in_days(doc3_time, now)

        # Apply decay to scores
        original_score = 1.0
        score1 = apply_temporal_decay(original_score, age1, half_life)
        score2 = apply_temporal_decay(original_score, age2, half_life)
        score3 = apply_temporal_decay(original_score, age3, half_life)

        # Verify ordering: newer documents should have higher scores
        assert score1 > score2 > score3

        # Verify specific values
        assert score1 > 0.9  # 1-day old should have minimal decay
        assert abs(score2 - 0.5) < 0.01  # 30-day old should be ~0.5
        assert abs(score3 - 0.25) < 0.01  # 60-day old should be ~0.25
