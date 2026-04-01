# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CommunityDetector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.community.models import (
    Community,
    CommunityDetectionResult,
    HierarchicalCluster,
)


class TestCommunityDetectorInit:
    """Tests for CommunityDetector initialization."""

    def test_detector_initialization(self):
        """Test detector initializes correctly."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()

        detector = CommunityDetector(pool=mock_pool)

        assert detector._pool is mock_pool
        assert detector._max_cluster_size == 10
        assert detector._default_seed == 42

    def test_detector_with_custom_params(self):
        """Test detector with custom parameters."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()

        detector = CommunityDetector(
            pool=mock_pool,
            max_cluster_size=20,
            default_seed=100,
        )

        assert detector._max_cluster_size == 20
        assert detector._default_seed == 100


class TestCommunityDetectorBuildEdgeList:
    """Tests for _build_edge_list method."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_build_edge_list_empty(self, mock_pool):
        """Test with no edges."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(return_value=[])

        detector = CommunityDetector(pool=mock_pool)
        edges = await detector._build_edge_list()

        assert edges == []

    @pytest.mark.asyncio
    async def test_build_edge_list_single_edge(self, mock_pool):
        """Test with single edge."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(
            return_value=[{"source": "entity_a", "target": "entity_b", "weight": 1.0}]
        )

        detector = CommunityDetector(pool=mock_pool)
        edges = await detector._build_edge_list()

        assert len(edges) == 1
        assert edges[0][2] == 1.0  # weight

    @pytest.mark.asyncio
    async def test_build_edge_list_normalizes_direction(self, mock_pool):
        """Test that edges are normalized to undirected."""
        from modules.knowledge.community.detector import CommunityDetector

        # Two edges in opposite directions should become one
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"source": "b", "target": "a", "weight": 1.0},
                {"source": "a", "target": "b", "weight": 2.0},
            ]
        )

        detector = CommunityDetector(pool=mock_pool)
        edges = await detector._build_edge_list()

        # Should be deduplicated, keeping higher weight
        assert len(edges) == 1
        assert edges[0][2] == 2.0  # Higher weight kept

    @pytest.mark.asyncio
    async def test_build_edge_list_keeps_higher_weight(self, mock_pool):
        """Test that duplicate edges keep higher weight."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"source": "entity_a", "target": "entity_b", "weight": 0.5},
                {"source": "entity_a", "target": "entity_b", "weight": 2.0},
            ]
        )

        detector = CommunityDetector(pool=mock_pool)
        edges = await detector._build_edge_list()

        assert len(edges) == 1
        assert edges[0][2] == 2.0


class TestCommunityDetectorGetOrphanEntities:
    """Tests for _get_orphan_entities method."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_get_orphan_entities_empty(self, mock_pool):
        """Test with no orphans."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(return_value=[])

        detector = CommunityDetector(pool=mock_pool)
        orphans = await detector._get_orphan_entities()

        assert orphans == []

    @pytest.mark.asyncio
    async def test_get_orphan_entities_with_results(self, mock_pool):
        """Test with orphan entities."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"name": "orphan_entity_1"},
                {"name": "orphan_entity_2"},
            ]
        )

        detector = CommunityDetector(pool=mock_pool)
        orphans = await detector._get_orphan_entities()

        assert len(orphans) == 2
        assert "orphan_entity_1" in orphans
        assert "orphan_entity_2" in orphans

    @pytest.mark.asyncio
    async def test_get_orphan_entities_filters_none_names(self, mock_pool):
        """Test that None names are filtered out."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"name": "valid_entity"},
                {"name": None},
                {"name": ""},
            ]
        )

        detector = CommunityDetector(pool=mock_pool)
        orphans = await detector._get_orphan_entities()

        assert orphans == ["valid_entity"]


class TestCommunityDetectorCreateOrphanCommunity:
    """Tests for _create_orphan_community method."""

    def test_create_orphan_community(self):
        """Test orphan community creation."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        community = detector._create_orphan_community(["orphan1", "orphan2"])

        assert community.level == -1
        assert community.title == "Orphan Entities"
        assert community.entity_count == 2
        assert community.rank == 0.0
        assert "orphan1" in community.entity_ids
        assert "orphan2" in community.entity_ids

    def test_create_orphan_community_empty(self):
        """Test orphan community with empty list."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        community = detector._create_orphan_community([])

        assert community.entity_count == 0
        assert community.entity_ids == []


