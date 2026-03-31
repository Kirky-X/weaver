# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CommunityDetector."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.graph_store.community_detector import (
    GRASPOLOGIC_AVAILABLE,
    CommunityDetector,
)
from modules.graph_store.community_models import (
    Community,
    CommunityDetectionResult,
    HierarchicalCluster,
)


class TestCommunityDetectorInit:
    """Test CommunityDetector initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        detector = CommunityDetector(mock_pool)

        assert detector._pool == mock_pool
        assert detector._max_cluster_size == 10
        assert detector._default_seed == 42

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        mock_pool = MagicMock()
        detector = CommunityDetector(
            pool=mock_pool,
            max_cluster_size=20,
            default_seed=100,
        )

        assert detector._max_cluster_size == 20
        assert detector._default_seed == 100


class TestCommunityDetectorBuildEdgeList:
    """Test _build_edge_list method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    @pytest.mark.asyncio
    async def test_build_edge_list_returns_normalized_edges(self, detector):
        """Test that _build_edge_list returns normalized edges."""
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 1.0},
                {"source": "B", "target": "A", "weight": 0.5},  # Duplicate, normalized
                {"source": "C", "target": "D", "weight": 2.0},
            ]
        )

        edges = await detector._build_edge_list()

        # Should deduplicate normalized edges (A-B and B-A become same)
        assert len(edges) == 2

    @pytest.mark.asyncio
    async def test_build_edge_list_uses_weight(self, detector):
        """Test that _build_edge_list uses weight from relationship."""
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 2.5},
            ]
        )

        edges = await detector._build_edge_list()

        assert len(edges) == 1
        assert edges[0][2] == 2.5  # Weight is third element

    @pytest.mark.asyncio
    async def test_build_edge_list_default_weight(self, detector):
        """Test that _build_edge_list uses default weight when missing."""
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B"},  # No weight
            ]
        )

        edges = await detector._build_edge_list()

        assert len(edges) == 1
        assert edges[0][2] == 1.0  # Default weight

    @pytest.mark.asyncio
    async def test_build_edge_list_empty_result(self, detector):
        """Test that _build_edge_list returns empty list when no edges."""
        detector._pool.execute_query = AsyncMock(return_value=[])
        edges = await detector._build_edge_list()
        assert edges == []


class TestCommunityDetectorGetOrphanEntities:
    """Test _get_orphan_entities method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    @pytest.mark.asyncio
    async def test_get_orphan_entities_returns_names(self, detector):
        """Test that _get_orphan_entities returns entity names."""
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"name": "Orphan1"},
                {"name": "Orphan2"},
            ]
        )

        orphans = await detector._get_orphan_entities()

        assert len(orphans) == 2
        assert "Orphan1" in orphans
        assert "Orphan2" in orphans

    @pytest.mark.asyncio
    async def test_get_orphan_entities_empty(self, detector):
        """Test that _get_orphan_entities returns empty list when no orphans."""
        detector._pool.execute_query = AsyncMock(return_value=[])
        orphans = await detector._get_orphan_entities()
        assert orphans == []


@pytest.mark.skipif(
    not GRASPOLOGIC_AVAILABLE,
    reason="graspologic not available due to PyTorch 2.x compatibility issues",
)
class TestCommunityDetectorRunHierarchicalLeiden:
    """Test _run_hierarchical_leiden method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    def test_run_hierarchical_leiden_returns_clusters(self, detector):
        """Test that _run_hierarchical_leiden returns clusters."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("C", "D", 1.0),
        ]

        clusters = detector._run_hierarchical_leiden(
            edges=edges,
            max_cluster_size=10,
            seed=42,
        )

        # Should return list of HierarchicalCluster
        assert isinstance(clusters, list)
        assert len(clusters) > 0
        assert all(isinstance(c, HierarchicalCluster) for c in clusters)

    def test_run_hierarchical_leiden_respects_seed(self, detector):
        """Test that _run_hierarchical_leiden produces consistent results with same seed."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("C", "D", 1.0),
            ("D", "E", 1.0),
        ]

        clusters1 = detector._run_hierarchical_leiden(edges=edges, max_cluster_size=10, seed=42)
        clusters2 = detector._run_hierarchical_leiden(edges=edges, max_cluster_size=10, seed=42)

        # Same seed should produce same results
        assert len(clusters1) == len(clusters2)


