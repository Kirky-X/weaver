# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Graph Quality Metrics module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.graph.metrics import (
    ConnectedComponent,
    EntityDegree,
    GraphMetrics,
    GraphQualityMetrics,
    _dfs_component,
)


class TestDFSComponent:
    """Test _dfs_component helper function."""

    def test_single_node(self):
        """Test DFS on a single isolated node."""
        adjacency = {"A": set()}
        visited: set[str] = set()

        result = _dfs_component("A", adjacency, visited)

        assert result == {"A"}
        assert visited == {"A"}

    def test_connected_component(self):
        """Test DFS finds all connected nodes."""
        adjacency = {
            "A": {"B", "C"},
            "B": {"A", "D"},
            "C": {"A"},
            "D": {"B"},
            "E": {"F"},
            "F": {"E"},
        }
        visited: set[str] = set()

        result = _dfs_component("A", adjacency, visited)

        assert result == {"A", "B", "C", "D"}
        assert "E" not in result
        assert "F" not in result

    def test_already_visited_nodes_skipped(self):
        """Test that already visited nodes are not reprocessed."""
        adjacency = {
            "A": {"B"},
            "B": {"A"},
        }
        visited: set[str] = {"B"}

        result = _dfs_component("A", adjacency, visited)

        assert result == {"A"}
        # B should not be added again

    def test_empty_adjacency(self):
        """Test DFS with node not in adjacency dict."""
        adjacency: dict[str, set[str]] = {}
        visited: set[str] = set()

        result = _dfs_component("X", adjacency, visited)

        assert result == {"X"}

    def test_complex_graph(self):
        """Test DFS on complex graph with multiple branches."""
        adjacency = {
            "1": {"2", "3"},
            "2": {"1", "4", "5"},
            "3": {"1", "6"},
            "4": {"2"},
            "5": {"2"},
            "6": {"3"},
            "7": {"8"},
            "8": {"7"},
        }
        visited: set[str] = set()

        result = _dfs_component("1", adjacency, visited)

        assert result == {"1", "2", "3", "4", "5", "6"}
        assert len(result) == 6

    def test_mutates_visited_in_place(self):
        """Test that visited set is modified in place."""
        adjacency = {"A": {"B"}, "B": {"A"}}
        visited: set[str] = set()

        _dfs_component("A", adjacency, visited)

        assert "A" in visited
        assert "B" in visited


class TestGraphMetrics:
    """Test GraphMetrics dataclass."""

    def test_default_values(self):
        """Test default initialization."""
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

    def test_to_dict(self):
        """Test to_dict serialization."""
        metrics = GraphMetrics(
            total_entities=100,
            total_articles=50,
            total_relationships=200,
            total_mentions=300,
            connected_components=5,
            largest_component_size=80,
            average_degree=4.0,
            modularity_score=0.65,
            orphan_entities=10,
            high_degree_entities=[{"name": "Entity1", "total_degree": 20}],
            entity_type_distribution={"人物": 50, "组织": 30},
            relationship_type_distribution={"合作": 100},
        )

        result = metrics.to_dict()

        assert result["total_entities"] == 100
        assert result["total_articles"] == 50
        assert result["total_relationships"] == 200
        assert result["total_mentions"] == 300
        assert result["connected_components"] == 5
        assert result["largest_component_size"] == 80
        assert result["average_degree"] == 4.0
        assert result["modularity_score"] == 0.65
        assert result["orphan_entities"] == 10
        assert len(result["high_degree_entities"]) == 1
        assert result["entity_type_distribution"]["人物"] == 50
        assert "computed_at" in result


class TestEntityDegree:
    """Test EntityDegree dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        degree = EntityDegree(
            entity_id="id1",
            canonical_name="Test Entity",
            entity_type="人物",
        )

        assert degree.in_degree == 0
        assert degree.out_degree == 0
        assert degree.mention_count == 0
        assert degree.total_degree == 0

    def test_degree_property(self):
        """Test degree property calculation."""
        degree = EntityDegree(
            entity_id="id1",
            canonical_name="Test",
            entity_type="人物",
            in_degree=5,
            out_degree=3,
        )

        assert degree.degree == 8


class TestConnectedComponent:
    """Test ConnectedComponent dataclass."""

    def test_initialization(self):
        """Test initialization."""
        component = ConnectedComponent(
            component_id=0,
            node_ids=["node1", "node2", "node3"],
            size=3,
            entity_types={"人物": 2, "组织": 1},
        )

        assert component.component_id == 0
        assert component.size == 3
        assert len(component.node_ids) == 3
        assert component.entity_types["人物"] == 2


class TestGraphQualityMetricsInit:
    """Test GraphQualityMetrics initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        metrics = GraphQualityMetrics(mock_pool)

        assert metrics._pool == mock_pool


