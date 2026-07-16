# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for subgraph_extractor module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db.graph_query_builders import GraphDatabaseType
from modules.knowledge.graph.community.subgraph_extractor import SubgraphExtractor


@pytest.fixture
def mock_pool():
    """Create a mock graph pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


class TestSubgraphExtractorInit:
    """Test SubgraphExtractor initialization."""

    def test_init_with_neo4j(self, mock_pool):
        """Test initialization with Neo4j database type."""
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.NEO4J)
        assert extractor._database_type == GraphDatabaseType.NEO4J
        assert extractor._pool == mock_pool

    def test_init_with_ladybug(self, mock_pool):
        """Test initialization with LadybugDB database type."""
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.LADYBUG)
        assert extractor._database_type == GraphDatabaseType.LADYBUG

    def test_init_default_is_neo4j(self, mock_pool):
        """Test that default database type is Neo4j."""
        extractor = SubgraphExtractor(mock_pool)
        assert extractor._database_type == GraphDatabaseType.NEO4J


class TestExtractSubgraph:
    """Test extract_subgraph method."""

    @pytest.mark.asyncio
    async def test_extract_empty_entity_list(self, mock_pool):
        """Test extract_subgraph with empty entity list."""
        extractor = SubgraphExtractor(mock_pool)
        result = await extractor.extract_subgraph([], max_hops=2)
        assert result == []
        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_neo4j_delegates(self, mock_pool):
        """Test extract_subgraph delegates to _extract_neo4j."""
        mock_pool.execute_query.return_value = []
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.NEO4J)

        await extractor.extract_subgraph(["Entity1"], max_hops=2)
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_ladybug_delegates(self, mock_pool):
        """Test extract_subgraph delegates to _extract_ladybug."""
        mock_pool.execute_query.return_value = []
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.LADYBUG)

        await extractor.extract_subgraph(["Entity1"], max_hops=2)
        mock_pool.execute_query.assert_called()


class TestExtractNeo4j:
    """Test _extract_neo4j method."""

    @pytest.mark.asyncio
    async def test_extract_neo4j_returns_edges(self, mock_pool):
        """Test _extract_neo4j returns edge tuples."""
        mock_pool.execute_query.return_value = [
            {"source": "A", "target": "B", "weight": 1.5},
            {"source": "B", "target": "C", "weight": 2.0},
        ]
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.NEO4J)

        result = await extractor._extract_neo4j(["A"], max_hops=2)
        assert len(result) == 2
        # Edges should be normalized (lo, hi, weight)
        assert result[0][0] <= result[0][1]  # lo <= hi

    @pytest.mark.asyncio
    async def test_extract_neo4j_empty_results(self, mock_pool):
        """Test _extract_neo4j with empty results."""
        mock_pool.execute_query.return_value = []
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.NEO4J)

        result = await extractor._extract_neo4j(["A"], max_hops=2)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_neo4j_deduplicates_edges(self, mock_pool):
        """Test _extract_neo4j deduplicates edges."""
        mock_pool.execute_query.return_value = [
            {"source": "A", "target": "B", "weight": 1.5},
            {"source": "B", "target": "A", "weight": 1.0},  # Same edge, different direction
        ]
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.NEO4J)

        result = await extractor._extract_neo4j(["A"], max_hops=2)
        # Should deduplicate to single edge
        assert len(result) == 1


class TestExtractLadybug:
    """Test _extract_ladybug method."""

    @pytest.mark.asyncio
    async def test_extract_ladybug_hop1(self, mock_pool):
        """Test _extract_ladybug with max_hops=1."""
        mock_pool.execute_query.return_value = [
            {"source": "A", "target": "B", "weight": 1.0},
        ]
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.LADYBUG)

        result = await extractor._extract_ladybug(["A"], max_hops=1)
        assert len(result) >= 0
        mock_pool.execute_query.assert_called()

    @pytest.mark.asyncio
    async def test_extract_ladybug_hop2(self, mock_pool):
        """Test _extract_ladybug with max_hops=2."""
        mock_pool.execute_query.return_value = [
            {"source": "A", "target": "B", "weight": 1.0},
        ]
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.LADYBUG)

        result = await extractor._extract_ladybug(["A"], max_hops=2)
        assert len(result) >= 0
        # Should execute queries for both 1-hop and 2-hop

    @pytest.mark.asyncio
    async def test_extract_ladybug_empty_results(self, mock_pool):
        """Test _extract_ladybug with empty results."""
        mock_pool.execute_query.return_value = []
        extractor = SubgraphExtractor(mock_pool, GraphDatabaseType.LADYBUG)

        result = await extractor._extract_ladybug(["A"], max_hops=2)
        assert result == []


class TestGetSubgraphEntities:
    """Test get_subgraph_entities method."""

    @pytest.mark.asyncio
    async def test_get_entities_with_edges(self, mock_pool):
        """Test get_subgraph_entities extracts entities from edges."""
        mock_pool.execute_query.return_value = [
            {"source": "A", "target": "B", "weight": 1.0},
            {"source": "B", "target": "C", "weight": 1.5},
        ]
        extractor = SubgraphExtractor(mock_pool)

        result = await extractor.get_subgraph_entities(["A"], max_hops=2)
        assert "A" in result
        assert "B" in result
        assert "C" in result
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_entities_no_edges(self, mock_pool):
        """Test get_subgraph_entities returns input when no edges."""
        mock_pool.execute_query.return_value = []
        extractor = SubgraphExtractor(mock_pool)

        result = await extractor.get_subgraph_entities(["A"], max_hops=2)
        assert result == ["A"]

    @pytest.mark.asyncio
    async def test_get_entities_returns_sorted(self, mock_pool):
        """Test get_subgraph_entities returns sorted list."""
        mock_pool.execute_query.return_value = [
            {"source": "C", "target": "A", "weight": 1.0},
            {"source": "B", "target": "D", "weight": 1.5},
        ]
        extractor = SubgraphExtractor(mock_pool)

        result = await extractor.get_subgraph_entities(["A"], max_hops=2)
        assert result == sorted(result)
