# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for community article_count backfill (R3 fix).

Verifies that article_count is backfilled on Community nodes after both
incremental update and full rebuild, traversing the
Article-[:MENTIONS]->Entity<-[:HAS_ENTITY]-Community path.

Covers two call sites:
1. SubgraphClusteringService._update_article_counts (called by
   run_full_rebuild and run_incremental_update)
2. CommunityDetector.rebuild_communities (called by the
   /api/v1/admin/communities/rebuild endpoint — the primary user-facing
   trigger, which was initially missed in the R3 fix)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.graph.community.updater_clustering import (
    SubgraphClusteringService,
)


@pytest.fixture
def mock_pool():
    """Mock GraphPool with execute_query tracking."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def mock_collaborators():
    """Mock collaborators required by SubgraphClusteringService constructor."""
    return {
        "modularity_calculator": MagicMock(),
        "diff_writer": MagicMock(),
        "updater": MagicMock(),
    }


@pytest.fixture
def clustering_service(mock_pool, mock_collaborators):
    """Create SubgraphClusteringService with mocked dependencies."""
    return SubgraphClusteringService(
        pool=mock_pool,
        max_subgraph_size=2000,
        database_type="neo4j",
        llm_client=None,
        modularity_calculator=mock_collaborators["modularity_calculator"],
        diff_writer=mock_collaborators["diff_writer"],
        updater=mock_collaborators["updater"],
    )


class TestUpdateArticleCounts:
    """Tests for _update_article_counts method (R3 fix)."""

    @pytest.mark.asyncio
    async def test_executes_backfill_query(self, clustering_service, mock_pool):
        """Test that _update_article_counts executes the Cypher backfill query."""
        await clustering_service._update_article_counts()

        mock_pool.execute_query.assert_awaited_once()
        call_args = mock_pool.execute_query.call_args
        query_text = call_args.args[0] if call_args.args else call_args.kwargs.get("query", "")

        assert (
            "MATCH (c:Community)-[:HAS_ENTITY]->(e:Entity)<-[:MENTIONS]-(a:Article)" in query_text
        )
        assert "count(DISTINCT a) AS article_count" in query_text
        assert "SET c.article_count = article_count" in query_text

    @pytest.mark.asyncio
    async def test_does_not_raise_on_query_failure(self, clustering_service, mock_pool):
        """Test that query failure is logged but does not raise (best-effort)."""
        mock_pool.execute_query.side_effect = RuntimeError("DB connection lost")

        # Should not raise — best-effort per Rule 12 (failure logged, not swallowed silently)
        await clustering_service._update_article_counts()

    @pytest.mark.asyncio
    async def test_no_params_passed(self, clustering_service, mock_pool):
        """Test that no parameters dict is passed (query is parameterless)."""
        await clustering_service._update_article_counts()

        call_args = mock_pool.execute_query.call_args
        # The query takes no parameters — second arg should be empty or absent
        if len(call_args.args) > 1:
            assert call_args.args[1] == {} or call_args.args[1] is None


class TestDetectorRebuildCommunitiesBackfill:
    """Tests that CommunityDetector.rebuild_communities backfills article_count.

    This is the primary user-facing entry point (via
    /api/v1/admin/communities/rebuild). The initial R3 fix only patched
    SubgraphClusteringService.run_full_rebuild, missing this path.
    """

    @pytest.fixture
    def detector(self, mock_pool):
        """Create CommunityDetector with mocked dependencies."""
        from core.db.graph_query_builders import GraphDatabaseType
        from modules.knowledge.graph.community.detector import CommunityDetector

        return CommunityDetector(
            pool=mock_pool,
            max_cluster_size=10,
            default_seed=42,
            database_type=GraphDatabaseType.NEO4J,
            llm_client=None,
        )

    @pytest.mark.asyncio
    async def test_rebuild_communities_calls_backfill(self, detector, mock_pool):
        """rebuild_communities must execute the article_count backfill query."""
        # Mock internal methods to isolate backfill verification
        detector._repo.delete_all_communities = AsyncMock(return_value=0)
        detector.detect_communities = AsyncMock(return_value=MagicMock(communities=[]))
        detector._generate_community_titles = AsyncMock()
        detector._persist_communities = AsyncMock()

        await detector.rebuild_communities()

        # Verify backfill query was among the execute_query calls
        backfill_calls = [
            call
            for call in mock_pool.execute_query.call_args_list
            if call.args and "SET c.article_count = article_count" in call.args[0]
        ]
        assert len(backfill_calls) == 1, (
            f"Expected exactly 1 backfill call, got {len(backfill_calls)}. "
            f"All calls: {mock_pool.execute_query.call_args_list}"
        )

    @pytest.mark.asyncio
    async def test_rebuild_communities_does_not_raise_on_backfill_failure(
        self, detector, mock_pool
    ):
        """Backfill failure must not break rebuild_communities (best-effort)."""
        detector._repo.delete_all_communities = AsyncMock(return_value=0)
        detector.detect_communities = AsyncMock(return_value=MagicMock(communities=[]))
        detector._generate_community_titles = AsyncMock()
        detector._persist_communities = AsyncMock()

        # Make only the backfill query fail (detect_communities also calls
        # execute_query via _build_edge_list, but it's mocked here)
        call_count = [0]

        async def side_effect(query, *args, **kwargs):
            call_count[0] += 1
            if "SET c.article_count = article_count" in str(query):
                raise RuntimeError("Neo4j connection lost")
            return []

        mock_pool.execute_query.side_effect = side_effect

        # Should not raise — best-effort per Rule 12
        await detector.rebuild_communities()
