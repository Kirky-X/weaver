# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline throughput tracking with sliding window and low-throughput alerts."""

from __future__ import annotations

import time
from collections import defaultdict

from core.observability.metrics import MetricsCollector


class PipelineThroughputTracker:
    """Track pipeline throughput using a sliding time window.

    Records article completion events per worker and calculates
    articles-per-minute throughput. Alerts when throughput drops
    below a configurable threshold.

    Args:
        window_seconds: Sliding window duration in seconds (default 300 = 5 min).
        low_threshold: Articles-per-minute threshold below which throughput
            is considered low (default 10.0).
    """

    def __init__(
        self,
        window_seconds: int = 300,
        low_threshold: float = 10.0,
    ) -> None:
        self._window_seconds = window_seconds
        self._low_threshold = low_threshold
        # worker_id -> list of (timestamp, count) tuples
        self._completions: dict[str, list[tuple[float, int]]] = defaultdict(list)

    def record_completion(self, worker_id: str, count: int = 1) -> None:
        """Record article completion events for a worker.

        Args:
            worker_id: Identifier for the pipeline worker.
            count: Number of articles completed in this event.
        """
        self._completions[worker_id].append((time.monotonic(), count))

    def calculate_throughput(self, worker_id: str) -> float:
        """Calculate articles-per-minute throughput for a worker.

        Uses a sliding window: only completions within the last
        ``window_seconds`` are counted.

        Args:
            worker_id: Identifier for the pipeline worker.

        Returns:
            Articles per minute throughput (0.0 if no completions in window).
        """
        now = time.monotonic()
        cutoff = now - self._window_seconds

        # Prune old entries and sum counts within window
        entries = self._completions.get(worker_id, [])
        recent = [(ts, cnt) for ts, cnt in entries if ts >= cutoff]
        self._completions[worker_id] = recent

        if not recent:
            return 0.0

        total_count = sum(cnt for _, cnt in recent)
        # articles_per_minute = total / (window_minutes)
        return total_count / (self._window_seconds / 60.0)

    def is_low_throughput(self, worker_id: str) -> bool:
        """Check if throughput for a worker is below the low threshold.

        Args:
            worker_id: Identifier for the pipeline worker.

        Returns:
            True if throughput is below the threshold.
        """
        return self.calculate_throughput(worker_id) < self._low_threshold

    def update_gauge(self, worker_id: str) -> None:
        """Calculate throughput and update the Prometheus Gauge.

        Also increments the low-throughput counter if below threshold.

        Args:
            worker_id: Identifier for the pipeline worker.
        """
        throughput = self.calculate_throughput(worker_id)
        MetricsCollector.pipeline_throughput_articles_per_minute.labels(worker_id=worker_id).set(
            throughput
        )

        if throughput > 0 and throughput < self._low_threshold:
            MetricsCollector.pipeline_throughput_low_total.inc()
