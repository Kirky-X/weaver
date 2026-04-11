# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Performance benchmarks for community detection algorithm."""

import time

import pytest

from modules.knowledge.graph.community.detector import CommunityDetector


@pytest.mark.performance
class TestEdgeListPerformance:
    """Performance benchmarks for edge list building."""

    def test_vectorized_vs_loop_small_dataset(self) -> None:
        """Compare vectorized vs loop for 1K edges."""
        # Generate synthetic edge data
        results = []
        for i in range(1000):
            source = f"Entity_{i % 100}"
            target = f"Entity_{(i + 1) % 100}"
            weight = 1.0 + (i % 10) * 0.1
            results.append(
                {
                    "source": source,
                    "target": target,
                    "weight": weight,
                }
            )

        # Vectorized approach (using pandas)
        import pandas as pd

        start_vectorized = time.perf_counter()
        df = pd.DataFrame(results)
        df["lo"] = df[["source", "target"]].min(axis=1)
        df["hi"] = df[["source", "target"]].max(axis=1)
        df = df.sort_values("weight", ascending=False)
        df = df.drop_duplicates(subset=["lo", "hi"], keep="first")
        edges_vectorized = list(
            zip(df["lo"].tolist(), df["hi"].tolist(), df["weight"].tolist(), strict=True)
        )
        time_vectorized = time.perf_counter() - start_vectorized

        # Loop approach
        start_loop = time.perf_counter()
        edge_map: dict[tuple[str, str], float] = {}
        for r in results:
            source = r["source"]
            target = r["target"]
            weight = r["weight"]
            lo, hi = sorted([source, target])
            key = (lo, hi)
            if key not in edge_map or weight > edge_map[key]:
                edge_map[key] = weight
        edges_loop = [(s, t, w) for (s, t), w in edge_map.items()]
        time_loop = time.perf_counter() - start_loop

        # Results should be identical
        assert len(edges_vectorized) == len(edges_loop)

        # Vectorized should complete in reasonable time (< 100ms for 1K edges)
        # Note: Pandas DataFrame creation overhead dominates for small datasets
        # Vectorization advantage becomes significant for >50K edges
        assert time_vectorized < 0.1, f"Vectorized too slow: {time_vectorized:.4f}s"

    def test_vectorized_vs_loop_medium_dataset(self) -> None:
        """Compare vectorized vs loop for 10K edges."""
        # Generate 10K synthetic edges
        results = []
        for i in range(10000):
            source = f"Entity_{i % 500}"
            target = f"Entity_{(i + 1) % 500}"
            weight = 1.0 + (i % 20) * 0.05
            results.append(
                {
                    "source": source,
                    "target": target,
                    "weight": weight,
                }
            )

        # Vectorized approach
        import pandas as pd

        start_vectorized = time.perf_counter()
        df = pd.DataFrame(results)
        df["lo"] = df[["source", "target"]].min(axis=1)
        df["hi"] = df[["source", "target"]].max(axis=1)
        df = df.sort_values("weight", ascending=False)
        df = df.drop_duplicates(subset=["lo", "hi"], keep="first")
        edges_vectorized = list(
            zip(df["lo"].tolist(), df["hi"].tolist(), df["weight"].tolist(), strict=True)
        )
        time_vectorized = time.perf_counter() - start_vectorized

        # Loop approach
        start_loop = time.perf_counter()
        edge_map: dict[tuple[str, str], float] = {}
        for r in results:
            source = r["source"]
            target = r["target"]
            weight = r["weight"]
            lo, hi = sorted([source, target])
            key = (lo, hi)
            if key not in edge_map or weight > edge_map[key]:
                edge_map[key] = weight
        edges_loop = [(s, t, w) for (s, t), w in edge_map.items()]
        time_loop = time.perf_counter() - start_loop

        # Results should be identical
        assert len(edges_vectorized) == len(edges_loop)

        # Both should complete in reasonable time (< 500ms for 10K edges)
        assert time_vectorized < 0.5, f"Vectorized too slow: {time_vectorized:.4f}s"
        assert time_loop < 0.5, f"Loop too slow: {time_loop:.4f}s"


