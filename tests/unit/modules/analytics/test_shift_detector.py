# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SentimentShiftDetector and ShiftConfig (PELT + CUSUM)."""

from __future__ import annotations

import pytest

from modules.analytics.shift_detector import SentimentShiftDetector, ShiftConfig


class TestShiftConfigDefaults:
    """Tests for ShiftConfig default parameters."""

    def test_default_window_days(self):
        config = ShiftConfig()
        assert config.window_days == 14

    def test_default_pel_penalty(self):
        config = ShiftConfig()
        assert config.pel_penalty == 5.0

    def test_default_pel_model(self):
        config = ShiftConfig()
        assert config.pel_model == "rbf"

    def test_default_min_size(self):
        config = ShiftConfig()
        assert config.min_size == 2

    def test_default_magnitude_threshold(self):
        config = ShiftConfig()
        assert config.magnitude_threshold == 0.05

    def test_default_cusum_threshold(self):
        config = ShiftConfig()
        assert config.cusum_threshold == 5.0

    def test_default_cusum_drift(self):
        config = ShiftConfig()
        assert config.cusum_drift == 0.0

    def test_default_cusum_min_observations(self):
        config = ShiftConfig()
        assert config.cusum_min_observations == 10

    def test_default_cooldown_hours(self):
        config = ShiftConfig()
        assert config.cooldown_hours == 24

    def test_no_binseg_params(self):
        """ShiftConfig should not have binseg-related parameters."""
        config = ShiftConfig()
        assert not hasattr(config, "binseg_penalty")
        assert not hasattr(config, "binseg_model")

    def test_custom_values(self):
        config = ShiftConfig(
            window_days=30,
            pel_penalty=10.0,
            pel_model="l2",
            min_size=3,
            magnitude_threshold=0.1,
            cusum_threshold=3.0,
            cusum_drift=0.5,
            cusum_min_observations=5,
            cooldown_hours=12,
        )
        assert config.window_days == 30
        assert config.pel_penalty == 10.0
        assert config.pel_model == "l2"
        assert config.min_size == 3
        assert config.magnitude_threshold == 0.1
        assert config.cusum_threshold == 3.0
        assert config.cusum_drift == 0.5
        assert config.cusum_min_observations == 5
        assert config.cooldown_hours == 12


class TestSentimentShiftDetectorInsufficientData:
    """Tests for SentimentShiftDetector with insufficient data."""

    @pytest.fixture
    def detector(self):
        return SentimentShiftDetector()

    def test_empty_signal(self, detector):
        result = detector.detect([])
        assert result == []

    def test_single_point(self, detector):
        result = detector.detect([0.5])
        assert result == []

    def test_two_points(self, detector):
        result = detector.detect([0.7, 0.3])
        assert result == []

    def test_three_points(self, detector):
        result = detector.detect([0.7, 0.5, 0.3])
        assert result == []

    def test_four_points_returns_list(self, detector):
        result = detector.detect([0.7, 0.7, 0.3, 0.3])
        assert isinstance(result, list)


class TestSentimentShiftDetectorPELT:
    """Tests for SentimentShiftDetector PELT detection."""

    @pytest.fixture
    def detector(self):
        return SentimentShiftDetector(
            ShiftConfig(
                magnitude_threshold=0.01,
                pel_penalty=1.0,
            )
        )

    def test_detect_shift_from_high_to_low(self, detector):
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        assert len(shifts) > 0
        pelt_shifts = [s for s in shifts if "pelt" in s.get("detection_method", "")]
        if pelt_shifts:
            for s in pelt_shifts:
                assert s["direction"] in ("positive", "negative")

    def test_detect_shift_from_low_to_high(self, detector):
        signal = [0.2, 0.22, 0.19, 0.21, 0.8, 0.82, 0.79, 0.81]
        shifts = detector.detect(signal)
        assert len(shifts) > 0

    def test_no_shift_in_flat_signal(self, detector):
        signal = [0.5, 0.51, 0.49, 0.5, 0.51, 0.49, 0.5, 0.51]
        shifts = detector.detect(signal)
        pelt_shifts = [s for s in shifts if "pelt" in s.get("detection_method", "")]
        for s in pelt_shifts:
            assert s["magnitude"] < 0.1

    def test_shift_magnitude_is_rounded(self, detector):
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        for s in shifts:
            assert isinstance(s["magnitude"], float)
            parts = str(s["magnitude"]).split(".")
            if len(parts) > 1:
                assert len(parts[1]) <= 4


