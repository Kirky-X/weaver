# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for search latency monitoring with P99 thresholds."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Mock setfit before any import that triggers transformers
sys.modules.setdefault("setfit", MagicMock())

from core.observability.metrics import MetricsCollector


class TestSearchLatencyHistogram:
    """Test search_latency_seconds Histogram."""

    def test_histogram_exists(self):
        assert hasattr(MetricsCollector, "search_latency_seconds")

    def test_histogram_has_mode_label(self):
        MetricsCollector.search_latency_seconds.labels(mode="hybrid").observe(0.1)
        MetricsCollector.search_latency_seconds.labels(mode="local").observe(0.05)
        MetricsCollector.search_latency_seconds.labels(mode="global").observe(0.2)
        MetricsCollector.search_latency_seconds.labels(mode="drift").observe(0.5)

    def test_observe_multiple_modes(self):
        for mode in ("hybrid", "local", "global", "drift"):
            MetricsCollector.search_latency_seconds.labels(mode=mode).observe(0.1)


class TestSearchPerformanceSettings:
    """Test SearchPerformanceSettings configuration."""

    def test_default_hybrid_p99_threshold(self):
        from config.subconfigs import SearchPerformanceSettings

        settings = SearchPerformanceSettings()
        assert settings.hybrid_p99_threshold_ms == 300

    def test_default_local_p99_threshold(self):
        from config.subconfigs import SearchPerformanceSettings

        settings = SearchPerformanceSettings()
        assert settings.local_p99_threshold_ms == 200

    def test_default_global_p99_threshold(self):
        from config.subconfigs import SearchPerformanceSettings

        settings = SearchPerformanceSettings()
        assert settings.global_p99_threshold_ms == 500

    def test_default_drift_p99_threshold(self):
        from config.subconfigs import SearchPerformanceSettings

        settings = SearchPerformanceSettings()
        assert settings.drift_p99_threshold_ms == 1000

    def test_custom_thresholds(self):
        from config.subconfigs import SearchPerformanceSettings

        settings = SearchPerformanceSettings(
            hybrid_p99_threshold_ms=400,
            local_p99_threshold_ms=150,
            global_p99_threshold_ms=600,
            drift_p99_threshold_ms=2000,
        )
        assert settings.hybrid_p99_threshold_ms == 400
        assert settings.local_p99_threshold_ms == 150
        assert settings.global_p99_threshold_ms == 600
        assert settings.drift_p99_threshold_ms == 2000

    def test_get_threshold_for_mode(self):
        from config.subconfigs import SearchPerformanceSettings

        settings = SearchPerformanceSettings()
        assert settings.get_threshold_ms("hybrid") == 300
        assert settings.get_threshold_ms("local") == 200
        assert settings.get_threshold_ms("global") == 500
        assert settings.get_threshold_ms("drift") == 1000

    def test_get_threshold_unknown_mode_defaults_hybrid(self):
        from config.subconfigs import SearchPerformanceSettings

        settings = SearchPerformanceSettings()
        assert settings.get_threshold_ms("unknown") == 300