@pytest.mark.performance
class TestLeidenPerformance:
    """Performance benchmarks for Leiden algorithm."""

    def test_lcc_filter_performance(self) -> None:
        """LCC filtering reduces graph size efficiently."""
        import igraph as ig

        # Create graph with multiple disconnected components
        g = ig.Graph()
        g.add_vertices(1000)

        # Main component (500 nodes)
        edges_main = [(i, i + 1) for i in range(499)]
        # Small islands (10 nodes each)
        edges_islands = [
            (500 + i * 10 + j, 500 + i * 10 + j + 1) for i in range(50) for j in range(9)
        ]

        g.add_edges(edges_main + edges_islands)

        start_lcc = time.perf_counter()
        components = g.connected_components()
        lcc = components.giant()
        time_lcc = time.perf_counter() - start_lcc

        print(f"LCC filter: {time_lcc:.4f}s, LCC size: {lcc.vcount()} vs original: {g.vcount()}")

        # LCC should be smaller than original
        assert lcc.vcount() < g.vcount()
        # LCC filter should be fast (< 10ms for 1000 nodes)
        assert time_lcc < 0.01

    def test_iterations_impact_on_quality(self) -> None:
        """More iterations improve modularity but increase time."""
        import igraph as ig
        import leidenalg

        # Create test graph
        g = ig.Graph.Erdos_Renyi(n=100, p=0.1)

        # 1 iteration
        start_1 = time.perf_counter()
        optimiser = leidenalg.Optimiser()
        partition_1 = leidenalg.ModularityVertexPartition(g)
        optimiser.optimise_partition(partition_1, n_iterations=1)
        time_1 = time.perf_counter() - start_1
        q_1 = partition_1.modularity

        # 10 iterations
        start_10 = time.perf_counter()
        optimiser_10 = leidenalg.Optimiser()
        partition_10 = leidenalg.ModularityVertexPartition(g)
        optimiser_10.optimise_partition(partition_10, n_iterations=10)
        time_10 = time.perf_counter() - start_10
        q_10 = partition_10.modularity

        print(
            f"1 iter: Q={q_1:.4f}, time={time_1:.4f}s | 10 iter: Q={q_10:.4f}, time={time_10:.4f}s"
        )

        # More iterations should improve modularity (or keep same)
        assert q_10 >= q_1 - 0.01  # Allow small variation

        # 10 iterations should take longer
        assert time_10 >= time_1


@pytest.mark.performance
class TestModularityPerformance:
    """Performance benchmarks for modularity calculation."""

    def test_modularity_100_communities(self) -> None:
        """Modularity calculation for 100 communities."""
        from modules.knowledge.graph.community.modularity import calculate_modularity

        # Generate 100 nodes, 10 communities
        edges = []
        partitions = {}

        for comm in range(10):
            for node in range(comm * 10, (comm + 1) * 10):
                partitions[f"Node_{node}"] = comm
                # Connect within community
                for other in range(comm * 10, node):
                    edges.append((f"Node_{other}", f"Node_{node}", 1.0))

        start = time.perf_counter()
        result = calculate_modularity(edges, partitions)
        elapsed = time.perf_counter() - start

        print(
            f"Modularity 100 nodes/10 communities: {elapsed:.4f}s, Q={result.graph_modularity:.4f}"
        )

        # Should complete in reasonable time
        assert elapsed < 0.05  # < 50ms for 100 nodes

        # Should return valid result
        assert result.component_count >= 1

    def test_weighted_modularity_performance(self) -> None:
        """Weighted modularity across components."""
        from modules.knowledge.graph.community.modularity import (
            _compute_weighted_modularity,
            _find_connected_components,
        )

        # Create 5 disconnected components
        edges = []
        partitions = {}

        for comp in range(5):
            for node in range(comp * 20, (comp + 1) * 20):
                partitions[f"Node_{node}"] = comp
                # Connect within component
                if node > comp * 20:
                    edges.append((f"Node_{node - 1}", f"Node_{node}", 1.0))

        components = _find_connected_components(edges)

        start = time.perf_counter()
        weighted_q = _compute_weighted_modularity(
            edges, partitions, components, min_component_size=10
        )
        elapsed = time.perf_counter() - start

        print(f"Weighted modularity 100 nodes/5 components: {elapsed:.4f}s, Q={weighted_q:.4f}")

        assert elapsed < 0.1  # Should be fast
