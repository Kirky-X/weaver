"""Unit tests for Graph Quality Metrics module."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from modules.graph_store.metrics import (
    GraphQualityMetrics,
    GraphMetrics,
    EntityDegree,
    ConnectedComponent,
)


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
        metrics._pool.execute_query = AsyncMock(return_value=[
            {"entity": "A", "type": "人物", "neighbors": ["B", "C"]},
            {"entity": "B", "type": "组织", "neighbors": ["A"]},
            {"entity": "C", "type": "人物", "neighbors": ["A"]},
        ])

        result = await metrics.get_connected_components()

        assert len(result) == 1
        assert result[0].size == 3

    @pytest.mark.asyncio
    async def test_get_connected_components_multiple(self, metrics):
        """Test get_connected_components with multiple components."""
        metrics._pool.execute_query = AsyncMock(return_value=[
            {"entity": "A", "type": "人物", "neighbors": ["B"]},
            {"entity": "B", "type": "组织", "neighbors": ["A"]},
            {"entity": "C", "type": "人物", "neighbors": ["D"]},
            {"entity": "D", "type": "组织", "neighbors": ["C"]},
        ])

        result = await metrics.get_connected_components()

        assert len(result) == 2
        assert all(c.size == 2 for c in result)

    @pytest.mark.asyncio
    async def test_get_largest_connected_component(self, metrics):
        """Test get_largest_connected_component."""
        metrics._pool.execute_query = AsyncMock(return_value=[
            {"entity": "A", "type": "人物", "neighbors": ["B", "C", "D"]},
            {"entity": "B", "type": "组织", "neighbors": ["A"]},
            {"entity": "C", "type": "人物", "neighbors": ["A"]},
            {"entity": "D", "type": "地点", "neighbors": ["A"]},
            {"entity": "E", "type": "人物", "neighbors": []},
        ])

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
        metrics._pool.execute_query = AsyncMock(return_value=[
            {"name": "Orphan1", "type": "人物", "created_at": datetime.now()},
            {"name": "Orphan2", "type": "组织", "created_at": datetime.now()},
        ])

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
        metrics._pool.execute_query = AsyncMock(return_value=[
            {"name": "Hub1", "type": "人物", "in_degree": 10, "out_degree": 5, "total_degree": 15},
            {"name": "Hub2", "type": "组织", "in_degree": 8, "out_degree": 8, "total_degree": 16},
        ])

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
        metrics._pool.execute_query = AsyncMock(return_value=[
            {"source": "A", "target": "B", "weight": 1.0},
            {"source": "B", "target": "C", "weight": 1.0},
            {"source": "C", "target": "A", "weight": 1.0},
        ])

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
        metrics._pool.execute_query = AsyncMock(return_value=[
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
        ])

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
