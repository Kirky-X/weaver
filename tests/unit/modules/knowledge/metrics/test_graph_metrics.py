# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for knowledge graph metrics."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.metrics.graph_metrics import (
    ConnectedComponent,
    EntityDegree,
    GraphMetrics,
    GraphQualityMetrics,
    _dfs_component,
)


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4jPool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def metrics_calculator(mock_neo4j_pool):
    """Create GraphQualityMetrics instance."""
    return GraphQualityMetrics(mock_neo4j_pool)


class TestDfsComponent:
    """Tests for _dfs_component helper function."""

    def test_single_node_component(self):
        """Test DFS on single node."""
        adjacency = {"A": set()}
        visited = set()

        result = _dfs_component("A", adjacency, visited)

        assert result == {"A"}
        assert visited == {"A"}

    def test_connected_component(self):
        """Test DFS finds connected nodes."""
        adjacency = {"A": {"B"}, "B": {"A", "C"}, "C": {"B"}}
        visited = set()

        result = _dfs_component("A", adjacency, visited)

        assert result == {"A", "B", "C"}

    def test_partial_visit(self):
        """Test DFS with pre-visited nodes."""
        adjacency = {"A": {"B"}, "B": {"A"}, "C": set()}
        visited = {"B"}

        result = _dfs_component("A", adjacency, visited)

        assert result == {"A"}
        assert "B" not in result

    def test_empty_adjacency(self):
        """Test DFS with missing node in adjacency."""
        adjacency: dict[str, set[str]] = {}
        visited = set()

        result = _dfs_component("Unknown", adjacency, visited)

        assert result == {"Unknown"}


class TestGraphMetrics:
    """Tests for GraphMetrics dataclass."""

    def test_default_initialization(self):
        """Test GraphMetrics initializes with defaults."""
        metrics = GraphMetrics()

        assert metrics.total_entities == 0
        assert metrics.total_articles == 0
        assert metrics.total_relationships == 0
        assert metrics.total_mentions == 0
        assert metrics.connected_components == 0
        assert metrics.largest_component_size == 0
        assert metrics.average_degree == 0.0
        assert metrics.modularity_score is None
        assert metrics.orphan_entities == 0
        assert metrics.high_degree_entities == []
        assert metrics.entity_type_distribution == {}
        assert metrics.relationship_type_distribution == {}

    def test_with_values(self):
        """Test GraphMetrics with values."""
        metrics = GraphMetrics(
            total_entities=100,
            total_articles=50,
            total_relationships=200,
            total_mentions=500,
            connected_components=5,
            largest_component_size=80,
            average_degree=4.0,
            modularity_score=0.65,
            orphan_entities=10,
            high_degree_entities=[{"name": "Hub", "degree": 50}],
            entity_type_distribution={"Person": 60, "Org": 40},
            relationship_type_distribution={"WORKS_FOR": 30},
        )

        assert metrics.total_entities == 100
        assert metrics.modularity_score == 0.65
        assert len(metrics.high_degree_entities) == 1

    def test_to_dict(self):
        """Test to_dict serialization."""
        metrics = GraphMetrics(
            total_entities=100,
            total_relationships=200,
            average_degree=4.0,
        )

        result = metrics.to_dict()

        assert result["total_entities"] == 100
        assert result["total_relationships"] == 200
        assert result["average_degree"] == 4.0
        assert "computed_at" in result

    def test_to_dict_with_datetime(self):
        """Test to_dict serializes datetime."""
        now = datetime.now(UTC)
        metrics = GraphMetrics(computed_at=now)

        result = metrics.to_dict()

        assert "computed_at" in result
        assert "T" in result["computed_at"]  # ISO format