class TestGraphQualityMetricsCalculateAll:
    """Test calculate_all_metrics method."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_calculate_all_empty_graph(self, metrics):
        """Test calculation on empty graph."""
        metrics._pool.execute_query = AsyncMock(return_value=[])

        result = await metrics.calculate_all_metrics()

        assert result.total_entities == 0
        assert result.total_articles == 0
        assert result.total_relationships == 0

    @pytest.mark.asyncio
    async def test_calculate_all_with_data(self, metrics):
        """Test calculation with data - verifies method runs without error."""
        call_count = 0

        def mock_query(query, params=None):
            nonlocal call_count
            call_count += 1
            q = query.lower().strip()
            if q.startswith("match (e:entity)") and "not" in q and "mentions" in q:
                return [{"count": 5}]
            if "count(e)" in q and "entity" in q:
                return [{"count": 100}]
            if "count(a)" in q and "article" in q:
                return [{"count": 50}]
            if "count(r)" in q and "related_to" in q:
                return [{"count": 200}]
            if "count(r)" in q and "mentions" in q:
                return [{"count": 300}]
            return [{"count": 0}]

        metrics._pool.execute_query = AsyncMock(side_effect=mock_query)

        result = await metrics.calculate_all_metrics()

        assert result.total_mentions == 300
        assert result.orphan_entities == 5


class TestGraphQualityMetricsConnectedComponents:
    """Test connected components methods."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_get_connected_components_empty(self, metrics):
        """Test get_connected_components on empty graph."""
        metrics._pool.execute_query = AsyncMock(return_value=[])

        result = await metrics.get_connected_components()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_connected_components_single(self, metrics):
        """Test get_connected_components with single component."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"entity": "A", "type": "人物", "neighbors": ["B", "C"]},
                {"entity": "B", "type": "组织", "neighbors": ["A"]},
                {"entity": "C", "type": "人物", "neighbors": ["A"]},
            ]
        )

        result = await metrics.get_connected_components()

        assert len(result) == 1
        assert result[0].size == 3

    @pytest.mark.asyncio
    async def test_get_connected_components_multiple(self, metrics):
        """Test get_connected_components with multiple components."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"entity": "A", "type": "人物", "neighbors": ["B"]},
                {"entity": "B", "type": "组织", "neighbors": ["A"]},
                {"entity": "C", "type": "人物", "neighbors": ["D"]},
                {"entity": "D", "type": "组织", "neighbors": ["C"]},
            ]
        )

        result = await metrics.get_connected_components()

        assert len(result) == 2
        assert all(c.size == 2 for c in result)

    @pytest.mark.asyncio
    async def test_get_largest_connected_component(self, metrics):
        """Test get_largest_connected_component."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"entity": "A", "type": "人物", "neighbors": ["B", "C", "D"]},
                {"entity": "B", "type": "组织", "neighbors": ["A"]},
                {"entity": "C", "type": "人物", "neighbors": ["A"]},
                {"entity": "D", "type": "地点", "neighbors": ["A"]},
                {"entity": "E", "type": "人物", "neighbors": []},
            ]
        )

        result = await metrics.get_largest_connected_component()

        assert result is not None
        assert result.size == 4


class TestGraphQualityMetricsOrphans:
    """Test orphan entity methods."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_find_orphan_entities(self, metrics):
        """Test find_orphan_entities."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"name": "Orphan1", "type": "人物", "created_at": datetime.now()},
                {"name": "Orphan2", "type": "组织", "created_at": datetime.now()},
            ]
        )

        result = await metrics.find_orphan_entities(limit=10)

        assert len(result) == 2
        assert result[0]["name"] == "Orphan1"

    @pytest.mark.asyncio
    async def test_find_orphan_entities_empty(self, metrics):
        """Test find_orphan_entities when none exist."""
        metrics._pool.execute_query = AsyncMock(return_value=[])

        result = await metrics.find_orphan_entities()

        assert result == []


class TestGraphQualityMetricsHighDegree:
    """Test high-degree entity methods."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_get_high_degree_entities(self, metrics):
        """Test get_high_degree_entities."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "name": "Hub1",
                    "type": "人物",
                    "in_degree": 10,
                    "out_degree": 5,
                    "total_degree": 15,
                },
                {
                    "name": "Hub2",
                    "type": "组织",
                    "in_degree": 8,
                    "out_degree": 8,
                    "total_degree": 16,
                },
            ]
        )

        result = await metrics.get_high_degree_entities(min_degree=10, limit=50)

        assert len(result) == 2
        assert result[0]["total_degree"] >= 10

    @pytest.mark.asyncio
    async def test_get_high_degree_entities_none(self, metrics):
        """Test get_high_degree_entities when none meet threshold."""
        metrics._pool.execute_query = AsyncMock(return_value=[])

        result = await metrics.get_high_degree_entities(min_degree=100)

        assert result == []


class TestGraphQualityMetricsModularity:
    """Test modularity calculation methods."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_calculate_modularity_empty(self, metrics):
        """Test calculate_modularity on empty graph."""
        metrics._pool.execute_query = AsyncMock(return_value=[])

        result = await metrics.calculate_modularity()

        assert result == 0.0

    @pytest.mark.asyncio
    async def test_calculate_modularity_with_edges(self, metrics):
        """Test calculate_modularity with edges."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 1.0},
                {"source": "B", "target": "C", "weight": 1.0},
                {"source": "C", "target": "A", "weight": 1.0},
            ]
        )

        result = await metrics.calculate_modularity()

        assert -1 <= result <= 1

    def test_compute_modularity_single_community(self, metrics):
        """Test _compute_modularity with single community."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("C", "A", 1.0),
        ]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = metrics._compute_modularity(edges, partitions)

        assert result >= 0

    def test_compute_modularity_two_communities(self, metrics):
        """Test _compute_modularity with two communities."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("D", "E", 1.0),
            ("E", "F", 1.0),
        ]
        partitions = {"A": 0, "B": 0, "C": 0, "D": 1, "E": 1, "F": 1}

        result = metrics._compute_modularity(edges, partitions)

        assert result >= 0


class TestGraphQualityMetricsHealthSummary:
    """Test health summary methods."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_get_health_summary_empty(self, metrics):
        """Test get_health_summary on empty graph."""
        metrics._pool.execute_query = AsyncMock(return_value=[])

        result = await metrics.get_health_summary()

        assert result["health_score"] == 0.0
        assert result["status"] == "critical"

    @pytest.mark.asyncio
    async def test_get_health_summary_healthy(self, metrics):
        """Test get_health_summary on healthy graph."""

        def mock_query(query, params=None):
            if "entity" in query.lower() and "count" in query.lower():
                return [{"count": 100}]
            if "article" in query.lower():
                return [{"count": 50}]
            if "related_to" in query.lower() and "count" in query.lower():
                return [{"count": 200}]
            if "mentions" in query.lower():
                return [{"count": 300}]
            if "orphan" in query.lower():
                return [{"count": 2}]
            if "avg" in query.lower():
                return [{"avg_degree": 4.5}]
            if "component" in query.lower():
                return [{"id": 1, "size": 95}]
            return []

        metrics._pool.execute_query = AsyncMock(side_effect=mock_query)

        result = await metrics.get_health_summary()

        assert result["entity_count"] == 100
        assert result["status"] in ["healthy", "moderate", "critical"]

    def test_compute_health_score_empty(self, metrics):
        """Test _compute_health_score with empty graph."""
        m = GraphMetrics(total_entities=0)
        result = metrics._compute_health_score(m)
        assert result == 0.0

    def test_compute_health_score_perfect(self, metrics):
        """Test _compute_health_score with perfect graph."""
        m = GraphMetrics(
            total_entities=100,
            orphan_entities=0,
            largest_component_size=100,
            average_degree=5.0,
        )
        result = metrics._compute_health_score(m)
        assert result == 100.0

    def test_compute_health_score_with_orphans(self, metrics):
        """Test _compute_health_score with orphans."""
        m = GraphMetrics(
            total_entities=100,
            orphan_entities=20,
            largest_component_size=80,
            average_degree=3.0,
        )
        result = metrics._compute_health_score(m)
        assert result < 100

    def test_get_health_status_labels(self, metrics):
        """Test _get_health_status returns correct labels."""
        assert metrics._get_health_status(85) == "healthy"
        assert metrics._get_health_status(70) == "moderate"
        assert metrics._get_health_status(50) == "degraded"
        assert metrics._get_health_status(30) == "critical"

    def test_generate_recommendations_no_issues(self, metrics):
        """Test _generate_recommendations with healthy graph."""
        m = GraphMetrics(
            total_entities=100,
            orphan_entities=2,
            average_degree=5.0,
            connected_components=3,
        )
        result = metrics._generate_recommendations(m)
        assert "good" in result[0].lower()

    def test_generate_recommendations_high_orphans(self, metrics):
        """Test _generate_recommendations with high orphan ratio."""
        m = GraphMetrics(
            total_entities=100,
            orphan_entities=20,
            average_degree=5.0,
            connected_components=3,
        )
        result = metrics._generate_recommendations(m)
        assert any("orphan" in r.lower() for r in result)

    def test_generate_recommendations_low_degree(self, metrics):
        """Test _generate_recommendations with low average degree."""
        m = GraphMetrics(
            total_entities=100,
            orphan_entities=0,
            average_degree=1.0,
            connected_components=3,
        )
        result = metrics._generate_recommendations(m)
        assert any("degree" in r.lower() or "sparse" in r.lower() for r in result)

    def test_generate_recommendations_many_components(self, metrics):
        """Test _generate_recommendations with many components."""
        m = GraphMetrics(
            total_entities=100,
            orphan_entities=0,
            average_degree=5.0,
            connected_components=20,
        )
        result = metrics._generate_recommendations(m)
        assert any("component" in r.lower() for r in result)


