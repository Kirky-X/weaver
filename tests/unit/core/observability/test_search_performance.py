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
