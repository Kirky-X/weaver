# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Leiden clustering algorithm."""

from modules.community.leiden import (
    GraphPartition,
    LeidenClustering,
)


class TestGraphPartition:
    """Test GraphPartition class."""

    def test_init(self):
        """Test GraphPartition initialization."""
        partition = GraphPartition()
        assert partition.nodes == set()
        assert partition.edges == []
        assert partition.total_weight == 0.0

    def test_add_edge(self):
        """Test adding edge to partition."""
        partition = GraphPartition()
        partition.add_edge("A", "B", 1.0)

        assert "A" in partition.nodes
        assert "B" in partition.nodes
        assert len(partition.edges) == 1
        assert partition.total_weight == 1.0

    def test_initialize_singleton_partition(self):
        """Test singleton partition initialization."""
        partition = GraphPartition()
        partition.add_edge("A", "B", 1.0)
        partition.add_edge("B", "C", 1.0)

        partition.initialize_singleton_partition()

        assert len(partition.node_to_community) == 3
        assert len(partition.community_to_nodes) == 3

    def test_get_node_degree(self):
        """Test node degree calculation."""
        partition = GraphPartition()
        partition.add_edge("A", "B", 1.0)
        partition.add_edge("A", "C", 2.0)

        degree = partition.get_node_degree("A")
        assert degree == 3.0

    def test_get_community_weight(self):
        """Test community weight calculation."""
        partition = GraphPartition()
        partition.add_edge("A", "B", 1.0)
        partition.add_edge("B", "C", 1.0)
        partition.initialize_singleton_partition()

        if partition.community_to_nodes:
            weight = partition.get_community_weight(0)
            assert weight >= 0


class TestLeidenClustering:
    """Test LeidenClustering class."""

    def test_init_default(self):
        """Test default initialization."""
        clustering = LeidenClustering()
        assert clustering._resolution == 1.0

    def test_init_custom(self):
        """Test custom initialization."""
        clustering = LeidenClustering(resolution=0.5, random_seed=42)
        assert clustering._resolution == 0.5

    def test_cluster_empty(self):
        """Test clustering empty graph."""
        clustering = LeidenClustering()
        result = clustering.cluster([])

        assert result.partitions == {}
        assert result.communities == []
        assert result.modularity == 0.0

    def test_cluster_single_edge(self):
        """Test clustering graph with single edge."""
        clustering = LeidenClustering()
        edges = [("A", "B", 1.0)]

        result = clustering.cluster(edges)

        assert result.total_entities >= 1

    def test_cluster_two_communities(self):
        """Test clustering with two distinct communities."""
        clustering = LeidenClustering()
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("X", "Y", 1.0),
        ]

        result = clustering.cluster(edges)

        assert result.total_entities >= 2

    def test_cluster_complete_graph(self):
        """Test clustering complete graph."""
        clustering = LeidenClustering()
        edges = [
            ("A", "B", 1.0),
            ("A", "C", 1.0),
            ("B", "C", 1.0),
        ]

        result = clustering.cluster(edges)

        assert result.total_entities >= 1

    def test_cluster_with_weights(self):
        """Test clustering with weighted edges."""
        clustering = LeidenClustering()
        edges = [
            ("A", "B", 10.0),
            ("B", "C", 10.0),
            ("X", "Y", 1.0),
        ]

        result = clustering.cluster(edges)

        assert result.total_entities >= 2

    def test_cluster_with_node_names(self):
        """Test clustering with node name mapping."""
        clustering = LeidenClustering()
        edges = [("A", "B", 1.0)]
        node_names = {"A": "Entity A", "B": "Entity B"}

        result = clustering.cluster(edges, node_names)

        assert len(result.communities) > 0

    def test_cluster_with_hierarchy(self):
        """Test hierarchical clustering."""
        clustering = LeidenClustering()
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("D", "E", 1.0),
            ("E", "F", 1.0),
        ]

        result = clustering.cluster_with_hierarchy(edges)

        assert result.hierarchy is not None
        assert result.hierarchy.max_level >= 0

    def test_cluster_deterministic(self):
        """Test deterministic clustering with fixed seed."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0)]

        clustering1 = LeidenClustering(random_seed=42)
        result1 = clustering1.cluster(edges)

        clustering2 = LeidenClustering(random_seed=42)
        result2 = clustering2.cluster(edges)

        assert result1.partitions == result2.partitions

    def test_cluster_resolution_parameter(self):
        """Test resolution parameter effect."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("X", "Y", 1.0),
        ]

        clustering_low = LeidenClustering(resolution=0.1)
        result_low = clustering_low.cluster(edges)

        clustering_high = LeidenClustering(resolution=2.0)
        result_high = clustering_high.cluster(edges)

        assert result_low.resolution == 0.1
        assert result_high.resolution == 2.0


class TestClusteringResult:
    """Test ClusteringResult from Leiden."""

    def test_get_community_entities(self):
        """Test getting entities in community."""
        clustering = LeidenClustering()
        edges = [("A", "B", 1.0), ("B", "C", 1.0)]

        result = clustering.cluster(edges)

        if result.partitions:
            community_0_entities = result.get_community_entities(0)
            assert isinstance(community_0_entities, list)

    def test_community_sizes(self):
        """Test community sizes calculation."""
        clustering = LeidenClustering()
        edges = [
            ("A", "B", 1.0),
            ("C", "D", 1.0),
        ]

        result = clustering.cluster(edges)
        sizes = result.community_sizes()

        assert isinstance(sizes, dict)

    def test_to_dict(self):
        """Test serialization to dict."""
        clustering = LeidenClustering()
        edges = [("A", "B", 1.0)]

        result = clustering.cluster(edges)
        d = result.to_dict()

        assert "partitions" in d
        assert "communities" in d
        assert "modularity" in d