class TestGraphQualityMetricsEntityDegrees:
    """Test entity degree calculation methods."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_calculate_entity_degrees(self, metrics):
        """Test calculate_entity_degrees."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "entity_id": "id1",
                    "name": "Entity1",
                    "type": "人物",
                    "in_degree": 5,
                    "out_degree": 3,
                    "mention_count": 10,
                },
                {
                    "entity_id": "id2",
                    "name": "Entity2",
                    "type": "组织",
                    "in_degree": 2,
                    "out_degree": 8,
                    "mention_count": 5,
                },
            ]
        )

        result = await metrics.calculate_entity_degrees()

        assert len(result) == 2
        assert result[0].canonical_name == "Entity1"
        assert result[0].in_degree == 5
        assert result[0].out_degree == 3
        assert result[0].total_degree == 8


class TestGraphQualityMetricsDistributions:
    """Test distribution calculation methods."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_calculate_distributions(self, metrics):
        """Test _calculate_distributions."""

        def mock_query(query, params=None):
            if "e.type" in query:
                return [
                    {"type": "人物", "count": 50},
                    {"type": "组织", "count": 30},
                    {"type": "地点", "count": 20},
                ]
            if "r.relation_type" in query:
                return [
                    {"type": "合作", "count": 100},
                    {"type": "竞争", "count": 50},
                ]
            return []

        metrics._pool.execute_query = AsyncMock(side_effect=mock_query)

        m = GraphMetrics()
        await metrics._calculate_distributions(m)

        assert m.entity_type_distribution["人物"] == 50
        assert m.entity_type_distribution["组织"] == 30
        assert m.relationship_type_distribution["合作"] == 100


class TestGraphQualityMetricsDegreeEdgeCases:
    """Test degree calculation edge cases."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_calculate_entity_degrees_with_isolated_nodes(self, metrics):
        """Test calculate_entity_degrees includes isolated nodes with zero degree."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "entity_id": "id1",
                    "name": "Connected",
                    "type": "人物",
                    "in_degree": 5,
                    "out_degree": 3,
                    "mention_count": 10,
                },
                {
                    "entity_id": "id2",
                    "name": "Isolated",
                    "type": "组织",
                    "in_degree": 0,
                    "out_degree": 0,
                    "mention_count": 0,
                },
            ]
        )

        result = await metrics.calculate_entity_degrees()

        assert len(result) == 2
        isolated = next(e for e in result if e.canonical_name == "Isolated")
        assert isolated.in_degree == 0
        assert isolated.out_degree == 0
        assert isolated.degree == 0

    @pytest.mark.asyncio
    async def test_calculate_entity_degrees_empty_graph(self, metrics):
        """Test calculate_entity_degrees on empty graph."""
        metrics._pool.execute_query = AsyncMock(return_value=[])

        result = await metrics.calculate_entity_degrees()

        assert result == []

    @pytest.mark.asyncio
    async def test_calculate_entity_degrees_high_in_degree(self, metrics):
        """Test entity with high in-degree (hub receiving many connections)."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "entity_id": "hub",
                    "name": "Hub",
                    "type": "组织",
                    "in_degree": 100,
                    "out_degree": 5,
                    "mention_count": 200,
                },
            ]
        )

        result = await metrics.calculate_entity_degrees()

        assert result[0].in_degree == 100
        assert result[0].out_degree == 5
        assert result[0].degree == 105

    @pytest.mark.asyncio
    async def test_calculate_entity_degrees_high_out_degree(self, metrics):
        """Test entity with high out-degree (hub making many connections)."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "entity_id": "source",
                    "name": "Source",
                    "type": "人物",
                    "in_degree": 2,
                    "out_degree": 50,
                    "mention_count": 100,
                },
            ]
        )

        result = await metrics.calculate_entity_degrees()

        assert result[0].out_degree == 50
        assert result[0].degree == 52


class TestGraphQualityMetricsModularityEdgeCases:
    """Test modularity calculation edge cases."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    def test_compute_modularity_zero_weight_edges(self, metrics):
        """Test _compute_modularity with zero weight edges."""
        edges = [
            ("A", "B", 0.0),
            ("B", "C", 0.0),
        ]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = metrics._compute_modularity(edges, partitions)

        assert result == 0.0

    def test_compute_modularity_weighted_edges(self, metrics):
        """Test _compute_modularity with weighted edges."""
        edges = [
            ("A", "B", 2.0),
            ("B", "C", 3.0),
            ("C", "A", 1.5),
            ("D", "E", 4.0),
            ("E", "F", 2.5),
        ]
        partitions = {"A": 0, "B": 0, "C": 0, "D": 1, "E": 1, "F": 1}

        result = metrics._compute_modularity(edges, partitions)

        assert -1 <= result <= 1

    def test_compute_modularity_empty_partitions(self, metrics):
        """Test _compute_modularity with empty partitions."""
        edges = [("A", "B", 1.0)]
        partitions: dict[str, int] = {}

        result = metrics._compute_modularity(edges, partitions)

        assert result == 0.0

    def test_compute_modularity_missing_nodes_in_partitions(self, metrics):
        """Test _compute_modularity when some nodes are not in partitions."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
        ]
        partitions = {"A": 0, "B": 0}  # C is missing

        result = metrics._compute_modularity(edges, partitions)

        # Should still compute but ignore edges with missing partitions
        assert isinstance(result, float)

    def test_compute_modularity_high_resolution(self, metrics):
        """Test _compute_modularity with high resolution parameter."""
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("C", "A", 1.0),
        ]
        partitions = {"A": 0, "B": 0, "C": 0}

        result_default = metrics._compute_modularity(edges, partitions, resolution=1.0)
        result_high = metrics._compute_modularity(edges, partitions, resolution=2.0)

        # Higher resolution should give different results
        assert isinstance(result_default, float)
        assert isinstance(result_high, float)

    @pytest.mark.asyncio
    async def test_calculate_modularity_with_weighted_edges(self, metrics):
        """Test calculate_modularity with edge weights."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"source": "A", "target": "B", "weight": 5.0},
                {"source": "B", "target": "C", "weight": 2.0},
                {"source": "C", "target": "A", "weight": 3.0},
            ]
        )

        result = await metrics.calculate_modularity()

        assert -1 <= result <= 1


