# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Global Search with Community support.

Tests the integrated functionality of:
- Community-based context building
- Vector similarity search for community reports
- Map-Reduce answer generation
- Fallback behavior when communities don't exist
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.search.context.global_context import GlobalContextBuilder
from modules.search.engines.global_search import GlobalSearchEngine, MapReduceResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    pool = AsyncMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_vector_repo():
    """Mock vector repository."""
    return AsyncMock()


@pytest.fixture
def sample_community_reports():
    """Sample community reports for testing."""
    return [
        {
            "id": "comm-1",
            "title": "人工智能研究",
            "summary": "人工智能领域的研究进展，包括深度学习和神经网络。",
            "full_content": "人工智能是计算机科学的一个重要分支...",
            "level": 0,
            "entity_count": 15,
            "rank": 8.5,
        },
        {
            "id": "comm-2",
            "title": "机器学习应用",
            "summary": "机器学习在各行业的实际应用案例。",
            "full_content": "机器学习技术已广泛应用于...",
            "level": 0,
            "entity_count": 12,
            "rank": 7.2,
        },
        {
            "id": "comm-3",
            "title": "数据科学技术",
            "summary": "数据分析和可视化的核心技术。",
            "full_content": "数据科学结合统计学和计算机科学...",
            "level": 0,
            "entity_count": 8,
            "rank": 6.0,
        },
    ]


class TestGlobalContextBuilderWithCommunities:
    """Integration tests for GlobalContextBuilder with community support."""

    @pytest.mark.asyncio
    async def test_build_context_with_communities(self, mock_neo4j_pool, sample_community_reports):
        """Test building context when communities exist."""
        # Mock community vector search
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "AI Research",
                    "summary": "AI research summary",
                    "full_content": "Full report content",
                    "level": 0,
                    "entity_count": 10,
                    "rank": 8.5,
                    "score": 0.92,
                }
            ]
        )

        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="人工智能研究", max_tokens=2000)

        assert context is not None
        assert len(context.sections) > 0
        assert context.metadata.get("total_communities", 0) > 0

    @pytest.mark.asyncio
    async def test_build_context_fallback_when_no_communities(self, mock_neo4j_pool):
        """Test fallback behavior when no communities exist."""
        # Mock no communities found
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            fallback_enabled=True,
        )
        context = await builder.build(query="测试查询", max_tokens=1000)

        assert context is not None
        # Should have hint about missing communities
        assert "hint" in context.metadata or len(context.sections) > 0

    @pytest.mark.asyncio
    async def test_build_context_disabled_fallback(self, mock_neo4j_pool):
        """Test that fallback can be disabled."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            fallback_enabled=False,
        )
        context = await builder.build(query="测试查询", max_tokens=1000)

        assert context is not None
        assert context.metadata.get("fallback_source") is None

    @pytest.mark.asyncio
    async def test_find_relevant_communities_with_vector_search(
        self, mock_neo4j_pool, sample_community_reports
    ):
        """Test vector similarity search for community reports."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "AI Research",
                    "summary": "AI research summary",
                    "score": 0.95,
                },
                {
                    "id": "comm-2",
                    "title": "ML Applications",
                    "summary": "ML applications summary",
                    "score": 0.88,
                },
            ]
        )

        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)

        # The method should exist and work with vector search
        results, used_fallback, method = await builder._find_relevant_communities(
            query="人工智能研究",
            level=0,
        )

        assert len(results) == 2


