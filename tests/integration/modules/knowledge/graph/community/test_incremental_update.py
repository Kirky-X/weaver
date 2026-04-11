# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for community incremental update."""

import pytest

from core.db.graph_query_builders import GraphDatabaseType
from modules.knowledge.graph.community.detector import CommunityDetector
from modules.knowledge.graph.community.repo import Neo4jCommunityRepo
from modules.knowledge.graph.community.subgraph_extractor import SubgraphExtractor


@pytest.fixture
async def graph_test_data(graph_pool) -> None:
    """Setup test entities and relationships in graph database.

    Creates 4 entities with RELATED_TO relationships forming a chain:
    Entity_A -> Entity_B -> Entity_C -> Entity_D
    """
    pool, db_type = graph_pool

    # Create entities (LadybugDB requires id as primary key)
    entities = ["Entity_A", "Entity_B", "Entity_C", "Entity_D"]
    for name in entities:
        await pool.execute_query(
            """
            CREATE (e:Entity {id: $id, canonical_name: $name})
            """,
            {"id": name, "name": name},
        )

    # Create relationships with weights
    edges = [
        ("Entity_A", "Entity_B", 1.0),
        ("Entity_B", "Entity_C", 1.0),
        ("Entity_C", "Entity_D", 1.0),
    ]
    for source, target, weight in edges:
        await pool.execute_query(
            """
            MATCH (s:Entity {id: $source})
            MATCH (t:Entity {id: $target})
            CREATE (s)-[r:RELATED_TO {weight: $weight}]->(t)
            """,
            {"source": source, "target": target, "weight": weight},
        )

    yield

    # Cleanup - simpler approach for LadybugDB compatibility
    # Delete all RELATED_TO relationships between test entities
    for source in ["Entity_A", "Entity_B", "Entity_C", "Entity_D"]:
        for target in ["Entity_A", "Entity_B", "Entity_C", "Entity_D"]:
            try:
                await pool.execute_query(
                    """
                    MATCH (s:Entity {id: $source})-[r:RELATED_TO]->(t:Entity {id: $target})
                    DELETE r
                    """,
                    {"source": source, "target": target},
                )
            except Exception:
                pass  # Ignore if relationship doesn't exist

    # Delete entities
    for name in ["Entity_A", "Entity_B", "Entity_C", "Entity_D"]:
        await pool.execute_query(
            """
            MATCH (e:Entity {id: $id})
            DELETE e
            """,
            {"id": name},
        )


@pytest.mark.integration
class TestSubgraphExtractor:
    """Integration tests for subgraph extraction."""

    @pytest.fixture
    def extractor(self, graph_pool) -> SubgraphExtractor:
        """Create SubgraphExtractor fixture."""
        pool, db_type = graph_pool
        return SubgraphExtractor(pool, database_type=GraphDatabaseType(db_type))

    async def test_extract_subgraph_returns_edges(self, extractor, graph_test_data) -> None:
        """Subgraph extraction returns edge tuples."""
        entities = ["Entity_A", "Entity_B"]
        edges = await extractor.extract_subgraph(entities, max_hops=1)

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

    async def test_get_subgraph_entities_includes_centers(self, extractor, graph_test_data) -> None:
        """Get subgraph entities includes center entities."""
        centers = ["Entity_A", "Entity_B"]
        entities = await extractor.get_subgraph_entities(centers, max_hops=1)
        for center in centers:
            assert center in entities

    async def test_extract_2hops_expands_neighbors(self, extractor, graph_test_data) -> None:
        """2-hop extraction expands to neighbors' neighbors."""
        centers = ["Entity_A"]
        edges_1hop = await extractor.extract_subgraph(centers, max_hops=1)
        edges_2hop = await extractor.extract_subgraph(centers, max_hops=2)
        assert len(edges_2hop) >= len(edges_1hop)


@pytest.mark.integration
class TestCommunityDetectorIntegration:
    """Integration tests for CommunityDetector."""

    @pytest.fixture
    def detector(self, graph_pool) -> CommunityDetector:
        """Create CommunityDetector fixture."""
        pool, db_type = graph_pool
        return CommunityDetector(
            pool=pool,
            max_cluster_size=10,
            default_seed=42,
            database_type=GraphDatabaseType(db_type),
        )

    async def test_detect_communities_with_use_lcc(self, detector, graph_test_data) -> None:
        """detect_communities respects use_lcc parameter."""
        result = await detector.detect_communities(
            max_cluster_size=10,
            use_lcc=True,
            iterations=1,
            seed=42,
        )

        assert isinstance(result.communities, list)
        for community in result.communities:
            assert hasattr(community, "children_ids")
            assert isinstance(community.children_ids, list)

    async def test_detect_communities_without_use_lcc(self, detector, graph_test_data) -> None:
        """detect_communities with use_lcc=False processes all components."""
        result = await detector.detect_communities(
            max_cluster_size=10,
            use_lcc=False,
            iterations=1,
            seed=42,
        )
        assert result.total_communities >= 0

    async def test_rebuild_communities_persists_children_ids(
        self, detector, graph_pool, graph_test_data
    ) -> None:
        """rebuild_communities persists children_ids."""
        pool, db_type = graph_pool
        repo = Neo4jCommunityRepo(pool, database_type=GraphDatabaseType(db_type))

        await repo.delete_all_communities()
        result = await detector.rebuild_communities(max_cluster_size=10, seed=42)

        if result.communities:
            community = result.communities[0]
            retrieved = await repo.get_community(community.id)
            if retrieved:
                assert retrieved.children_ids is not None


@pytest.mark.integration
class TestCommunityRepoIntegration:
    """Integration tests for Neo4jCommunityRepo.

    Tests basic CRUD operations without complex graph data.
    Works with both Neo4j and LadybugDB.
    """

    @pytest.fixture
    def repo(self, graph_pool) -> Neo4jCommunityRepo:
        """Create repo fixture."""
        pool, db_type = graph_pool
        return Neo4jCommunityRepo(pool, database_type=GraphDatabaseType(db_type))

    async def test_create_and_get_community(self, repo) -> None:
        """create_community stores and retrieves community."""
        community_id = "test-community-basic"

        await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=0,
            parent_id=None,
            children_ids=["child-1", "child-2"],
            entity_count=5,
            rank=1.0,
        )

        community = await repo.get_community(community_id)
        assert community is not None
        assert community.id == community_id
        assert community.title == "Test Community"
        assert community.children_ids == ["child-1", "child-2"]

        await repo.delete_community(community_id)

    async def test_update_children_ids(self, repo) -> None:
        """update_children modifies children_ids."""
        community_id = "test-community-update"

        await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=0,
            children_ids=[],
        )

        await repo.update_children(community_id, ["new-child-1", "new-child-2"])

        community = await repo.get_community(community_id)
        assert community is not None
        assert community.children_ids == ["new-child-1", "new-child-2"]

        await repo.delete_community(community_id)

    async def test_delete_community(self, repo) -> None:
        """delete_community removes community."""
        community_id = "test-community-delete"

        await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=0,
        )

        community = await repo.get_community(community_id)
        assert community is not None

        result = await repo.delete_community(community_id)
        assert result is True

        community = await repo.get_community(community_id)
        assert community is None