class TestEntityDegree:
    """Tests for EntityDegree dataclass."""

    def test_default_initialization(self):
        """Test EntityDegree initializes with defaults."""
        degree = EntityDegree(
            entity_id="123",
            canonical_name="TestEntity",
            entity_type="Person",
        )

        assert degree.in_degree == 0
        assert degree.out_degree == 0
        assert degree.mention_count == 0
        assert degree.total_degree == 0

    def test_degree_property(self):
        """Test degree property returns sum of in + out."""
        degree = EntityDegree(
            entity_id="123",
            canonical_name="TestEntity",
            entity_type="Person",
            in_degree=5,
            out_degree=3,
        )

        assert degree.degree == 8

    def test_total_degree_field(self):
        """Test total_degree field can be set."""
        degree = EntityDegree(
            entity_id="123",
            canonical_name="TestEntity",
            entity_type="Person",
            in_degree=5,
            out_degree=3,
            total_degree=8,
        )

        assert degree.total_degree == 8


class TestConnectedComponent:
    """Tests for ConnectedComponent dataclass."""

    def test_initialization(self):
        """Test ConnectedComponent initializes correctly."""
        component = ConnectedComponent(
            component_id=0,
            node_ids=["A", "B", "C"],
            size=3,
            entity_types={"Person": 2, "Org": 1},
        )

        assert component.component_id == 0
        assert len(component.node_ids) == 3
        assert component.size == 3
        assert component.entity_types["Person"] == 2