class TestSentimentShiftDetectorCUSUM:
    """Tests for SentimentShiftDetector CUSUM detection."""

    def test_cusum_detects_gradual_increase(self):
        signal = [0.3 + i * 0.05 for i in range(20)]
        detector = SentimentShiftDetector(
            ShiftConfig(cusum_threshold=5.0, cusum_drift=0.0, cusum_min_observations=10)
        )
        shifts = detector.detect(signal)
        cusum_shifts = [s for s in shifts if "cusum" in s.get("detection_method", "")]
        assert len(cusum_shifts) > 0

    def test_cusum_no_false_positive_on_stable(self):
        signal = [
            0.5,
            0.52,
            0.48,
            0.51,
            0.49,
            0.5,
            0.48,
            0.52,
            0.5,
            0.49,
            0.51,
            0.5,
            0.48,
            0.52,
            0.5,
            0.49,
            0.51,
            0.5,
            0.48,
            0.52,
        ]
        detector = SentimentShiftDetector(
            ShiftConfig(cusum_threshold=5.0, cusum_drift=0.0, cusum_min_observations=10)
        )
        shifts = detector.detect(signal)
        cusum_shifts = [s for s in shifts if "cusum" in s.get("detection_method", "")]
        assert len(cusum_shifts) == 0


class TestSentimentShiftDetectorEdgeCases:
    """Tests for SentimentShiftDetector edge cases."""

    def test_constant_signal_no_shifts(self):
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.5))
        signal = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
        shifts = detector.detect(signal)
        all_small = all(s["magnitude"] < 0.5 for s in shifts)
        assert all_small

    def test_large_signal(self):
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.01, pel_penalty=2.0))
        signal = [0.5] * 10 + [0.9] * 10 + [0.2] * 10
        shifts = detector.detect(signal)
        assert len(shifts) > 0

    def test_direction_positive(self):
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0))
        signal = [0.2, 0.22, 0.19, 0.21, 0.8, 0.82, 0.79, 0.81]
        shifts = detector.detect(signal)
        for s in shifts:
            if s["direction"] == "positive":
                assert s["magnitude"] > 0

    def test_direction_negative(self):
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0))
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        for s in shifts:
            if s["direction"] == "negative":
                assert s["magnitude"] > 0

    def test_magnitude_threshold_filters_small_shifts(self):
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.5))
        signal = [0.51, 0.52, 0.49, 0.5, 0.51, 0.52, 0.49, 0.5]
        shifts = detector.detect(signal)
        for s in shifts:
            assert s["magnitude"] >= 0.5

    def test_breakpoint_within_bounds(self):
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0))
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        shifts = detector.detect(signal)
        for s in shifts:
            assert 0 <= s["breakpoint"] < len(signal)

    def test_no_binseg_in_results(self):
        """No shift should have shift_type 'binseg'."""
        signal = [0.8, 0.82, 0.79, 0.81, 0.3, 0.28, 0.32, 0.29]
        detector = SentimentShiftDetector(ShiftConfig(magnitude_threshold=0.01, pel_penalty=1.0))
        shifts = detector.detect(signal)
        binseg_shifts = [s for s in shifts if s.get("shift_type") == "binseg"]
        assert len(binseg_shifts) == 0


class TestSentimentShiftDetectorCustomConfig:
    """Tests for SentimentShiftDetector with custom config."""

    def test_custom_min_size(self):
        detector = SentimentShiftDetector(ShiftConfig(min_size=5))
        signal = [0.5] * 7
        result = detector.detect(signal)
        assert isinstance(result, list)
