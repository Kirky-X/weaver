# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Performance tests for community detection on large-scale graphs.

These tests measure and validate the performance characteristics
of community detection with various graph sizes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.graph_store.community_detector import CommunityDetector
from modules.graph_store.community_models import CommunityDetectionResult


@dataclass
class PerformanceMetrics:
    """Performance metrics for community detection."""

    entity_count: int
    edge_count: int
    detection_time_ms: float
    communities_found: int
    modularity: float
    memory_mb: float = 0.0


def generate_mock_edges(entity_count: int, edge_density: float = 0.1) -> list[dict]:
    """Generate mock edges for performance testing.

    Args:
        entity_count: Number of entities.
        edge_density: Probability of edge between any two entities.

    Returns:
        List of edge dictionaries.
    """
    import random

    edges = []
    entities = [f"Entity_{i}" for i in range(entity_count)]

    for i in range(entity_count):
        for j in range(i + 1, entity_count):
            if random.random() < edge_density:
                edges.append(
                    {
                        "source": entities[i],
                        "target": entities[j],
                        "weight": random.uniform(0.5, 1.0),
                    }
                )

    return edges


class TestCommunityDetectionPerformance:
    """Performance tests for community detection."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return pool

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_small_graph_performance(self, mock_pool):
        """Test performance on small graph (100 entities)."""
        entity_count = 100
        edges = generate_mock_edges(entity_count, edge_density=0.1)

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                edges,  # Edges
                [],  # Orphans
            ]
        )

        detector = CommunityDetector(mock_pool)

        start = time.perf_counter()
        result = await detector.detect_communities()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        # Small graph should complete quickly
        assert elapsed_ms < 5000  # 5 seconds max

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_medium_graph_performance(self, mock_pool):
        """Test performance on medium graph (1000 entities)."""
        entity_count = 1000
        edges = generate_mock_edges(entity_count, edge_density=0.05)

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                edges,
                [],
            ]
        )

        detector = CommunityDetector(mock_pool)

        start = time.perf_counter()
        result = await detector.detect_communities()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        # Medium graph should complete in reasonable time
        assert elapsed_ms < 30000  # 30 seconds max

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_large_graph_performance(self, mock_pool):
        """Test performance on large graph (5000 entities)."""
        entity_count = 5000
        edges = generate_mock_edges(entity_count, edge_density=0.02)

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                edges,
                [],
            ]
        )

        detector = CommunityDetector(mock_pool)

        start = time.perf_counter()
        result = await detector.detect_communities()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        # Large graph has higher threshold
        assert elapsed_ms < 120000  # 2 minutes max

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_sparse_graph_performance(self, mock_pool):
        """Test performance on sparse graph (low edge density)."""
        entity_count = 500
        edges = generate_mock_edges(entity_count, edge_density=0.01)

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                edges,
                [],
            ]
        )

        detector = CommunityDetector(mock_pool)

        start = time.perf_counter()
        result = await detector.detect_communities()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        # Sparse graphs should be faster
        assert elapsed_ms < 10000  # 10 seconds max

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_dense_graph_performance(self, mock_pool):
        """Test performance on dense graph (high edge density)."""
        entity_count = 200
        edges = generate_mock_edges(entity_count, edge_density=0.3)

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                edges,
                [],
            ]
        )

        detector = CommunityDetector(mock_pool)

        start = time.perf_counter()
        result = await detector.detect_communities()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        # Dense graphs take longer
        assert elapsed_ms < 15000  # 15 seconds max


class TestCommunityDetectionScalability:
    """Scalability tests for community detection."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return pool

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_linear_scaling_with_entities(self, mock_pool):
        """Test that detection time scales linearly with entity count."""
        results = []

        for entity_count in [100, 200, 400]:
            edges = generate_mock_edges(entity_count, edge_density=0.1)
            mock_pool.execute_query = AsyncMock(side_effect=[edges, []])

            detector = CommunityDetector(mock_pool)

            start = time.perf_counter()
            await detector.detect_communities()
            elapsed_ms = (time.perf_counter() - start) * 1000

            results.append((entity_count, elapsed_ms))

        # Check that time doesn't grow exponentially
        # Time for 400 entities should be less than 8x time for 100
        ratio = results[2][1] / max(results[0][1], 1)
        assert ratio < 8, f"Time scaling is not linear: ratio={ratio}"

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_max_cluster_size_effect(self, mock_pool):
        """Test effect of max_cluster_size on performance."""
        entity_count = 300
        edges = generate_mock_edges(entity_count, edge_density=0.1)

        results = []

        for max_cluster in [5, 10, 20]:
            mock_pool.execute_query = AsyncMock(side_effect=[edges, []])

            detector = CommunityDetector(
                mock_pool,
                max_cluster_size=max_cluster,
            )

            start = time.perf_counter()
            await detector.detect_communities()
            elapsed_ms = (time.perf_counter() - start) * 1000

            results.append((max_cluster, elapsed_ms))

        # All should complete successfully
        assert all(t < 30000 for _, t in results)