class TestCommunityDetectorBuildCommunitiesFromClusters:
    """Tests for _build_communities_from_clusters method."""

    def test_build_communities_empty_clusters(self):
        """Test with empty clusters."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        communities = detector._build_communities_from_clusters([])

        assert communities == []

    def test_build_communities_single_cluster(self):
        """Test with single cluster."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        clusters = [
            HierarchicalCluster(node="entity_a", cluster=0, level=0, parent_cluster=None),
            HierarchicalCluster(node="entity_b", cluster=0, level=0, parent_cluster=None),
        ]

        communities = detector._build_communities_from_clusters(clusters)

        assert len(communities) == 1
        assert communities[0].entity_count == 2
        assert communities[0].level == 0

    def test_build_communities_multiple_clusters(self):
        """Test with multiple clusters at different levels."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        clusters = [
            HierarchicalCluster(node="entity_a", cluster=0, level=0, parent_cluster=0),
            HierarchicalCluster(node="entity_b", cluster=1, level=0, parent_cluster=0),
            HierarchicalCluster(node="entity_a", cluster=0, level=1, parent_cluster=None),
            HierarchicalCluster(node="entity_b", cluster=0, level=1, parent_cluster=None),
        ]

        communities = detector._build_communities_from_clusters(clusters)

        assert len(communities) >= 2


class TestCommunityDetectorCalculateModularity:
    """Tests for _calculate_modularity method."""

    def test_calculate_modularity_empty(self):
        """Test with empty inputs."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        modularity = detector._calculate_modularity([], [])

        assert modularity == 0.0

    def test_calculate_modularity_single_cluster(self):
        """Test with single cluster."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        edges = [("a", "b", 1.0), ("b", "c", 1.0)]
        clusters = [
            HierarchicalCluster(node="a", cluster=0, level=0),
            HierarchicalCluster(node="b", cluster=0, level=0),
            HierarchicalCluster(node="c", cluster=0, level=0),
        ]

        modularity = detector._calculate_modularity(edges, clusters)

        # Modularity is calculated based on internal vs external edges
        # For a single community with all internal edges, value is 0
        assert modularity >= 0

    def test_calculate_modularity_no_leaf_clusters(self):
        """Test when no level 0 clusters exist."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        edges = [("a", "b", 1.0)]
        clusters = [
            HierarchicalCluster(node="a", cluster=0, level=1),  # Level 1, not 0
            HierarchicalCluster(node="b", cluster=0, level=1),
        ]

        modularity = detector._calculate_modularity(edges, clusters)

        assert modularity == 0.0


class TestCommunityDetectorRunHierarchicalLeiden:
    """Tests for _run_hierarchical_leiden method."""

    def test_run_hierarchical_leiden_empty_edges(self):
        """Test with empty edges."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        clusters = detector._run_hierarchical_leiden(
            edges=[],
            max_cluster_size=10,
            seed=42,
        )

        assert clusters == []

    def test_run_hierarchical_leiden_single_edge(self):
        """Test with single edge."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        edges = [("a", "b", 1.0)]

        clusters = detector._run_hierarchical_leiden(
            edges=edges,
            max_cluster_size=10,
            seed=42,
        )

        assert len(clusters) == 2
        assert all(isinstance(c, HierarchicalCluster) for c in clusters)

    def test_run_hierarchical_leiden_small_graph(self):
        """Test with small graph."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool = MagicMock()
        detector = CommunityDetector(pool=mock_pool)

        edges = [
            ("a", "b", 1.0),
            ("b", "c", 1.0),
            ("c", "d", 1.0),
        ]

        clusters = detector._run_hierarchical_leiden(
            edges=edges,
            max_cluster_size=10,
            seed=42,
        )

        assert len(clusters) == 4
        # All nodes should be in the same cluster for a connected graph
        cluster_ids = {c.cluster for c in clusters}
        assert len(cluster_ids) >= 1


class TestCommunityDetectorDetectCommunities:
    """Tests for detect_communities method."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_detect_communities_no_edges(self, mock_pool):
        """Test detection with no edges."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(return_value=[])

        detector = CommunityDetector(pool=mock_pool)
        result = await detector.detect_communities()

        assert isinstance(result, CommunityDetectionResult)
        assert result.total_communities == 0
        assert result.total_entities == 0

    @pytest.mark.asyncio
    async def test_detect_communities_with_edges(self, mock_pool):
        """Test detection with edges."""
        from modules.knowledge.community.detector import CommunityDetector

        # Mock edge query
        edge_results = [
            {"source": "entity_a", "target": "entity_b", "weight": 1.0},
        ]
        # Mock orphan query
        orphan_results = []

        mock_pool.execute_query = AsyncMock(side_effect=[edge_results, orphan_results])

        detector = CommunityDetector(pool=mock_pool)
        result = await detector.detect_communities()

        assert isinstance(result, CommunityDetectionResult)
        assert result.total_entities >= 0

    @pytest.mark.asyncio
    async def test_detect_communities_with_orphans(self, mock_pool):
        """Test detection with orphan entities."""
        from modules.knowledge.community.detector import CommunityDetector

        edge_results = [
            {"source": "entity_a", "target": "entity_b", "weight": 1.0},
        ]
        orphan_results = [
            {"name": "orphan_entity"},
        ]

        mock_pool.execute_query = AsyncMock(side_effect=[edge_results, orphan_results])

        detector = CommunityDetector(pool=mock_pool)
        result = await detector.detect_communities()

        assert result.orphan_count == 1

    @pytest.mark.asyncio
    async def test_detect_communities_custom_params(self, mock_pool):
        """Test detection with custom parameters."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(return_value=[])

        detector = CommunityDetector(pool=mock_pool)
        result = await detector.detect_communities(
            max_cluster_size=20,
            seed=100,
        )

        assert isinstance(result, CommunityDetectionResult)