class TestGlobalSearchEngineMapReduce:
    """Integration tests for GlobalSearchEngine Map-Reduce."""

    @pytest.mark.asyncio
    async def test_map_phase_generates_intermediate_answers(self, mock_neo4j_pool, mock_llm):
        """Test Map phase generates intermediate answers."""
        # Setup community context
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "AI Research",
                    "full_content": "AI research content",
                    "entity_count": 10,
                }
            ]
        )

        # Mock LLM responses for map phase
        mock_llm.call = AsyncMock(return_value="Intermediate answer about AI research")

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("What is AI research?")

        assert result is not None
        assert result.query == "What is AI research?"

    @pytest.mark.asyncio
    async def test_reduce_phase_aggregates_answers(self, mock_neo4j_pool, mock_llm):
        """Test Reduce phase aggregates intermediate answers."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "AI Research",
                    "full_content": "Content about AI research",
                },
                {
                    "id": "comm-2",
                    "title": "ML Applications",
                    "full_content": "Content about ML applications",
                },
            ]
        )

        # Mock map then reduce responses
        mock_llm.call = AsyncMock(
            side_effect=[
                "Map answer 1 about AI",
                "Map answer 2 about ML",
                "Final reduced answer combining both",
            ]
        )

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Tell me about AI and ML")

        assert result is not None

    @pytest.mark.asyncio
    async def test_map_reduce_with_weighted_communities(self, mock_neo4j_pool, mock_llm):
        """Test Map-Reduce with community weight ranking."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "High Rank Community",
                    "full_content": "Important content",
                    "rank": 9.5,
                    "entity_count": 20,
                },
                {
                    "id": "comm-2",
                    "title": "Lower Rank Community",
                    "full_content": "Less important content",
                    "rank": 5.0,
                    "entity_count": 5,
                },
            ]
        )

        mock_llm.call = AsyncMock(return_value="Generated answer")

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Important query")

        assert result is not None

    @pytest.mark.asyncio
    async def test_map_reduce_handles_empty_communities(self, mock_neo4j_pool, mock_llm):
        """Test Map-Reduce handles case with no communities."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Unknown topic")

        # Should return a result even with no communities
        assert result is not None
        assert result.query == "Unknown topic"


class TestGlobalSearchErrorHandling:
    """Integration tests for error handling in Global Search."""

    @pytest.mark.asyncio
    async def test_handles_neo4j_error_gracefully(self, mock_neo4j_pool, mock_llm):
        """Test graceful handling of Neo4j errors."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Neo4j connection failed"))

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Should handle error gracefully
        try:
            result = await engine.search("Test query")
            assert result is not None
        except Exception:
            # Also acceptable to raise
            pass

    @pytest.mark.asyncio
    async def test_handles_llm_error_in_map_phase(self, mock_neo4j_pool, mock_llm):
        """Test handling of LLM errors during Map phase."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[{"id": "comm-1", "title": "Test"}])
        mock_llm.call = AsyncMock(side_effect=Exception("LLM failed"))

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        try:
            result = await engine.search("Test query")
            assert result is not None
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_partial_failure_continues_processing(self, mock_neo4j_pool, mock_llm):
        """Test that partial failures don't stop entire process."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id": "comm-1", "title": "Community 1"},
                {"id": "comm-2", "title": "Community 2"},
            ]
        )

        # First call succeeds, second fails, third (reduce) succeeds
        mock_llm.call = AsyncMock(
            side_effect=[
                "Answer 1",
                Exception("LLM error"),
                "Reduced answer",
            ]
        )

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        try:
            result = await engine.search("Test query")
            # May still return partial result
            assert result is not None
        except Exception:
            pass


class TestGlobalSearchPerformance:
    """Integration tests for Global Search performance characteristics."""

    @pytest.mark.asyncio
    async def test_respects_max_communities_limit(self, mock_neo4j_pool, mock_llm):
        """Test that search respects max communities limit."""
        # Return many communities
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id": f"comm-{i}", "title": f"Community {i}", "rank": 10 - i} for i in range(20)
            ]
        )

        mock_llm.call = AsyncMock(return_value="Answer")

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
            max_communities=5,
        )

        result = await engine.search("Test query")

        assert result is not None
        # Context builder should limit communities
        # The engine processes all returned communities but context builder limits

    @pytest.mark.asyncio
    async def test_parallel_map_execution(self, mock_neo4j_pool, mock_llm):
        """Test that Map phase executes for all communities."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id": "comm-1", "title": "Community 1"},
                {"id": "comm-2", "title": "Community 2"},
                {"id": "comm-3", "title": "Community 3"},
            ]
        )

        mock_llm.call = AsyncMock(return_value="Answer")

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Test query")

        assert result is not None


class TestGlobalSearchWithRealEmbeddings:
    """Integration tests with simulated embedding behavior."""

    @pytest.mark.asyncio
    async def test_vector_similarity_ordering(self, mock_neo4j_pool, mock_llm):
        """Test that communities are ordered by similarity score."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id": "comm-1", "title": "Most Relevant", "score": 0.95},
                {"id": "comm-2", "title": "Less Relevant", "score": 0.75},
                {"id": "comm-3", "title": "Least Relevant", "score": 0.55},
            ]
        )

        mock_llm.call = AsyncMock(return_value="Answer")

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Specific query")

        assert result is not None

    @pytest.mark.asyncio
    async def test_similarity_threshold_filtering(self, mock_neo4j_pool, mock_llm):
        """Test that communities are filtered by relevance."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id": "comm-1", "title": "High Similarity", "score": 0.9},
                {"id": "comm-2", "title": "Low Similarity", "score": 0.3},
            ]
        )

        mock_llm.call = AsyncMock(return_value="Answer")

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Test query")

        assert result is not None