class TestGraphQualityMetrics:
    """Tests for GraphQualityMetrics class."""

    def test_initialization(self, mock_neo4j_pool):
        """Test GraphQualityMetrics initializes with pool."""
        metrics = GraphQualityMetrics(mock_neo4j_pool)

        assert metrics._pool is mock_neo4j_pool

    @pytest.mark.asyncio
    async def test_calculate_all_metrics_full(self, metrics_calculator, mock_neo4j_pool):
        """Test calculate_all_metrics computes all metrics."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 100}],  # entities
            [{"count": 50}],  # articles
            [{"count": 200}],  # relationships
            [{"count": 500}],  # mentions
            [{"count": 10}],  # orphans
            [{"avg_degree": 4.0}],  # average degree
            [  # high degree entities
                {
                    "name": "Hub",
                    "type": "Person",
                    "in_degree": 20,
                    "out_degree": 15,
                    "mention_count": 50,
                    "total_degree": 35,
                }
            ],
            [{"avg_degree": 4.0}],  # avg degree again
            [  # component query
                {"entity": "A", "neighbors": ["B"]},
                {"entity": "B", "neighbors": ["A", "C"]},
                {"entity": "C", "neighbors": ["B"]},
            ],
            [{"type": "Person", "count": 60}],  # entity types
            [{"type": "WORKS_FOR", "count": 30}],  # relationship types
        ]

        result = await metrics_calculator.calculate_all_metrics()

        assert result.total_entities == 100
        assert result.total_articles == 50
        assert result.total_relationships == 200
        assert result.total_mentions == 500
        assert result.orphan_entities == 10

    @pytest.mark.asyncio
    async def test_calculate_all_metrics_selective(self, metrics_calculator, mock_neo4j_pool):
        """Test calculate_all_metrics with selective include."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 100}],  # entities
            [{"count": 50}],  # articles
            [{"count": 200}],  # relationships
            [{"count": 500}],  # mentions
            [{"avg_degree": 4.0}],  # average degree
        ]

        result = await metrics_calculator.calculate_all_metrics(include={"components"})

        assert result.total_entities == 100
        # components not calculated
        assert result.connected_components == 0

    @pytest.mark.asyncio
    async def test_calculate_counts_with_error(self, metrics_calculator, mock_neo4j_pool):
        """Test _calculate_counts handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        metrics = GraphMetrics()
        await metrics_calculator._calculate_counts(metrics)

        assert metrics.total_entities == 0

    @pytest.mark.asyncio
    async def test_calculate_degree_metrics_empty_graph(self, metrics_calculator, mock_neo4j_pool):
        """Test _calculate_degree_metrics with no entities."""
        metrics = GraphMetrics(total_entities=0)

        await metrics_calculator._calculate_degree_metrics(metrics, include_high_degree=False)

        assert metrics.average_degree == 0.0

    @pytest.mark.asyncio
    async def test_calculate_degree_metrics_with_high_degree(
        self, metrics_calculator, mock_neo4j_pool
    ):
        """Test _calculate_degree_metrics includes high degree entities."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"avg_degree": 4.0}],
            [
                {
                    "name": "Hub",
                    "type": "Person",
                    "in_degree": 20,
                    "out_degree": 15,
                    "mention_count": 50,
                    "total_degree": 35,
                }
            ],
            [{"avg_degree": 4.0}],
        ]

        metrics = GraphMetrics(total_entities=100)
        await metrics_calculator._calculate_degree_metrics(metrics, include_high_degree=True)

        assert len(metrics.high_degree_entities) == 1
        assert metrics.high_degree_entities[0]["name"] == "Hub"

    @pytest.mark.asyncio
    async def test_calculate_component_metrics(self, metrics_calculator, mock_neo4j_pool):
        """Test _calculate_component_metrics."""
        mock_neo4j_pool.execute_query.return_value = [
            {"entity": "A", "neighbors": ["B"]},
            {"entity": "B", "neighbors": ["A", "C"]},
            {"entity": "C", "neighbors": ["B"]},
            {"entity": "D", "neighbors": []},  # Isolated
        ]

        metrics = GraphMetrics()
        await metrics_calculator._calculate_component_metrics(metrics)

        assert metrics.connected_components == 2  # A-B-C and D
        assert metrics.largest_component_size == 3

    @pytest.mark.asyncio
    async def test_calculate_component_metrics_empty(self, metrics_calculator, mock_neo4j_pool):
        """Test _calculate_component_metrics with empty graph."""
        mock_neo4j_pool.execute_query.return_value = []

        metrics = GraphMetrics()
        await metrics_calculator._calculate_component_metrics(metrics)

        assert metrics.connected_components == 0

    @pytest.mark.asyncio
    async def test_calculate_distributions(self, metrics_calculator, mock_neo4j_pool):
        """Test _calculate_distributions."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"type": "Person", "count": 60}, {"type": "Org", "count": 40}],
            [{"type": "WORKS_FOR", "count": 30}],
        ]

        metrics = GraphMetrics()
        await metrics_calculator._calculate_distributions(metrics)

        assert metrics.entity_type_distribution["Person"] == 60
        assert metrics.entity_type_distribution["Org"] == 40
        assert metrics.relationship_type_distribution["WORKS_FOR"] == 30

    @pytest.mark.asyncio
    async def test_calculate_modularity_single_component(self, metrics_calculator, mock_neo4j_pool):
        """Test _calculate_modularity with single component."""
        metrics = GraphMetrics(total_entities=100, connected_components=1)
        await metrics_calculator._calculate_modularity(metrics)

        assert metrics.modularity_score == 0.0

    @pytest.mark.asyncio
    async def test_calculate_modularity_empty_graph(self, metrics_calculator, mock_neo4j_pool):
        """Test _calculate_modularity with empty graph."""
        metrics = GraphMetrics(total_entities=0)
        await metrics_calculator._calculate_modularity(metrics)

        assert metrics.modularity_score is None

    @pytest.mark.asyncio
    async def test_get_connected_components(self, metrics_calculator, mock_neo4j_pool):
        """Test get_connected_components."""
        mock_neo4j_pool.execute_query.return_value = [
            {"entity": "A", "type": "Person", "neighbors": ["B"]},
            {"entity": "B", "type": "Org", "neighbors": ["A"]},
        ]

        result = await metrics_calculator.get_connected_components()

        assert len(result) == 1
        assert result[0].size == 2
        assert "A" in result[0].node_ids
        assert "B" in result[0].node_ids

    @pytest.mark.asyncio
    async def test_get_largest_connected_component(self, metrics_calculator, mock_neo4j_pool):
        """Test get_largest_connected_component."""
        mock_neo4j_pool.execute_query.return_value = [
            {"entity": "A", "type": "Person", "neighbors": ["B"]},
            {"entity": "B", "type": "Org", "neighbors": ["A"]},
        ]

        result = await metrics_calculator.get_largest_connected_component()

        assert result is not None
        assert result.size == 2

    @pytest.mark.asyncio
    async def test_get_largest_connected_component_empty(self, metrics_calculator, mock_neo4j_pool):
        """Test get_largest_connected_component with empty graph."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await metrics_calculator.get_largest_connected_component()

        assert result is None

    @pytest.mark.asyncio
    async def test_calculate_entity_degrees(self, metrics_calculator, mock_neo4j_pool):
        """Test calculate_entity_degrees."""
        mock_neo4j_pool.execute_query.return_value = [
            {
                "entity_id": "1",
                "name": "EntityA",
                "type": "Person",
                "in_degree": 5,
                "out_degree": 3,
                "mention_count": 10,
            }
        ]

        result = await metrics_calculator.calculate_entity_degrees()

        assert len(result) == 1
        assert result[0].canonical_name == "EntityA"
        assert result[0].degree == 8

    @pytest.mark.asyncio
    async def test_find_orphan_entities(self, metrics_calculator, mock_neo4j_pool):
        """Test find_orphan_entities."""
        mock_neo4j_pool.execute_query.return_value = [
            {"name": "Orphan1", "type": "Person", "created_at": datetime.now(UTC)},
            {"name": "Orphan2", "type": "Org", "created_at": datetime.now(UTC)},
        ]

        result = await metrics_calculator.find_orphan_entities(limit=100)

        assert len(result) == 2
        assert result[0]["name"] == "Orphan1"

    @pytest.mark.asyncio
    async def test_get_high_degree_entities(self, metrics_calculator, mock_neo4j_pool):
        """Test get_high_degree_entities."""
        mock_neo4j_pool.execute_query.return_value = [
            {
                "name": "Hub",
                "type": "Person",
                "in_degree": 20,
                "out_degree": 15,
                "total_degree": 35,
            }
        ]

        result = await metrics_calculator.get_high_degree_entities(min_degree=10, limit=100)

        assert len(result) == 1
        assert result[0]["name"] == "Hub"
        assert result[0]["total_degree"] == 35

    @pytest.mark.asyncio
    async def test_calculate_modularity_with_edges(self, metrics_calculator, mock_neo4j_pool):
        """Test calculate_modularity with edges."""
        mock_neo4j_pool.execute_query.side_effect = [
            [  # edges
                {"source": "A", "target": "B", "weight": 1.0},
                {"source": "B", "target": "C", "weight": 1.0},
            ],
            [  # community assignments
                {"entity_name": "A", "community_id": "comm1"},
                {"entity_name": "B", "community_id": "comm1"},
                {"entity_name": "C", "community_id": "comm1"},
            ],
        ]

        result = await metrics_calculator.calculate_modularity()

        assert result is not None
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_calculate_modularity_no_edges(self, metrics_calculator, mock_neo4j_pool):
        """Test calculate_modularity with no edges."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await metrics_calculator.calculate_modularity()

        assert result == 0.0

    @pytest.mark.asyncio
    async def test_get_health_summary(self, metrics_calculator, mock_neo4j_pool):
        """Test get_health_summary."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 100}],  # entities
            [{"count": 50}],  # articles
            [{"count": 200}],  # relationships
            [{"count": 500}],  # mentions
            [{"count": 10}],  # orphans
            [{"avg_degree": 4.0}],
            [],
            [{"type": "Person", "count": 60}],
            [{"type": "WORKS_FOR", "count": 30}],
        ]

        result = await metrics_calculator.get_health_summary()

        assert "health_score" in result
        assert "status" in result
        assert "recommendations" in result

    def test_compute_health_score_empty(self, metrics_calculator):
        """Test _compute_health_score with empty graph."""
        metrics = GraphMetrics(total_entities=0)
        result = metrics_calculator._compute_health_score(metrics)

        assert result == 0.0

    def test_compute_health_score_healthy(self, metrics_calculator):
        """Test _compute_health_score with healthy graph."""
        metrics = GraphMetrics(
            total_entities=100,
            orphan_entities=5,  # 5% orphans
            largest_component_size=95,  # 95% connected
            average_degree=4.0,
        )
        result = metrics_calculator._compute_health_score(metrics)

        assert result >= 60  # Should be moderate to healthy

    def test_compute_health_score_degraded(self, metrics_calculator):
        """Test _compute_health_score with degraded graph."""
        metrics = GraphMetrics(
            total_entities=100,
            orphan_entities=50,  # 50% orphans
            largest_component_size=30,  # 30% connected
            average_degree=0.5,  # Low degree
        )
        result = metrics_calculator._compute_health_score(metrics)

        assert result < 70  # Should be moderate to degraded

    def test_get_health_status_labels(self, metrics_calculator):
        """Test _get_health_status returns correct labels."""
        from core.constants import GraphHealthStatus

        assert metrics_calculator._get_health_status(85) == GraphHealthStatus.HEALTHY.value
        assert metrics_calculator._get_health_status(65) == GraphHealthStatus.MODERATE.value
        assert metrics_calculator._get_health_status(45) == GraphHealthStatus.DEGRADED.value
        assert metrics_calculator._get_health_status(25) == GraphHealthStatus.CRITICAL.value

    def test_generate_recommendations_high_orphans(self, metrics_calculator):
        """Test recommendations for high orphan ratio."""
        metrics = GraphMetrics(
            total_entities=100,
            orphan_entities=20,  # 20% orphans
        )
        result = metrics_calculator._generate_recommendations(metrics)

        assert any("orphan" in r.lower() for r in result)

    def test_generate_recommendations_low_degree(self, metrics_calculator):
        """Test recommendations for low average degree."""
        metrics = GraphMetrics(
            total_entities=100,
            average_degree=1.0,
        )
        result = metrics_calculator._generate_recommendations(metrics)

        assert any("degree" in r.lower() for r in result)

    def test_generate_recommendations_many_components(self, metrics_calculator):
        """Test recommendations for many components."""
        metrics = GraphMetrics(
            total_entities=100,
            connected_components=15,
        )
        result = metrics_calculator._generate_recommendations(metrics)

        assert any("component" in r.lower() for r in result)

    def test_generate_recommendations_healthy(self, metrics_calculator):
        """Test recommendations for healthy graph."""
        metrics = GraphMetrics(
            total_entities=100,
            orphan_entities=2,
            average_degree=5.0,
            connected_components=3,
        )
        result = metrics_calculator._generate_recommendations(metrics)

        assert any("good" in r.lower() for r in result)

    def test_compute_modularity_empty(self, metrics_calculator):
        """Test _compute_modularity with empty inputs."""
        result = metrics_calculator._compute_modularity([], {})

        assert result == 0.0

    def test_compute_modularity_single_community(self, metrics_calculator):
        """Test _compute_modularity with single community."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = metrics_calculator._compute_modularity(edges, partitions)

        # Single community has modularity close to 0
        assert isinstance(result, float)

    def test_compute_modularity_multiple_communities(self, metrics_calculator):
        """Test _compute_modularity with multiple communities."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}

        result = metrics_calculator._compute_modularity(edges, partitions)

        # Two separate communities should have positive modularity
        assert result > 0

    @pytest.mark.asyncio
    async def test_generate_simple_partitions(self, metrics_calculator):
        """Test _generate_simple_partitions creates connected components."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("D", "E", 1.0),  # Separate component
        ]

        result = await metrics_calculator._generate_simple_partitions(edges)

        assert result["A"] == result["B"] == result["C"]
        assert result["D"] == result["E"]
        assert result["A"] != result["D"]