class TestGraphQualityMetricsCommunityMetrics:
    """Test community detection metrics."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_get_connected_components_size_distribution(self, metrics):
        """Test that connected components are sorted by size."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"entity": "A", "type": "人物", "neighbors": ["B"]},
                {"entity": "B", "type": "组织", "neighbors": ["A"]},
                {"entity": "C", "type": "人物", "neighbors": ["D", "E", "F"]},
                {"entity": "D", "type": "组织", "neighbors": ["C"]},
                {"entity": "E", "type": "地点", "neighbors": ["C"]},
                {"entity": "F", "type": "人物", "neighbors": ["C"]},
                {"entity": "G", "type": "组织", "neighbors": []},
            ]
        )

        result = await metrics.get_connected_components()

        # Should be sorted by size descending
        sizes = [c.size for c in result]
        assert sizes == sorted(sizes, reverse=True)
        # Largest should be C-D-E-F component
        assert result[0].size == 4

    @pytest.mark.asyncio
    async def test_get_connected_components_entity_type_distribution(self, metrics):
        """Test that components include entity type distribution."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"entity": "A", "type": "人物", "neighbors": ["B", "C"]},
                {"entity": "B", "type": "组织", "neighbors": ["A"]},
                {"entity": "C", "type": "人物", "neighbors": ["A"]},
            ]
        )

        result = await metrics.get_connected_components()

        assert len(result) == 1
        assert result[0].entity_types["人物"] == 2
        assert result[0].entity_types["组织"] == 1

    @pytest.mark.asyncio
    async def test_component_metrics_isolated_entity(self, metrics):
        """Test component metrics with isolated entities."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"entity": "Isolated1", "type": "人物", "neighbors": []},
                {"entity": "Isolated2", "type": "组织", "neighbors": []},
                {"entity": "Connected", "type": "地点", "neighbors": ["Partner"]},
                {"entity": "Partner", "type": "人物", "neighbors": ["Connected"]},
            ]
        )

        result = await metrics.get_connected_components()

        # Should have 3 components: 2 isolated + 1 connected pair
        assert len(result) == 3
        isolated_sizes = [c.size for c in result if c.size == 1]
        assert len(isolated_sizes) == 2


