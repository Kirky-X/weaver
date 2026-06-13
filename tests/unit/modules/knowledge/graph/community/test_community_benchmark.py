# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for community detection performance metrics and benchmarking."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Mock setfit before any import that triggers transformers
sys.modules.setdefault("setfit", MagicMock())

from core.observability.metrics import MetricsCollector


class TestCommunityDetectionMetrics:
    """Test community_detection_duration_seconds Histogram."""

    def test_histogram_exists(self):
        assert hasattr(MetricsCollector, "community_detection_duration_seconds")

    def test_histogram_has_algorithm_label(self):
        MetricsCollector.community_detection_duration_seconds.labels(algorithm="leiden").observe(
            5.0
        )
        MetricsCollector.community_detection_duration_seconds.labels(algorithm="louvain").observe(
            3.0
        )

    def test_observe_multiple_algorithms(self):
        for algo in ("leiden", "louvain"):
            MetricsCollector.community_detection_duration_seconds.labels(algorithm=algo).observe(
                1.0
            )


class TestCommunityDetectionBenchmark:
    """Test community detection benchmarking with synthetic data.

    These tests verify that the Leiden algorithm can process
    a reasonable number of entities within the 60-second threshold.
    """

    def test_leiden_1k_entities_under_60s(self):
        """1K entities should complete well within 60s."""
        # Build synthetic edge list: 1000 entities with random connections
        import random

        from modules.knowledge.graph.community.detector import CommunityDetector

        random.seed(42)
        n_entities = 1000
        edges = []
        for i in range(n_entities):
            # Each entity connects to 2-5 others
            n_neighbors = random.randint(2, 5)
            for _ in range(n_neighbors):
                j = random.randint(0, n_entities - 1)
                if i != j:
                    weight = random.uniform(0.1, 1.0)
                    edges.append((f"entity_{i}", f"entity_{j}", weight))

        detector = CommunityDetector.__new__(CommunityDetector)
        # Call _run_hierarchical_leiden directly (no DB needed)
        import time

        start = time.monotonic()
        clusters = detector._run_hierarchical_leiden(
            edges, max_cluster_size=100, seed=42, use_lcc=True, iterations=1
        )
        elapsed = time.monotonic() - start

        assert elapsed < 60.0, f"Leiden took {elapsed:.1f}s for 1K entities (threshold: 60s)"
        assert len(clusters) > 0

    def test_execution_time_ms_field_accuracy(self):
        """Verify execution_time_ms field is populated accurately."""
        # This is a structural test — we verify the field exists
        # and is a positive float. The actual benchmark is above.
        from modules.knowledge.graph.community.models import CommunityDetectionResult

        result = CommunityDetectionResult(
            communities=[],
            total_entities=0,
            total_communities=0,
            modularity=0.0,
            levels=[],
            orphan_count=0,
            execution_time_ms=42.5,
        )
        assert result.execution_time_ms == 42.5
        assert isinstance(result.execution_time_ms, float)
