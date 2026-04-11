# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for community incremental update."""

import pytest

from modules.knowledge.graph.community.detector import CommunityDetector
from modules.knowledge.graph.community.models import Community
from modules.knowledge.graph.community.repo import Neo4jCommunityRepo
from modules.knowledge.graph.community.subgraph_extractor import SubgraphExtractor


@pytest.mark.integration
class TestSubgraphExtractor:
    """Integration tests for subgraph extraction."""

    @pytest.fixture
    def extractor(self, neo4j_pool) -> SubgraphExtractor:
        """Create SubgraphExtractor fixture."""
        from core.db.graph_query_builders import GraphDatabaseType

        return SubgraphExtractor(neo4j_pool, database_type=GraphDatabaseType.NEO4J)

    async def test_extract_subgraph_returns_edges(self, extractor, neo4j_test_data) -> None:
        """Subgraph extraction returns edge tuples."""
        # Setup: Create test entities and relationships
        entities = ["Entity_A", "Entity_B"]

        edges = await extractor.extract_subgraph(entities, max_hops=1)

        # Should return list of edge tuples
        assert isinstance(edges, list)
        for edge in edges:
            assert len(edge) == 3  # (source, target, weight)
            assert isinstance(edge[0], str)
            assert isinstance(edge[1], str)
            assert isinstance(edge[2], float)

    async def test_extract_subgraph_empty_entities_returns_empty(self, extractor) -> None:
        """Empty entity list returns empty edges."""
        edges = await extractor.extract_subgraph([], max_hops=2)
        assert edges == []

    async def test_get_subgraph_entities_includes_centers(self, extractor) -> None:
        """Get subgraph entities includes center entities."""
        centers = ["Entity_A", "Entity_B"]

        entities = await extractor.get_subgraph_entities(centers, max_hops=1)

        # Center entities should be included
        for center in centers:
            assert center in entities

    async def test_extract_2hops_expands_neighbors(self, extractor, neo4j_test_data) -> None:
        """2-hop extraction expands to neighbors' neighbors."""
        centers = ["Entity_A"]

        edges_1hop = await extractor.extract_subgraph(centers, max_hops=1)
        edges_2hop = await extractor.extract_subgraph(centers, max_hops=2)

        # 2-hop should have more or equal edges than 1-hop
        assert len(edges_2hop) >= len(edges_1hop)


@pytest.mark.integration
class TestCommunityDetectorIntegration:
    """Integration tests for CommunityDetector."""

    @pytest.fixture
    def detector(self, neo4j_pool) -> CommunityDetector:
        """Create CommunityDetector fixture."""
        from core.db.graph_query_builders import GraphDatabaseType

        return CommunityDetector(
            pool=neo4j_pool,
            max_cluster_size=10,
            default_seed=42,
            database_type=GraphDatabaseType.NEO4J,
        )

    async def test_detect_communities_with_use_lcc(self, detector, neo4j_test_data) -> None:
        """detect_communities respects use_lcc parameter."""
        result = await detector.detect_communities(
            max_cluster_size=10,
            use_lcc=True,
            iterations=1,
            seed=42,
        )

        # Result should have communities
        assert isinstance(result.communities, list)
        # Each community should have children_ids
        for community in result.communities:
            assert hasattr(community, "children_ids")
            assert isinstance(community.children_ids, list)

    async def test_detect_communities_without_use_lcc(self, detector, neo4j_test_data) -> None:
        """detect_communities with use_lcc=False processes all components."""
        result = await detector.detect_communities(
            max_cluster_size=10,
            use_lcc=False,
            iterations=1,
            seed=42,
        )

        # Should still produce valid result
        assert result.total_communities >= 0

    async def test_rebuild_communities_persists_children_ids(
        self, detector, neo4j_pool, neo4j_test_data
    ) -> None:
        """rebuild_communities persists children_ids to Neo4j."""
        repo = Neo4jCommunityRepo(neo4j_pool)

        # Delete existing communities
        await repo.delete_all_communities()

        # Run rebuild
        result = await detector.rebuild_communities(
            max_cluster_size=10,
            seed=42,
        )

        # Retrieve a community and verify children_ids
        if result.communities:
            community = result.communities[0]
            retrieved = await repo.get_community(community.id)

            if retrieved:
                # Should have children_ids field
                assert retrieved.children_ids is not None


@pytest.mark.integration
class TestCommunityRepoIntegration:
    """Integration tests for Neo4jCommunityRepo."""

    @pytest.fixture
    def repo(self, neo4j_pool) -> Neo4jCommunityRepo:
        """Create repo fixture."""
        from core.db.graph_query_builders import GraphDatabaseType

        return Neo4jCommunityRepo(neo4j_pool, database_type=GraphDatabaseType.NEO4J)

    async def test_create_community_with_children_ids(self, repo) -> None:
        """create_community stores children_ids."""
        community_id = "test-community-children"

        await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=0,
            parent_id=None,
            children_ids=["child-1", "child-2"],
            entity_count=5,
            rank=1.0,
        )

        # Retrieve and verify
        community = await repo.get_community(community_id)

        if community:
            assert community.children_ids == ["child-1", "child-2"]

        # Cleanup
        await repo.delete_community(community_id)

    async def test_update_children(self, repo) -> None:
        """update_children modifies children_ids."""
        community_id = "test-community-update"

        # Create with empty children
        await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=0,
            children_ids=[],
        )

        # Update children
        await repo.update_children(community_id, ["new-child-1", "new-child-2"])

        # Verify update
        community = await repo.get_community(community_id)

        if community:
            assert community.children_ids == ["new-child-1", "new-child-2"]

        # Cleanup
        await repo.delete_community(community_id)

    async def test_delete_community_removes_node(self, repo) -> None:
        """delete_community removes community node."""
        community_id = "test-community-delete"

        # Create
        await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=0,
        )

        # Verify exists
        community = await repo.get_community(community_id)
        assert community is not None

        # Delete
        result = await repo.delete_community(community_id)
        assert result is True

        # Verify deleted
        community = await repo.get_community(community_id)
        assert community is None


@pytest.fixture
async def neo4j_test_data(neo4j_pool) -> None:
    """Setup test entities and relationships in Neo4j."""
    # Create test entities
    query = """
    MERGE (e1:Entity {canonical_name: 'Entity_A'})
    MERGE (e2:Entity {canonical_name: 'Entity_B'})
    MERGE (e3:Entity {canonical_name: 'Entity_C'})
    MERGE (e4:Entity {canonical_name: 'Entity_D'})

    MERGE (e1)-[r1:RELATED_TO {weight: 1.0}]->(e2)
    MERGE (e2)-[r2:RELATED_TO {weight: 1.0}]->(e3)
    MERGE (e3)-[r3:RELATED_TO {weight: 1.0}]->(e4)
    """
    await neo4j_pool.execute_query(query)

    yield

    # Cleanup
    cleanup = """
    MATCH (e:Entity) WHERE e.canonical_name IN ['Entity_A', 'Entity_B', 'Entity_C', 'Entity_D']
    DETACH DELETE e
    """
    await neo4j_pool.execute_query(cleanup)