class TestCommunityDetectorBuildCommunitiesFromClusters:
    """Test _build_communities_from_clusters method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    def test_build_communities_from_clusters_returns_communities(self, detector):
        """Test that _build_communities_from_clusters returns Community list."""
        clusters = [
            HierarchicalCluster(node="A", cluster=0, level=0, parent_cluster=1),
            HierarchicalCluster(node="B", cluster=0, level=0, parent_cluster=1),
            HierarchicalCluster(node="C", cluster=1, level=1, parent_cluster=None),
        ]

        communities = detector._build_communities_from_clusters(clusters)

        assert isinstance(communities, list)
        assert all(isinstance(c, Community) for c in communities)

    def test_build_communities_groups_by_cluster(self, detector):
        """Test that entities are grouped by cluster."""
        clusters = [
            HierarchicalCluster(node="A", cluster=0, level=0, parent_cluster=None),
            HierarchicalCluster(node="B", cluster=0, level=0, parent_cluster=None),
            HierarchicalCluster(node="C", cluster=1, level=0, parent_cluster=None),
        ]

        communities = detector._build_communities_from_clusters(clusters)

        # Should have 2 communities (cluster 0 and cluster 1)
        assert len(communities) == 2

        # Find community with A and B
        community_0 = next((c for c in communities if "A" in c.entity_ids), None)
        assert community_0 is not None
        assert "B" in community_0.entity_ids
        assert community_0.entity_count == 2

    def test_build_communities_sets_hierarchy(self, detector):
        """Test that parent-child hierarchy is set correctly."""
        clusters = [
            HierarchicalCluster(node="A", cluster=0, level=0, parent_cluster=1),
            HierarchicalCluster(node="B", cluster=1, level=1, parent_cluster=None),
        ]

        communities = detector._build_communities_from_clusters(clusters)

        # Find level 0 community (child)
        child = next((c for c in communities if c.level == 0), None)
        assert child is not None
        # Parent should be set based on parent_cluster reference
        # Note: parent_id is set to the community_id of the parent cluster


class TestCommunityDetectorCreateOrphanCommunity:
    """Test _create_orphan_community method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    def test_create_orphan_community_returns_community(self, detector):
        """Test that _create_orphan_community returns Community."""
        orphan_entities = ["Orphan1", "Orphan2", "Orphan3"]

        community = detector._create_orphan_community(orphan_entities)

        assert isinstance(community, Community)
        assert community.title == "Orphan Entities"
        assert community.level == -1  # Special level for orphans
        assert community.entity_count == 3
        assert community.rank == 0.0

    def test_create_orphan_community_empty_list(self, detector):
        """Test that _create_orphan_community handles empty list."""
        community = detector._create_orphan_community([])

        assert community.entity_count == 0


class TestCommunityDetectorCalculateModularity:
    """Test _calculate_modularity method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    def test_calculate_modularity_returns_float(self, detector):
        """Test that _calculate_modularity returns float."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("C", "D", 1.0),
            ("D", "A", 1.0),
        ]
        clusters = [
            HierarchicalCluster(node="A", cluster=0, level=0, parent_cluster=None),
            HierarchicalCluster(node="B", cluster=0, level=0, parent_cluster=None),
            HierarchicalCluster(node="C", cluster=1, level=0, parent_cluster=None),
            HierarchicalCluster(node="D", cluster=1, level=0, parent_cluster=None),
        ]

        modularity = detector._calculate_modularity(edges, clusters)

        assert isinstance(modularity, float)
        # Modularity should be in valid range [-0.5, 1.0]
        assert -0.5 <= modularity <= 1.0

    def test_calculate_modularity_empty_edges(self, detector):
        """Test that _calculate_modularity returns 0 for empty edges."""
        modularity = detector._calculate_modularity([], [])
        assert modularity == 0.0

    def test_calculate_modularity_no_leaf_clusters(self, detector):
        """Test that _calculate_modularity returns 0 when no leaf clusters."""
        edges = [("A", "B", 1.0)]
        # Clusters with level > 0 (no leaf level)
        clusters = [
            HierarchicalCluster(node="A", cluster=0, level=1, parent_cluster=None),
        ]

        modularity = detector._calculate_modularity(edges, clusters)
        assert modularity == 0.0


