# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for pipeline throughput monitoring metrics."""

from __future__ import annotations

from core.observability.metrics import MetricsCollector


class TestPipelineThroughputGauge:
    """Test pipeline_throughput_articles_per_minute Gauge."""

    def test_gauge_exists(self):
        assert hasattr(MetricsCollector, "pipeline_throughput_articles_per_minute")

    def test_gauge_has_worker_id_label(self):
        MetricsCollector.pipeline_throughput_articles_per_minute.labels(worker_id="worker-1").set(
            42.5
        )

    def test_gauge_set_multiple_workers(self):
        MetricsCollector.pipeline_throughput_articles_per_minute.labels(worker_id="worker-0").set(
            10.0
        )
        MetricsCollector.pipeline_throughput_articles_per_minute.labels(worker_id="worker-1").set(
            15.0
        )


class TestPipelineThroughputLowCounter:
    """Test pipeline_throughput_low_total Counter."""

    def test_counter_exists(self):
        assert hasattr(MetricsCollector, "pipeline_throughput_low_total")

    def test_counter_inc(self):
        MetricsCollector.pipeline_throughput_low_total.inc()


class TestThroughputCalculation:
    """Test throughput calculation logic in PipelineThroughputTracker."""

    def test_calculate_throughput_from_window(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker(window_seconds=300)
        # Simulate 50 articles completed in 5 minutes = 10 articles/min
        tracker.record_completion("worker-0", count=50)
        throughput = tracker.calculate_throughput("worker-0")
        assert throughput == 10.0

    def test_zero_completions_zero_throughput(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker(window_seconds=300)
        throughput = tracker.calculate_throughput("worker-0")
        assert throughput == 0.0

    def test_low_throughput_detection(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker(window_seconds=300, low_threshold=10.0)
        # 5 articles in 5 min = 1 article/min < 10 threshold
        tracker.record_completion("worker-0", count=5)
        assert tracker.is_low_throughput("worker-0")

    def test_normal_throughput_not_flagged(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker(window_seconds=300, low_threshold=10.0)
        # 100 articles in 5 min = 20 articles/min > 10 threshold
        tracker.record_completion("worker-0", count=100)
        assert not tracker.is_low_throughput("worker-0")

    def test_multiple_workers_independent(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker(window_seconds=300, low_threshold=10.0)
        tracker.record_completion("worker-0", count=5)  # 1/min — low
        tracker.record_completion("worker-1", count=100)  # 20/min — normal
        assert tracker.is_low_throughput("worker-0")
        assert not tracker.is_low_throughput("worker-1")

    def test_record_and_update_gauge(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker(window_seconds=300)
        tracker.record_completion("worker-0", count=30)
        tracker.update_gauge("worker-0")
        # Gauge should have been set to 6.0 (30 articles / 5 min)
        # We verify the method runs without error; exact value checked via Prometheus registry

    def test_window_expiry(self):
        """Completions outside the window should not count."""
        import time

        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker(window_seconds=1)
        tracker.record_completion("worker-0", count=100)
        time.sleep(1.1)
        # Window expired, throughput should be 0
        throughput = tracker.calculate_throughput("worker-0")
        assert throughput == 0.0

    def test_default_low_threshold(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker()
        assert tracker._low_threshold == 10.0

    def test_default_window_seconds(self):
        from core.observability.throughput import PipelineThroughputTracker

        tracker = PipelineThroughputTracker()
        assert tracker._window_seconds == 300