class TestGraphQualityMetricsHighDegreeEdgeCases:
    """Test high-degree entity edge cases."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_get_high_degree_entities_with_weights(self, metrics):
        """Test that high-degree entities are returned from query."""
        # Mock returns data as SQL would (ordered by total_degree DESC)
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "name": "Hub1",
                    "type": "人物",
                    "in_degree": 20,
                    "out_degree": 5,
                    "total_degree": 25,
                },
                {
                    "name": "Hub3",
                    "type": "地点",
                    "in_degree": 15,
                    "out_degree": 8,
                    "total_degree": 23,
                },
                {
                    "name": "Hub2",
                    "type": "组织",
                    "in_degree": 10,
                    "out_degree": 10,
                    "total_degree": 20,
                },
            ]
        )

        result = await metrics.get_high_degree_entities(min_degree=10)

        assert len(result) == 3
        # SQL orders by total_degree DESC, so mock reflects that
        assert result[0]["total_degree"] == 25
        assert result[1]["total_degree"] == 23
        assert result[2]["total_degree"] == 20

    @pytest.mark.asyncio
    async def test_get_high_degree_entities_threshold_boundary(self, metrics):
        """Test entities exactly at threshold are included."""
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "name": "Exact",
                    "type": "人物",
                    "in_degree": 10,
                    "out_degree": 0,
                    "total_degree": 10,
                },
                {
                    "name": "Above",
                    "type": "组织",
                    "in_degree": 11,
                    "out_degree": 0,
                    "total_degree": 11,
                },
            ]
        )

        result = await metrics.get_high_degree_entities(min_degree=10)

        assert len(result) == 2


class TestGraphQualityMetricsOrphanEdgeCases:
    """Test orphan entity edge cases."""

    @pytest.fixture
    def metrics(self):
        """Create GraphQualityMetrics instance."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock()
        return GraphQualityMetrics(mock_pool)

    @pytest.mark.asyncio
    async def test_find_orphan_entities_with_limit(self, metrics):
        """Test that limit is passed correctly to query."""
        from datetime import timezone

        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"name": f"Orphan{i}", "type": "人物", "created_at": datetime.now(timezone.utc)}
                for i in range(5)
            ]
        )

        result = await metrics.find_orphan_entities(limit=5)

        assert len(result) == 5
        # Verify limit was passed to query
        call_args = metrics._pool.execute_query.call_args
        assert call_args[0][1]["limit"] == 5

    @pytest.mark.asyncio
    async def test_find_orphan_entities_datetime_conversion(self, metrics):
        """Test that datetime objects are converted to isoformat."""
        dt = datetime.now()
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"name": "Orphan", "type": "人物", "created_at": dt},
            ]
        )

        result = await metrics.find_orphan_entities()

        assert result[0]["created_at"] == dt.isoformat()

    @pytest.mark.asyncio
    async def test_find_orphan_entities_string_datetime(self, metrics):
        """Test that string datetimes are preserved."""
        dt_str = "2025-01-01T00:00:00"
        metrics._pool.execute_query = AsyncMock(
            return_value=[
                {"name": "Orphan", "type": "人物", "created_at": dt_str},
            ]
        )

        result = await metrics.find_orphan_entities()

        assert result[0]["created_at"] == dt_str
