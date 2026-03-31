# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for semantic edge type adaptation in community detection queries."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.graph.community_detector import CommunityDetector
from modules.knowledge.graph.incremental_community_updater import IncrementalCommunityUpdater


@pytest.fixture
def mock_pool():
    """Mock Neo4j pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


class TestCommunityDetectorEdgeQuery:
    """Tests for CommunityDetector._build_edge_list() semantic edge matching."""

    @pytest.mark.asyncio
    async def test_edge_query_excludes_non_entity_relations(self, mock_pool):
        """_build_edge_list() excludes HAS_ENTITY, MENTIONS, FOLLOWED_BY."""
        mock_pool.execute_query.return_value = [
            {"source": "A", "target": "B", "weight": 1.0},
        ]

        detector = CommunityDetector(pool=mock_pool)
        await detector._build_edge_list()

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]

        assert "NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']" in query
        assert "RELATED_TO" not in query

    @pytest.mark.asyncio
    async def test_edge_query_filters_pruned_entities(self, mock_pool):
        """_build_edge_list() excludes pruned entities."""
        mock_pool.execute_query.return_value = []

        detector = CommunityDetector(pool=mock_pool)
        await detector._build_edge_list()

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]

        assert "pruned" in query

    @pytest.mark.asyncio
    async def test_edge_query_matches_all_entity_pairs(self, mock_pool):
        """_build_edge_list() matches (e1:Entity)-[r]->(e2:Entity) pattern."""
        mock_pool.execute_query.return_value = []

        detector = CommunityDetector(pool=mock_pool)
        await detector._build_edge_list()

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]

        assert "(e1:Entity)-[r]->(e2:Entity)" in query

    @pytest.mark.asyncio
    async def test_orphan_query_uses_semantic_exclusion(self, mock_pool):
        """_get_orphan_entities() uses semantic relationship exclusion."""
        mock_pool.execute_query.return_value = [{"name": "OrphanEntity"}]

        detector = CommunityDetector(pool=mock_pool)
        result = await detector._get_orphan_entities()

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]

        assert "HAS_ENTITY" in query
        assert "MENTIONS" in query
        assert "FOLLOWED_BY" in query
        assert "RELATED_TO" not in query or "NOT" in query


class TestUpdaterEdgeQuery:
    """Tests for IncrementalCommunityUpdater edge query adaptation."""

    @pytest.mark.asyncio
    async def test_extract_subgraph_uses_semantic_query(self, mock_pool):
        """_extract_subgraph() uses generic relationship matching."""
        mock_pool.execute_query.return_value = [
            {"id1": "id1", "id2": "id2", "weight": 1.0},
        ]

        updater = IncrementalCommunityUpdater(pool=mock_pool)
        await updater._extract_subgraph(["comm1"])

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]

        assert "NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']" in query
        assert "RELATED_TO" not in query

    @pytest.mark.asyncio
    async def test_calculate_modularity_uses_semantic_query(self, mock_pool):
        """_calculate_modularity() uses generic relationship matching."""
        mock_pool.execute_query.return_value = []

        updater = IncrementalCommunityUpdater(pool=mock_pool)
        await updater._calculate_modularity()

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]

        assert "NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']" in query
        # Should NOT have explicit RELATED_TO
        assert "RELATED_TO" not in query

    @pytest.mark.asyncio
    async def test_identify_affected_communities_uses_semantic_query(self, mock_pool):
        """_identify_affected_communities() uses generic relationship matching."""
        mock_pool.execute_query.return_value = []

        updater = IncrementalCommunityUpdater(pool=mock_pool)
        await updater._identify_affected_communities(["Entity1"])

        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]

        assert "NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']" in query
        assert "RELATED_TO" not in query

    @pytest.mark.asyncio
    async def test_create_communities_uses_semantic_query(self, mock_pool):
        """_create_communities_for_entities() uses generic relationship matching."""
        mock_pool.execute_query.return_value = [
            {"entity": "E1", "neighbors": []},
        ]

        updater = IncrementalCommunityUpdater(pool=mock_pool)
        result = await updater._create_communities_for_entities(["E1"])

        # First call is the relationship query with semantic exclusion
        first_call = mock_pool.execute_query.call_args_list[0]
        query = first_call[0][0]

        assert "NOT type(r) IN ['HAS_ENTITY', 'MENTIONS', 'FOLLOWED_BY']" in query
        assert "RELATED_TO" not in query