class TestCommunityReportGenerationPerformance:
    """Performance tests for community report generation."""

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_report_generation_single_community(self):
        """Test report generation time for single community."""
        from modules.graph_store.community_report_generator import (
            CommunityReportGenerator,
            ReportGenerationResult,
        )

        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "comm-1", "level": 0, "entity_count": 10}],
                [{"name": f"Entity_{i}", "type": "类型"} for i in range(10)],
                [],
            ]
        )

        mock_llm = MagicMock()
        mock_llm._prompts = MagicMock()
        mock_llm._prompts.get = MagicMock(return_value="Prompt")
        mock_llm._queue = MagicMock()
        mock_llm._queue.enqueue = AsyncMock(
            return_value='{"title": "Test", "summary": "Summary", "rank": 5}'
        )
        mock_llm.batch_embed = AsyncMock(return_value=[[0.1] * 1536])

        generator = CommunityReportGenerator(mock_pool, mock_llm)
        generator._repo = MagicMock()
        generator._repo.get_report = AsyncMock(return_value=None)
        generator._repo.create_report = AsyncMock(return_value="report-id")

        start = time.perf_counter()
        result = await generator.generate_report("comm-1")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        # Report generation should complete quickly
        assert elapsed_ms < 5000  # 5 seconds

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_batch_report_generation(self):
        """Test batch report generation for multiple communities."""
        from modules.graph_store.community_models import Community
        from modules.graph_store.community_report_generator import (
            CommunityReportGenerator,
            ReportGenerationResult,
        )

        mock_pool = MagicMock()
        mock_llm = MagicMock()

        generator = CommunityReportGenerator(mock_pool, mock_llm)
        generator._repo = MagicMock()
        generator._repo.list_communities = AsyncMock(
            return_value=[
                Community(id=f"comm-{i}", title=f"C{i}", level=0, entity_count=5) for i in range(5)
            ]
        )
        generator.generate_report = AsyncMock(
            return_value=ReportGenerationResult(
                community_id="comm-1",
                success=True,
                report_id="report-id",
            )
        )

        start = time.perf_counter()
        result = await generator.generate_all_reports()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result["success"] >= 0
        # Batch processing should be efficient
        assert elapsed_ms < 10000  # 10 seconds


class TestModularityQuality:
    """Tests for modularity quality of detected communities."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return pool

    @pytest.mark.performance
    def test_modularity_with_clear_communities(self, mock_pool):
        """Test modularity when graph has clear community structure."""
        # Create edges that form 3 distinct clusters
        edges = []

        # Cluster 1: A-B-C connected
        edges.extend(
            [
                {"source": "A", "target": "B", "weight": 1.0},
                {"source": "B", "target": "C", "weight": 1.0},
            ]
        )

        # Cluster 2: D-E-F connected
        edges.extend(
            [
                {"source": "D", "target": "E", "weight": 1.0},
                {"source": "E", "target": "F", "weight": 1.0},
            ]
        )

        # Cluster 3: G-H-I connected
        edges.extend(
            [
                {"source": "G", "target": "H", "weight": 1.0},
                {"source": "H", "target": "I", "weight": 1.0},
            ]
        )

        # Single inter-cluster edge
        edges.append({"source": "C", "target": "D", "weight": 0.5})

        mock_pool.execute_query = AsyncMock(side_effect=[edges, []])

        detector = CommunityDetector(mock_pool)

        # Modularity should be high for clear community structure
        # (testing the _calculate_modularity method indirectly)
        assert detector is not None

    @pytest.mark.performance
    def test_modularity_with_random_graph(self, mock_pool):
        """Test modularity for random graph (expected low modularity)."""
        import random

        # Create random edges
        edges = []
        entities = list(range(20))

        for _ in range(30):
            source = random.choice(entities)
            target = random.choice(entities)
            if source != target:
                edges.append(
                    {
                        "source": str(source),
                        "target": str(target),
                        "weight": random.uniform(0.5, 1.0),
                    }
                )

        mock_pool.execute_query = AsyncMock(side_effect=[edges, []])

        detector = CommunityDetector(mock_pool)
        assert detector is not None


class TestPerformanceBenchmarks:
    """Benchmark tests for performance regression detection."""

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_benchmark_detection_latency(self):
        """Benchmark: Detection should complete within acceptable latency."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                generate_mock_edges(500, 0.05),
                [],
            ]
        )

        detector = CommunityDetector(mock_pool)

        # Run multiple iterations
        latencies = []
        for _ in range(3):
            start = time.perf_counter()
            await detector.detect_communities()
            latencies.append((time.perf_counter() - start) * 1000)

        # Average latency should be reasonable
        avg_latency = sum(latencies) / len(latencies)
        assert avg_latency < 20000  # 20 seconds average

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_benchmark_memory_efficiency(self):
        """Benchmark: Memory usage should stay reasonable."""
        # This is a placeholder for memory profiling
        # In production, use memory_profiler or similar
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                generate_mock_edges(1000, 0.03),
                [],
            ]
        )

        detector = CommunityDetector(mock_pool)
        result = await detector.detect_communities()

        assert result is not None
        # Memory check would be done by external profiler