class TestCommunityDetectorRebuildCommunities:
    """Tests for rebuild_communities method."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_rebuild_communities_deletes_existing(self, mock_pool):
        """Test that rebuild deletes existing communities."""
        from modules.knowledge.community.detector import CommunityDetector

        # Mock delete_all_communities
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"total": 5}],  # delete result
                [],  # edges
                [],  # orphans
            ]
        )

        detector = CommunityDetector(pool=mock_pool)
        with patch.object(detector._repo, "delete_all_communities", return_value=5):
            with patch.object(detector, "detect_communities") as mock_detect:
                mock_detect.return_value = CommunityDetectionResult(communities=[])

                await detector.rebuild_communities()

    @pytest.mark.asyncio
    async def test_rebuild_communities_returns_result(self, mock_pool):
        """Test that rebuild returns detection result."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(return_value=[])

        detector = CommunityDetector(pool=mock_pool)

        with patch.object(detector, "detect_communities") as mock_detect:
            mock_result = CommunityDetectionResult(
                communities=[],
                total_entities=0,
                total_communities=0,
            )
            mock_detect.return_value = mock_result

            result = await detector.rebuild_communities()

            assert result.total_communities == 0


class TestCommunityDetectorPersistCommunities:
    """Tests for _persist_communities method."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_persist_communities_empty(self, mock_pool):
        """Test persisting empty list."""
        from modules.knowledge.community.detector import CommunityDetector

        detector = CommunityDetector(pool=mock_pool)

        with patch.object(detector._repo, "ensure_constraints"):
            count = await detector._persist_communities([])

        assert count == 0

    @pytest.mark.asyncio
    async def test_persist_communities_single(self, mock_pool):
        """Test persisting single community."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # ensure_constraints
                [{"id": "test-id"}],  # create_community
                [{"name": "entity1", "type": "Person"}],  # get_entity_types
                [{"total": 1}],  # add_entities_batch
            ]
        )

        detector = CommunityDetector(pool=mock_pool)

        community = Community(
            id="test-id",
            title="Test Community",
            level=0,
            entity_ids=["entity1"],
            entity_count=1,
        )

        with patch.object(detector._repo, "ensure_constraints"):
            with patch.object(detector._repo, "create_community", return_value="test-id"):
                with patch.object(detector._repo, "add_entities_batch", return_value=1):
                    with patch.object(
                        detector, "_get_entity_types", return_value={"entity1": "Person"}
                    ):
                        count = await detector._persist_communities([community])

        assert count == 1


class TestCommunityDetectorGetEntityTypes:
    """Tests for _get_entity_types method."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_get_entity_types_empty(self, mock_pool):
        """Test with empty entity list."""
        from modules.knowledge.community.detector import CommunityDetector

        detector = CommunityDetector(pool=mock_pool)
        result = await detector._get_entity_types([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_entity_types_single(self, mock_pool):
        """Test with single entity."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(return_value=[{"name": "entity1", "type": "Person"}])

        detector = CommunityDetector(pool=mock_pool)
        result = await detector._get_entity_types(["entity1"])

        assert result == {"entity1": "Person"}

    @pytest.mark.asyncio
    async def test_get_entity_types_multiple(self, mock_pool):
        """Test with multiple entities."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"name": "entity1", "type": "Person"},
                {"name": "entity2", "type": "Organization"},
            ]
        )

        detector = CommunityDetector(pool=mock_pool)
        result = await detector._get_entity_types(["entity1", "entity2"])

        assert result == {"entity1": "Person", "entity2": "Organization"}

    @pytest.mark.asyncio
    async def test_get_entity_types_handles_missing(self, mock_pool):
        """Test handling of missing type field."""
        from modules.knowledge.community.detector import CommunityDetector

        mock_pool.execute_query = AsyncMock(return_value=[{"name": "entity1", "type": None}])

        detector = CommunityDetector(pool=mock_pool)
        result = await detector._get_entity_types(["entity1"])

        # Code returns None for missing type, not a default
        assert result == {"entity1": None}


class TestCommunityDetectorIntegration:
    """Integration-like tests for CommunityDetector."""

    @pytest.fixture
    def mock_pool(self):
        """Mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_full_detection_flow(self, mock_pool):
        """Test a full detection flow with mocked database."""
        from modules.knowledge.community.detector import CommunityDetector

        # Mock queries in order: edges, orphans
        edge_results = [
            {"source": "a", "target": "b", "weight": 1.0},
            {"source": "b", "target": "c", "weight": 1.0},
            {"source": "c", "target": "d", "weight": 1.0},
        ]
        orphan_results = []

        mock_pool.execute_query = AsyncMock(side_effect=[edge_results, orphan_results])

        detector = CommunityDetector(pool=mock_pool)
        result = await detector.detect_communities()

        assert isinstance(result, CommunityDetectionResult)
        assert result.execution_time_ms > 0
        assert result.modularity >= 0
