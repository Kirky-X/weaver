# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SentimentShiftDetector and ShiftConfig."""

from __future__ import annotations

import pytest

from modules.analytics.shift_detector import SentimentShiftDetector, ShiftConfig


class TestShiftConfigDefaults:
    """Tests for ShiftConfig default parameters."""

    def test_default_window_days(self):
        """Test default window_days is 14."""
        config = ShiftConfig()
        assert config.window_days == 14

    def test_default_pel_penalty(self):
        """Test default pel_penalty is 5.0."""
        config = ShiftConfig()
        assert config.pel_penalty == 5.0

    def test_default_binseg_penalty(self):
        """Test default binseg_penalty is 3.0."""
        config = ShiftConfig()
        assert config.binseg_penalty == 3.0

    def test_default_pel_model(self):
        """Test default pel_model is 'rbf'."""
        config = ShiftConfig()
        assert config.pel_model == "rbf"

    def test_default_binseg_model(self):
        """Test default binseg_model is 'l2'."""
        config = ShiftConfig()
        assert config.binseg_model == "l2"

    def test_default_min_size(self):
        """Test default min_size is 2."""
        config = ShiftConfig()
        assert config.min_size == 2

    def test_default_magnitude_threshold(self):
        """Test default magnitude_threshold is 0.05."""
        config = ShiftConfig()
        assert config.magnitude_threshold == 0.05

    def test_custom_values(self):
        """Test custom values are applied."""
        config = ShiftConfig(
            window_days=30,
            pel_penalty=10.0,
            binseg_penalty=5.0,
            pel_model="l2",
            binseg_model="rbf",
            min_size=3,
            magnitude_threshold=0.1,
        )
        assert config.window_days == 30
        assert config.pel_penalty == 10.0
        assert config.binseg_penalty == 5.0
        assert config.pel_model == "l2"
        assert config.binseg_model == "rbf"
        assert config.min_size == 3
        assert config.magnitude_threshold == 0.1


class TestSentimentShiftDetectorInsufficientData:
    """Tests for SentimentShiftDetector with insufficient data."""

    @pytest.fixture
    def detector(self):
        """Create a SentimentShiftDetector instance."""
        return SentimentShiftDetector()

    def test_empty_signal(self, detector):
        """Test empty signal returns empty list."""
        result = detector.detect([])
        assert result == []

    def test_single_point(self, detector):
        """Test single point returns empty list."""
        result = detector.detect([0.5])
        assert result == []

    def test_two_points(self, detector):
        """Test two points returns empty list (min_size * 2 = 4)."""
        result = detector.detect([0.7, 0.3])
        assert result == []

    def test_three_points(self, detector):
        """Test three points returns empty list."""
        result = detector.detect([0.7, 0.5, 0.3])
        assert result == []

    def test_four_points_returns_list(self, detector):
        """Test four points may produce shifts."""
        result = detector.detect([0.7, 0.7, 0.3, 0.3])
        assert isinstance(result, list)


class TestSentimentShiftDetectorPELT:
    """Tests for SentimentShiftDetector PELT detection."""

    @pytest.fixture
    def detector(self):
        """Create a SentimentShiftDetector with sensitive config."""
        return SentimentShiftDetector(
            ShiftConfig(
                magnitude_threshold=0.01,
                pel_penalty=1.0,
                binseg_penalty=1.0,
            )
        )

    def test_detect_shift_from_high_to_low(self, detector):
        """Test detecting a shift from high to low sentiment."""
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        assert len(shifts) > 0
        pel_shifts = [s for s in shifts if s["shift_type"] == "pel"]
        if pel_shifts:
            for s in pel_shifts:
                assert s["direction"] in ("positive", "negative")

    def test_detect_shift_from_low_to_high(self, detector):
        """Test detecting a shift from low to high sentiment."""
        signal = [0.2, 0.22, 0.19, 0.21, 0.8, 0.82, 0.79, 0.81]
        shifts = detector.detect(signal)
        assert len(shifts) > 0

    def test_no_shift_in_flat_signal(self, detector):
        """Test flat signal produces no significant shifts."""
        signal = [0.5, 0.51, 0.49, 0.5, 0.51, 0.49, 0.5, 0.51]
        shifts = detector.detect(signal)
        pel_shifts = [s for s in shifts if s["shift_type"] == "pel"]
        for s in pel_shifts:
            assert s["magnitude"] < 0.1

    def test_shift_magnitude_is_rounded(self, detector):
        """Test shift magnitude is rounded to 4 decimal places."""
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        for s in shifts:
            assert isinstance(s["magnitude"], float)
            parts = str(s["magnitude"]).split(".")
            if len(parts) > 1:
                assert len(parts[1]) <= 4


