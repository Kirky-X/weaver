# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for temporal_decay in knowledge module."""

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


class TestTemporalDecayConfig:
    """Tests for TemporalDecayConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TemporalDecayConfig()

        assert config.enabled is False
        assert config.half_life_days == 30.0

    def test_custom_config(self):
        """Test custom configuration values."""
        config = TemporalDecayConfig(
            enabled=True,
            half_life_days=60.0,
        )

        assert config.enabled is True
        assert config.half_life_days == 60.0


class TestCalculateDecayMultiplier:
    """Tests for calculate_decay_multiplier function."""

    def test_zero_age_returns_one(self):
        """Test that zero age returns multiplier of 1.0."""
        result = calculate_decay_multiplier(0.0, 30.0)
        assert result == 1.0

    def test_half_life_age_returns_half(self):
        """Test that age equal to half-life returns 0.5."""
        result = calculate_decay_multiplier(30.0, 30.0)
        assert result == pytest.approx(0.5, rel=0.01)

    def test_double_half_life_returns_quarter(self):
        """Test that age equal to 2x half-life returns 0.25."""
        result = calculate_decay_multiplier(60.0, 30.0)
        assert result == pytest.approx(0.25, rel=0.01)

    def test_negative_age_returns_one(self):
        """Test that negative age returns 1.0 (no decay)."""
        result = calculate_decay_multiplier(-10.0, 30.0)
        assert result == 1.0

    def test_zero_half_life_returns_one(self):
        """Test that zero half-life returns 1.0 (no decay)."""
        result = calculate_decay_multiplier(30.0, 0.0)
        assert result == 1.0

    def test_negative_half_life_returns_one(self):
        """Test that negative half-life returns 1.0 (no decay)."""
        result = calculate_decay_multiplier(30.0, -10.0)
        assert result == 1.0

    def test_infinity_half_life_returns_one(self):
        """Test that infinity half-life returns 1.0."""
        result = calculate_decay_multiplier(30.0, math.inf)
        assert result == 1.0

    def test_infinity_age_returns_one(self):
        """Test that infinity age returns 1.0."""
        result = calculate_decay_multiplier(math.inf, 30.0)
        assert result == 1.0

    def test_custom_half_life(self):
        """Test decay with custom half-life."""
        # With half-life of 60 days, 60-day old doc should have 0.5 multiplier
        result = calculate_decay_multiplier(60.0, 60.0)
        assert result == pytest.approx(0.5, rel=0.01)

    def test_older_document_lower_multiplier(self):
        """Test that older documents have lower multipliers."""
        result_30_days = calculate_decay_multiplier(30.0, 30.0)
        result_60_days = calculate_decay_multiplier(60.0, 30.0)

        assert result_60_days < result_30_days


class TestApplyTemporalDecay:
    """Tests for apply_temporal_decay function."""

    def test_apply_decay_to_score(self):
        """Test applying decay to a score."""
        # With half-life of 30 days and age of 30 days, multiplier is 0.5
        result = apply_temporal_decay(1.0, 30.0, 30.0)
        assert result == pytest.approx(0.5, rel=0.01)

    def test_apply_decay_zero_age(self):
        """Test that zero age doesn't modify score."""
        result = apply_temporal_decay(0.8, 0.0, 30.0)
        assert result == 0.8

    def test_apply_decay_high_score(self):
        """Test decay applied to high score."""
        result = apply_temporal_decay(2.0, 30.0, 30.0)
        assert result == pytest.approx(1.0, rel=0.01)

    def test_apply_decay_preserves_zero(self):
        """Test that zero score remains zero."""
        result = apply_temporal_decay(0.0, 30.0, 30.0)
        assert result == 0.0


class TestCalculateAgeInDays:
    """Tests for calculate_age_in_days function."""

    def test_none_timestamp_returns_zero(self):
        """Test that None timestamp returns 0.0."""
        result = calculate_age_in_days(None)
        assert result == 0.0

    def test_recent_timestamp(self):
        """Test age calculation for recent timestamp."""
        now = datetime.now(UTC)
        timestamp = now - timedelta(hours=24)  # 1 day ago

        result = calculate_age_in_days(timestamp, now)
        assert result == pytest.approx(1.0, rel=0.01)

    def test_week_old_timestamp(self):
        """Test age calculation for week-old timestamp."""
        now = datetime.now(UTC)
        timestamp = now - timedelta(days=7)

        result = calculate_age_in_days(timestamp, now)
        assert result == pytest.approx(7.0, rel=0.01)

    def test_future_timestamp_returns_zero(self):
        """Test that future timestamp returns 0.0."""
        now = datetime.now(UTC)
        future = now + timedelta(days=10)

        result = calculate_age_in_days(future, now)
        assert result == 0.0

    def test_custom_now_parameter(self):
        """Test with custom 'now' parameter."""
        now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        timestamp = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)  # 5 days before

        result = calculate_age_in_days(timestamp, now)
        assert result == 5.0

    def test_fractional_days(self):
        """Test age calculation with fractional days."""
        now = datetime.now(UTC)
        timestamp = now - timedelta(hours=12)  # 0.5 days ago

        result = calculate_age_in_days(timestamp, now)
        assert result == pytest.approx(0.5, rel=0.01)

    def test_default_now_uses_utc(self):
        """Test that default 'now' uses UTC."""
        timestamp = datetime.now(UTC) - timedelta(days=1)

        result = calculate_age_in_days(timestamp)
        # Should be approximately 1 day, not throw an error
        assert result == pytest.approx(1.0, rel=0.1)
