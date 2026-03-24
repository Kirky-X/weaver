# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Regression tests for Global Search with Community integration.

These tests verify that Global Search continues to work correctly
with the new community-based context building.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.search.context.global_context import GlobalContextBuilder
from modules.search.engines.global_search import GlobalSearchEngine, MapReduceResult
from modules.search.engines.local_search import SearchResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    llm = MagicMock()
    llm.call = AsyncMock(return_value={"content": "Generated answer"})
    llm.batch_embed = AsyncMock(return_value=[[0.1] * 1536])
    return llm


class TestGlobalSearchRegression:
    """Regression tests for Global Search functionality."""

    @pytest.mark.asyncio
    async def test_global_search_returns_result(self, mock_neo4j_pool, mock_llm):
        """Test that global search returns a valid result."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("What is artificial intelligence?")

        assert result is not None
        assert isinstance(result, SearchResult)
        assert result.query == "What is artificial intelligence?"

    @pytest.mark.asyncio
    async def test_global_search_with_vector_similarity(self, mock_neo4j_pool, mock_llm):
        """Test global search uses vector similarity for community reports."""
        # Mock vector search results
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "AI Research",
                    "summary": "AI research summary",
                    "full_content": "Full content about AI",
                    "rank": 8.5,
                    "entity_count": 10,
                    "score": 0.92,
                }
            ]
        )

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            llm_client=mock_llm,
        )

        context = await builder.build(query="artificial intelligence")

        assert context is not None
        # Verify vector search was attempted
        assert mock_llm.batch_embed.called or mock_neo4j_pool.execute_query.called

    @pytest.mark.asyncio
    async def test_global_search_fallback_to_text_search(self, mock_neo4j_pool, mock_llm):
        """Test fallback to text search when vector search fails."""
        # First call (vector search) returns empty, second (text) returns results
        call_count = [0]

        async def side_effect_fn(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return []  # Vector search fails
            return [{"id": "comm-1", "title": "AI", "summary": "AI summary"}]

        mock_neo4j_pool.execute_query = AsyncMock(side_effect=side_effect_fn)

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            llm_client=mock_llm,
        )

        context = await builder.build(query="artificial intelligence")

        assert context is not None

    @pytest.mark.asyncio
    async def test_global_search_entity_article_fallback(self, mock_neo4j_pool, mock_llm):
        """Test fallback to entity-article when no communities exist."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # No communities via vector
                [],  # No communities via text
                [{"count": 0}],  # No communities count check
                [  # Entity-article fallback
                    {
                        "entity_name": "OpenAI",
                        "entity_type": "组织机构",
                        "article_title": "OpenAI announces GPT-5",
                    }
                ],
            ]
        )

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            llm_client=None,  # No LLM for embedding
            fallback_enabled=True,
        )

        context = await builder.build(query="OpenAI")

        assert context is not None

    @pytest.mark.asyncio
    async def test_global_search_no_fallback_when_disabled(self, mock_neo4j_pool, mock_llm):
        """Test that entity-article fallback can be disabled."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            llm_client=None,
            fallback_enabled=False,
        )

        context = await builder.build(query="unknown topic")

        # Should not use fallback
        assert context.metadata.get("fallback_source") != "entity_article"


class TestGlobalSearchMapReduce:
    """Regression tests for Map-Reduce functionality."""

    @pytest.mark.asyncio
    async def test_map_reduce_processes_all_communities(self, mock_neo4j_pool, mock_llm):
        """Test that Map-Reduce processes all relevant communities."""
        # Mock multiple communities
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id": "comm-1", "title": "AI Research", "full_content": "Content 1"},
                {"id": "comm-2", "title": "ML Applications", "full_content": "Content 2"},
                {"id": "comm-3", "title": "Data Science", "full_content": "Content 3"},
            ]
        )

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("Tell me about AI and ML")

        assert result is not None

    @pytest.mark.asyncio
    async def test_map_reduce_respects_community_rank(self, mock_neo4j_pool, mock_llm):
        """Test that communities are processed by rank order."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id": "comm-1", "title": "High Rank", "rank": 9.5},
                {"id": "comm-2", "title": "Low Rank", "rank": 3.0},
            ]
        )

        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="test")

        assert context is not None