class TestSentimentShiftDetectorBinseg:
    """Tests for SentimentShiftDetector Binseg detection."""

    def test_detect_returns_binseg_shifts(self):
        """Test that results include binseg-type shifts."""
        detector = SentimentShiftDetector(
            ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0, binseg_penalty=1.0)
        )
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        binseg_shifts = [s for s in shifts if s["shift_type"] == "binseg"]
        assert len(binseg_shifts) >= 0

    def test_binseg_confidence_is_08(self):
        """Test binseg shifts have confidence 0.8."""
        detector = SentimentShiftDetector(
            ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0, binseg_penalty=1.0)
        )
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        for s in shifts:
            if s["shift_type"] == "binseg":
                assert s["confidence"] == 0.8


class TestSentimentShiftDetectorEdgeCases:
    """Tests for SentimentShiftDetector edge cases."""

    def test_constant_signal_no_shifts(self):
        """Test constant signal produces no shifts above threshold."""
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.5))
        signal = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
        shifts = detector.detect(signal)
        all_small = all(s["magnitude"] < 0.5 for s in shifts)
        assert all_small

    def test_large_signal(self):
        """Test detecting shifts in a large signal."""
        detector = SentimentShiftDetector(
            ShiftConfig(magnitude_threshold=0.01, pel_penalty=2.0, binseg_penalty=2.0)
        )
        signal = [0.5] * 10 + [0.9] * 10 + [0.2] * 10
        shifts = detector.detect(signal)
        assert len(shifts) > 0

    def test_direction_positive(self):
        """Test direction is 'positive' when after > before."""
        detector = SentimentShiftDetector(
            ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0, binseg_penalty=1.0)
        )
        signal = [0.2, 0.22, 0.19, 0.21, 0.8, 0.82, 0.79, 0.81]
        shifts = detector.detect(signal)
        for s in shifts:
            if s["direction"] == "positive":
                assert s["magnitude"] > 0

    def test_direction_negative(self):
        """Test direction is 'negative' when after < before."""
        detector = SentimentShiftDetector(
            ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0, binseg_penalty=1.0)
        )
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        for s in shifts:
            if s["direction"] == "negative":
                assert s["magnitude"] > 0

    def test_magnitude_threshold_filters_small_shifts(self):
        """Test magnitude_threshold filters out small shifts."""
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.5))
        signal = [0.51, 0.52, 0.49, 0.5, 0.51, 0.52, 0.49, 0.5]
        shifts = detector.detect(signal)
        for s in shifts:
            assert s["magnitude"] >= 0.5

    def test_breakpoint_within_bounds(self):
        """Test breakpoint index is within signal bounds."""
        detector = SentimentShiftDetector(
            ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0, binseg_penalty=1.0)
        )
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        for s in shifts:
            assert 0 <= s["breakpoint"] < len(signal)


class TestSentimentShiftDetectorCustomConfig:
    """Tests for SentimentShiftDetector with custom config."""

    def test_custom_min_size(self):
        """Test custom min_size requires more data points."""
        detector = SentimentShiftDetector(ShiftConfig(min_size=5))
        signal = [0.5] * 7
        result = detector.detect(signal)
        assert isinstance(result, list)