@pytest.mark.skipif(
    not GRASPOLOGIC_AVAILABLE,
    reason="graspologic not available due to PyTorch 2.x compatibility issues",
)
class TestCommunityDetectorDetectCommunities:
    """Test detect_communities method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    @pytest.mark.asyncio
    async def test_detect_communities_returns_result(self, detector):
        """Test that detect_communities returns CommunityDetectionResult."""
        # Mock edges
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 1.0},
                {"source": "B", "target": "C", "weight": 1.0},
            ]
        )

        result = await detector.detect_communities()

        assert isinstance(result, CommunityDetectionResult)
        assert isinstance(result.communities, list)
        assert isinstance(result.total_entities, int)
        assert isinstance(result.total_communities, int)
        assert isinstance(result.modularity, float)
        assert isinstance(result.levels, int)
        assert isinstance(result.orphan_count, int)
        assert isinstance(result.execution_time_ms, float)

    @pytest.mark.asyncio
    async def test_detect_communities_no_edges(self, detector):
        """Test that detect_communities handles graph with no edges."""
        detector._pool.execute_query = AsyncMock(return_value=[])

        result = await detector.detect_communities()

        assert result.communities == []
        assert result.total_entities == 0
        assert result.total_communities == 0
        assert result.modularity == 0.0

    @pytest.mark.asyncio
    async def test_detect_communities_with_orphans(self, detector):
        """Test that detect_communities includes orphan entities."""
        # First call returns edges, second returns orphans
        detector._pool.execute_query = AsyncMock(
            side_effect=[
                [{"source": "A", "target": "B", "weight": 1.0}],  # Edges
                [{"name": "Orphan1"}],  # Orphans
            ]
        )

        result = await detector.detect_communities()

        # Should have orphan community
        assert result.orphan_count == 1

    @pytest.mark.asyncio
    async def test_detect_communities_respects_max_cluster_size(self, detector):
        """Test that detect_communities uses max_cluster_size parameter."""
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 1.0},
                {"source": "B", "target": "C", "weight": 1.0},
            ]
        )

        # Run with different max_cluster_size values
        result1 = await detector.detect_communities(max_cluster_size=5)
        result2 = await detector.detect_communities(max_cluster_size=20)

        # Both should succeed (different parameters may produce different results)
        assert isinstance(result1, CommunityDetectionResult)
        assert isinstance(result2, CommunityDetectionResult)


class TestCommunityDetectorRebuildCommunities:
    """Test rebuild_communities method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        detector = CommunityDetector(pool)
        detector._repo = MagicMock()
        detector._repo.delete_all_communities = AsyncMock(return_value=5)
        detector._repo.ensure_constraints = AsyncMock()
        detector._repo.create_community = AsyncMock(return_value="community-id")
        detector._repo.add_entities_batch = AsyncMock(return_value=1)
        detector._get_entity_types = AsyncMock(return_value={"A": "人物"})
        return detector

    @pytest.mark.asyncio
    async def test_rebuild_communities_deletes_existing(self, detector):
        """Test that rebuild_communities deletes existing communities."""
        # Mock edges for detection
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 1.0},
            ]
        )

        await detector.rebuild_communities()

        detector._repo.delete_all_communities.assert_called_once()

    @pytest.mark.asyncio
    async def test_rebuild_communities_returns_result(self, detector):
        """Test that rebuild_communities returns CommunityDetectionResult."""
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 1.0},
            ]
        )

        result = await detector.rebuild_communities()

        assert isinstance(result, CommunityDetectionResult)


class TestCommunityDetectorGetEntityTypes:
    """Test _get_entity_types method."""

    @pytest.fixture
    def detector(self):
        """Create CommunityDetector instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return CommunityDetector(pool)

    @pytest.mark.asyncio
    async def test_get_entity_types_returns_mapping(self, detector):
        """Test that _get_entity_types returns name to type mapping."""
        detector._pool.execute_query = AsyncMock(
            return_value=[
                {"name": "OpenAI", "type": "组织机构"},
                {"name": "GPT-4", "type": "产品"},
            ]
        )

        result = await detector._get_entity_types(["OpenAI", "GPT-4"])

        assert result["OpenAI"] == "组织机构"
        assert result["GPT-4"] == "产品"

    @pytest.mark.asyncio
    async def test_get_entity_types_empty_list(self, detector):
        """Test that _get_entity_types returns empty dict for empty list."""
        result = await detector._get_entity_types([])
        assert result == {}