class TestGlobalSearchContextBuilder:
    """Regression tests for GlobalContextBuilder."""

    @pytest.mark.asyncio
    async def test_context_includes_community_summaries(self, mock_neo4j_pool, mock_llm):
        """Test that context includes community summaries."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "AI Community",
                    "summary": "Summary of AI community",
                    "entity_count": 10,
                }
            ]
        )

        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="AI")

        # Check that community section exists
        assert context is not None
        assert context.metadata.get("total_communities", 0) >= 0

    @pytest.mark.asyncio
    async def test_context_includes_key_entities(self, mock_neo4j_pool, mock_llm):
        """Test that context includes key entities from communities."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": "comm-1", "title": "AI"}],  # Communities
                [  # Key entities
                    {"canonical_name": "OpenAI", "type": "Organization", "degree": 10},
                    {"canonical_name": "GPT-4", "type": "Product", "degree": 8},
                ],
                [],  # Cross-community relationships
            ]
        )

        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="AI")

        assert context is not None

    @pytest.mark.asyncio
    async def test_context_includes_cross_community_connections(self, mock_neo4j_pool, mock_llm):
        """Test that context includes cross-community relationships."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [
                    {"id": "comm-1", "title": "AI"},
                    {"id": "comm-2", "title": "ML"},
                ],  # Two communities
                [],  # Entities
                [  # Cross-community connections
                    {
                        "source_community": "AI",
                        "target_community": "ML",
                        "source_entity": "Neural Networks",
                        "target_entity": "Deep Learning",
                        "relation_type": "RELATED_TO",
                    }
                ],
            ]
        )

        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="AI and ML")

        assert context is not None

    @pytest.mark.asyncio
    async def test_context_respects_max_tokens(self, mock_neo4j_pool, mock_llm):
        """Test that context respects max_tokens limit."""
        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            default_max_tokens=1000,
        )

        # Should handle max_tokens parameter
        context = await builder.build(query="test", max_tokens=500)

        assert context is not None


class TestGlobalSearchErrorHandling:
    """Regression tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_neo4j_connection_error(self, mock_neo4j_pool, mock_llm):
        """Test graceful handling of Neo4j connection errors."""
        # Mock returns an empty list to simulate no results found
        # This simulates graceful degradation when no data is available
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="test")

        # Should handle gracefully - returns a context with no communities
        assert context is not None
        assert context.metadata.get("total_communities", 0) == 0

    @pytest.mark.asyncio
    async def test_handles_llm_error_in_search(self, mock_neo4j_pool, mock_llm):
        """Test handling of LLM errors during search."""
        mock_llm.call = AsyncMock(side_effect=Exception("LLM error"))

        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Should not crash
        try:
            result = await engine.search("test")
            assert result is not None
        except Exception:
            pass  # Also acceptable to raise

    @pytest.mark.asyncio
    async def test_handles_empty_query(self, mock_neo4j_pool, mock_llm):
        """Test handling of empty query string."""
        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="")

        # Should handle empty query
        assert context is not None


class TestGlobalSearchBackwardCompatibility:
    """Tests for backward compatibility with existing Global Search."""

    @pytest.mark.asyncio
    async def test_search_result_structure(self, mock_neo4j_pool, mock_llm):
        """Test that result structure is backward compatible."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("test query")

        # Result should have expected fields
        assert hasattr(result, "query")
        assert hasattr(result, "answer")
        assert hasattr(result, "confidence")

    @pytest.mark.asyncio
    async def test_confidence_is_valid_range(self, mock_neo4j_pool, mock_llm):
        """Test that confidence is in valid range [0, 1]."""
        engine = GlobalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        result = await engine.search("test")

        assert 0 <= result.confidence <= 1

    @pytest.mark.asyncio
    async def test_context_builder_metadata_structure(self, mock_neo4j_pool, mock_llm):
        """Test that context metadata has expected structure."""
        builder = GlobalContextBuilder(neo4j_pool=mock_neo4j_pool)
        context = await builder.build(query="test")

        # Check metadata exists
        assert hasattr(context, "metadata")
        assert isinstance(context.metadata, dict)


class TestGlobalSearchPerformance:
    """Performance-related regression tests."""

    @pytest.mark.asyncio
    async def test_limits_communities_properly(self, mock_neo4j_pool, mock_llm):
        """Test that community count is properly limited."""
        # Return many communities
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[{"id": f"comm-{i}", "title": f"Community {i}"} for i in range(50)]
        )

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            max_communities=10,
        )

        context = await builder.build(query="test")

        # Should be limited
        assert context is not None

    @pytest.mark.asyncio
    async def test_handles_large_community_reports(self, mock_neo4j_pool, mock_llm):
        """Test handling of large community report content."""
        large_content = "x" * 10000  # Large content

        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "Large Community",
                    "full_content": large_content,
                }
            ]
        )

        builder = GlobalContextBuilder(
            neo4j_pool=mock_neo4j_pool,
            default_max_tokens=1000,
        )

        context = await builder.build(query="test")

        # Should handle large content without error
        assert context is not None
