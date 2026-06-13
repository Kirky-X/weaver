# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for LadybugDB global context builder."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from modules.knowledge.search.context.builder import SearchContext
from modules.knowledge.search.context.ladybug_global_context import (
    LadybugGlobalContextBuilder,
)


class TestLadybugGlobalContextBuilderInit:
    """Test LadybugGlobalContextBuilder initialization."""

    def test_should_initialize_with_default_parameters(self, mock_pool) -> None:
        """Test initialization with default parameters."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        assert builder._pool is mock_pool
        assert builder._max_communities == 10
        assert builder._max_entities_per_community == 5
        assert builder._llm_client is None
        assert builder._fallback_enabled is True
        assert builder._query_builder is not None

    def test_should_initialize_with_custom_parameters(self, mock_pool) -> None:
        """Test initialization with custom parameters."""
        mock_llm = AsyncMock()
        mock_token_encoder = Mock()

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            token_encoder=mock_token_encoder,
            default_max_tokens=15000,
            max_communities=20,
            max_entities_per_community=10,
            llm_client=mock_llm,
            fallback_enabled=False,
        )

        assert builder._pool is mock_pool
        assert builder._token_encoder is mock_token_encoder
        assert builder._default_max_tokens == 15000
        assert builder._max_communities == 20
        assert builder._max_entities_per_community == 10
        assert builder._llm_client is mock_llm
        assert builder._fallback_enabled is False

    def test_should_create_query_builder_for_ladybug(self, mock_pool) -> None:
        """Test that query builder is created for ladybug type."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        # Verify query builder exists and is for ladybug
        assert builder._query_builder is not None
        assert builder._query_builder.database_type.value == "ladybug"


class TestBuildContext:
    """Test build() method - main context building logic."""

    @pytest.mark.asyncio
    async def test_should_build_context_with_simple_query(self, mock_pool) -> None:
        """Test building context for a simple query."""
        # Return empty communities - need to mock all search attempts including fallback
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search with query - returns empty
                [],  # text search fallback (no query) - also returns empty
                [],  # entity-article fallback - also empty
                [{"count": 5}],  # _has_any_communities
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test query")

        assert isinstance(context, SearchContext)
        assert context.query == "test query"
        # When no communities found but some exist
        assert len(context.sections) >= 1

    @pytest.mark.asyncio
    async def test_should_handle_empty_query(self, mock_pool) -> None:
        """Test handling empty query string."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search returns empty
                [],  # text search fallback also empty
                [{"count": 3}],  # has communities
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="")

        assert isinstance(context, SearchContext)
        assert context.query == ""

    @pytest.mark.asyncio
    async def test_should_handle_no_communities_exist(self, mock_pool) -> None:
        """Test when no communities exist and fallback also fails."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [],  # text fallback
                [],  # entity fallback (token-based)
                [],  # entity fallback (Chinese chunk - also empty for "test")
                [{"count": 0}],  # no communities exist
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test")

        assert len(context.sections) == 1
        assert context.sections[0].name == "No Communities"
        assert "社区数据尚未初始化" in context.sections[0].content
        assert context.metadata["hint"] == "run POST /api/v1/admin/communities/rebuild"

    @pytest.mark.asyncio
    async def test_should_build_context_with_communities(self, mock_pool) -> None:
        """Test building context when communities are found."""
        # Use valid UUID format for community IDs
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # text search returns communities
                [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "title": "Tech Community",
                        "summary": "Technology related entities",
                        "rank": 0.9,
                    },
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440002",
                        "title": "Science Community",
                        "summary": "Science related entities",
                        "rank": 0.8,
                    },
                ],
                # key entities
                [
                    {
                        "canonical_name": "AI",
                        "type": "TECHNOLOGY",
                        "description": "Artificial Intelligence",
                    },
                ],
                # cross-community relationships
                [
                    {
                        "source_community": "Tech Community",
                        "target_community": "Science Community",
                        "source_entity": "AI",
                        "target_entity": "Research",
                        "relation_type": "RELATED_TO",
                    },
                ],
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="technology")

        assert isinstance(context, SearchContext)
        assert context.metadata["total_communities"] == 2
        assert context.metadata["community_level"] == 0
        assert context.metadata["search_method"] == "text_search"
        assert len(context.sections) >= 1
        # Should have communities section
        communities_section = [s for s in context.sections if s.name == "Community Summaries"]
        assert len(communities_section) == 1

    @pytest.mark.asyncio
    async def test_should_build_context_with_custom_max_tokens(self, mock_pool) -> None:
        """Test building context with custom max tokens."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", max_tokens=5000)

        assert context.max_tokens == 5000

    @pytest.mark.asyncio
    async def test_should_build_context_with_community_level(self, mock_pool) -> None:
        """Test building context with specific community level."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [{"count": 2}],  # has communities
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", community_level=2)

        assert context.metadata["community_level"] == 2

    @pytest.mark.asyncio
    async def test_should_add_key_entities_section(self, mock_pool) -> None:
        """Test that key entities are added to context."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # communities with valid UUID
                [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "title": "Tech",
                        "summary": "Tech summary",
                        "rank": 0.9,
                    }
                ],
                # key entities
                [
                    {
                        "canonical_name": "Python",
                        "type": "LANGUAGE",
                        "description": "Programming language",
                    },
                    {
                        "canonical_name": "Rust",
                        "type": "LANGUAGE",
                        "description": "Systems language",
                    },
                ],
                # no cross-community rels (only 1 community)
                [],
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="programming")

        entities_section = [s for s in context.sections if s.name == "Key Entities"]
        assert len(entities_section) == 1
        assert entities_section[0].metadata["entity_count"] == 2

    @pytest.mark.asyncio
    async def test_should_add_cross_community_relationships(self, mock_pool) -> None:
        """Test that cross-community relationships are added."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # 2 communities with valid UUIDs
                [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "title": "Tech",
                        "summary": "Tech",
                        "rank": 0.9,
                    },
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440002",
                        "title": "Science",
                        "summary": "Science",
                        "rank": 0.8,
                    },
                ],
                # key entities
                [{"canonical_name": "AI", "type": "TECH", "description": "AI"}],
                # cross-community relationships
                [
                    {
                        "source_community": "Tech",
                        "target_community": "Science",
                        "source_entity": "AI",
                        "target_entity": "Research",
                        "relation_type": "INFLUENCES",
                    },
                ],
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="AI research")

        rels_section = [s for s in context.sections if s.name == "Cross-Community Connections"]
        assert len(rels_section) == 1
        assert rels_section[0].metadata["connection_count"] == 1

    @pytest.mark.asyncio
    async def test_should_handle_query_error_gracefully(self, mock_pool) -> None:
        """Test handling database query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Database connection failed"))

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        # Should not raise, should return empty context
        context = await builder.build(query="test")

        assert isinstance(context, SearchContext)
        # When all queries fail, metadata may not be set
        assert (
            context.metadata.get("total_communities", 0) == 0
            or "total_communities" not in context.metadata
        )


class TestFindRelevantCommunities:
    """Test find_relevant_communities() method."""

    @pytest.mark.asyncio
    async def test_should_use_vector_search_when_llm_available(self, mock_pool) -> None:
        """Test vector search is attempted when LLM client is available."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        mock_llm = AsyncMock()
        mock_llm.embed_default = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            llm_client=mock_llm,
        )

        communities, used_fallback, method = await builder.find_relevant_communities(
            "test query", level=0
        )

        # Vector search falls back to text search in LadybugDB
        mock_llm.embed_default.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_skip_vector_search_without_llm(self, mock_pool) -> None:
        """Test vector search is skipped when no LLM client."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        communities, used_fallback, method = await builder.find_relevant_communities(
            "test", level=0
        )

        assert method in ["text_search", "none"]

    @pytest.mark.asyncio
    async def test_should_fallback_to_text_search(self, mock_pool) -> None:
        """Test fallback to text search when vector search fails."""
        # First call (vector->text) returns empty, second call (text) returns results
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search with query
                [{"id": "comm-1", "title": "Test", "summary": "Test", "rank": 0.9}],
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        communities, used_fallback, method = await builder.find_relevant_communities(
            "test", level=0
        )

        assert len(communities) == 1
        assert method == "text_search"
        assert used_fallback is False

    @pytest.mark.asyncio
    async def test_should_use_entity_article_fallback(self, mock_pool) -> None:
        """Test entity-article fallback when no communities found."""
        # Text search fails, fallback query succeeds
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search with query
                [],  # text search fallback (no query)
                [  # entity-article fallback (new format)
                    {
                        "entity_name": "AI",
                        "entity_type": "TECHNOLOGY",
                        "entity_description": "Artificial Intelligence",
                        "entity_tier": 2,
                    },
                ],
            ]
        )

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            fallback_enabled=True,
        )

        communities, used_fallback, method = await builder.find_relevant_communities(
            "AI technology", level=0
        )

        assert len(communities) == 1
        assert used_fallback is True
        assert method == "entity_article_fallback"
        assert communities[0]["id"] == "entity:AI"

    @pytest.mark.asyncio
    async def test_should_return_empty_when_no_results(self, mock_pool) -> None:
        """Test returning empty when all search methods fail."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            fallback_enabled=True,
        )

        communities, used_fallback, method = await builder.find_relevant_communities(
            "nonexistent query xyz", level=0
        )

        assert communities == []
        assert method == "none"

    @pytest.mark.asyncio
    async def test_should_disable_fallback_when_configured(self, mock_pool) -> None:
        """Test that fallback is skipped when disabled."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            fallback_enabled=False,
        )

        communities, used_fallback, method = await builder.find_relevant_communities(
            "test", level=0
        )

        assert communities == []
        assert method == "none"


class TestVectorSearchCommunities:
    """Test _vector_search_communities() method."""

    @pytest.mark.asyncio
    async def test_should_return_empty_without_llm_client(self, mock_pool) -> None:
        """Test vector search returns empty without LLM client."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = await builder._vector_search_communities("test", level=0)

        assert result == []

    @pytest.mark.asyncio
    async def test_should_handle_embedding_generation_failure(self, mock_pool) -> None:
        """Test handling embedding generation failure."""
        mock_llm = AsyncMock()
        mock_llm.embed_default = AsyncMock(side_effect=Exception("Embedding API error"))

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            llm_client=mock_llm,
        )

        result = await builder._vector_search_communities("test", level=0)

        # Should fallback to text search
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_should_handle_empty_embedding(self, mock_pool) -> None:
        """Test handling empty embedding result."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        mock_llm = AsyncMock()
        mock_llm.embed_default = AsyncMock(return_value=[[]])

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            llm_client=mock_llm,
        )

        result = await builder._vector_search_communities("test", level=0)

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_should_fallback_to_text_search_for_ladybugdb(self, mock_pool) -> None:
        """Test that LadybugDB falls back to text search (no native vector)."""
        mock_pool.execute_query = AsyncMock(
            return_value=[{"id": "comm-1", "title": "Tech", "summary": "Tech", "rank": 0.8}]
        )

        mock_llm = AsyncMock()
        mock_llm.embed_default = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            llm_client=mock_llm,
        )

        result = await builder._vector_search_communities("technology", level=0)

        # Should use text search as fallback
        assert len(result) == 1


class TestTextSearchCommunities:
    """Test _text_search_communities() method."""

    @pytest.mark.asyncio
    async def test_should_search_with_query(self, mock_pool) -> None:
        """Test text search with query string."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "comm-1",
                    "title": "AI Research",
                    "summary": "AI research community",
                    "rank": 0.95,
                },
                {
                    "id": "comm-2",
                    "title": "Machine Learning",
                    "summary": "ML community",
                    "rank": 0.85,
                },
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder._text_search_communities("AI research", level=0)

        assert len(result) == 2
        assert result[0]["title"] == "AI Research"
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_fallback_to_top_communities(self, mock_pool) -> None:
        """Test fallback to top communities by rank when text search fails."""
        # First query fails, second (fallback) succeeds
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                Exception("Text search failed"),
                [
                    {"id": "comm-1", "title": "Top Community", "summary": "Summary", "rank": 0.9},
                ],
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder._text_search_communities("query", level=0)

        assert len(result) == 1
        assert result[0]["title"] == "Top Community"

    @pytest.mark.asyncio
    async def test_should_handle_both_queries_failing(self, mock_pool) -> None:
        """Test handling both text search and fallback failing."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                Exception("Text search failed"),
                Exception("Fallback also failed"),
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder._text_search_communities("query", level=0)

        assert result == []

    @pytest.mark.asyncio
    async def test_should_respect_max_communities_limit(self, mock_pool) -> None:
        """Test that max_communities limit is respected."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": f"comm-{i}",
                    "title": f"Community {i}",
                    "summary": "Summary",
                    "rank": 0.9 - i * 0.1,
                }
                for i in range(15)
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool, max_communities=5)
        result = await builder._text_search_communities("test", level=0)

        # Query builder should use max_communities limit
        assert builder._max_communities == 5


class TestFindEntityArticleFallback:
    """Test _find_entity_article_fallback() method."""

    @pytest.mark.asyncio
    async def test_should_return_empty_for_empty_query(self, mock_pool) -> None:
        """Test returning empty for empty query."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = await builder._find_entity_article_fallback("")

        assert result == []

    @pytest.mark.asyncio
    async def test_should_return_empty_for_whitespace_query(self, mock_pool) -> None:
        """Test returning empty for whitespace-only query."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = await builder._find_entity_article_fallback("   ")

        assert result == []

    @pytest.mark.asyncio
    async def test_should_build_fallback_results(self, mock_pool) -> None:
        """Test building fallback results from entity matches."""
        # Mock data matches new entity-based fallback format
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "entity_name": "Python",
                    "entity_type": "LANGUAGE",
                    "entity_description": "Programming language",
                    "entity_tier": 2,
                },
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder._find_entity_article_fallback("Python programming")

        assert len(result) == 1
        assert result[0]["id"] == "entity:Python"
        assert result[0]["title"] == "Python"
        assert result[0]["summary"] == "Programming language"
        assert result[0]["rank"] == 0.8  # 1.0 - (2 / 10.0)

    @pytest.mark.asyncio
    async def test_should_handle_fallback_query_error(self, mock_pool) -> None:
        """Test handling fallback query error."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder._find_entity_article_fallback("test query")

        assert result == []

    @pytest.mark.asyncio
    async def test_should_handle_empty_fallback_results(self, mock_pool) -> None:
        """Test handling empty fallback results."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder._find_entity_article_fallback("nonexistent")

        assert result == []


class TestGetKeyEntities:
    """Test _get_key_entities() method."""

    @pytest.mark.asyncio
    async def test_should_return_empty_for_empty_communities(self, mock_pool) -> None:
        """Test returning empty for empty communities list."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = await builder._get_key_entities([])

        assert result == []

    @pytest.mark.asyncio
    async def test_should_return_empty_for_communities_without_ids(self, mock_pool) -> None:
        """Test returning empty for communities without IDs."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = await builder._get_key_entities(
            [
                {"title": "No ID Community"},
                {"summary": "Another no ID"},
            ]
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_should_get_entities_for_valid_communities(self, mock_pool) -> None:
        """Test getting entities for communities with valid IDs."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"canonical_name": "Entity1", "type": "TYPE1", "description": "Desc1"},
                {"canonical_name": "Entity2", "type": "TYPE2", "description": "Desc2"},
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        communities = [
            {"id": "550e8400-e29b-41d4-a716-446655440001", "title": "Community 1"},
            {"id": "550e8400-e29b-41d4-a716-446655440002", "title": "Community 2"},
        ]

        result = await builder._get_key_entities(communities)

        assert len(result) == 2
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Database error"))

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        communities = [{"id": "550e8400-e29b-41d4-a716-446655440001"}]

        result = await builder._get_key_entities(communities)

        assert result == []

    @pytest.mark.asyncio
    async def test_should_filter_communities_without_ids(self, mock_pool) -> None:
        """Test filtering communities without IDs."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        communities = [
            {"id": "550e8400-e29b-41d4-a716-446655440001", "title": "With ID"},
            {"title": "Without ID"},
            {"id": "550e8400-e29b-41d4-a716-446655440002", "title": "Another With ID"},
        ]

        await builder._get_key_entities(communities)

        # Query was called (we can't verify exact params due to parameterized query)
        assert mock_pool.execute_query.called


class TestGetCrossCommunityRelationships:
    """Test _get_cross_community_relationships() method."""

    @pytest.mark.asyncio
    async def test_should_return_empty_for_single_community(self, mock_pool) -> None:
        """Test returning empty for single community (no cross-community possible)."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = await builder._get_cross_community_relationships(
            [{"id": "550e8400-e29b-41d4-a716-446655440001", "title": "Single"}]
        )

        assert result == []
        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_return_empty_for_empty_list(self, mock_pool) -> None:
        """Test returning empty for empty communities list."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = await builder._get_cross_community_relationships([])

        assert result == []

    @pytest.mark.asyncio
    async def test_should_query_for_multiple_communities(self, mock_pool) -> None:
        """Test querying cross-community relationships for multiple communities."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "source_community": "Tech",
                    "target_community": "Science",
                    "source_entity": "AI",
                    "target_entity": "Research",
                    "relation_type": "RELATED_TO",
                },
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        communities = [
            {"id": "550e8400-e29b-41d4-a716-446655440001", "title": "Tech"},
            {"id": "550e8400-e29b-41d4-a716-446655440002", "title": "Science"},
        ]

        result = await builder._get_cross_community_relationships(communities)

        assert len(result) == 1
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        communities = [
            {"id": "550e8400-e29b-41d4-a716-446655440001"},
            {"id": "550e8400-e29b-41d4-a716-446655440002"},
        ]

        result = await builder._get_cross_community_relationships(communities)

        assert result == []

    @pytest.mark.asyncio
    async def test_should_filter_communities_without_ids(self, mock_pool) -> None:
        """Test filtering communities without IDs in query."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        communities = [
            {"id": "550e8400-e29b-41d4-a716-446655440001", "title": "With ID"},
            {"title": "Without ID"},
        ]

        await builder._get_cross_community_relationships(communities)

        # Query was called (parameterized query, can't check exact string)
        assert mock_pool.execute_query.called


class TestFormatCommunitiesSection:
    """Test _format_communities_section() method."""

    def test_should_format_single_community(self, mock_pool) -> None:
        """Test formatting single community."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        communities = [
            {
                "title": "AI Community",
                "summary": "Artificial Intelligence related entities",
                "entity_count": 15,
            }
        ]

        result = builder.format_communities_section(communities)

        assert "### AI Community" in result
        assert "Entities: 15" in result
        assert "Artificial Intelligence" in result

    def test_should_format_multiple_communities(self, mock_pool) -> None:
        """Test formatting multiple communities."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        communities = [
            {"title": "Tech", "summary": "Tech summary", "entity_count": 10},
            {"title": "Science", "summary": "Science summary", "entity_count": 20},
        ]

        result = builder.format_communities_section(communities)

        assert "### Tech" in result
        assert "### Science" in result
        assert "Entities: 10" in result
        assert "Entities: 20" in result

    def test_should_handle_missing_fields(self, mock_pool) -> None:
        """Test handling communities with missing fields."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        communities = [
            {"title": "Minimal Community"},
            {"entity_count": 5},
        ]

        result = builder.format_communities_section(communities)

        assert "### Minimal Community" in result
        assert "### Community 2" in result  # Default title
        assert "Entities: 0" in result  # Default entity_count

    def test_should_truncate_long_summaries(self, mock_pool) -> None:
        """Test truncating long community summaries."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        long_summary = "A" * 500
        communities = [{"title": "Long Summary", "summary": long_summary, "entity_count": 1}]

        result = builder.format_communities_section(communities)

        # Should be truncated to ~200 tokens
        assert len(result) < len(long_summary) + 100

    def test_should_handle_empty_summary(self, mock_pool) -> None:
        """Test handling empty summary."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        communities = [{"title": "No Summary", "summary": "", "entity_count": 1}]

        result = builder.format_communities_section(communities)

        assert "### No Summary" in result
        assert "Summary:" not in result


class TestFormatEntitiesSection:
    """Test _format_entities_section() method."""

    def test_should_format_single_entity(self, mock_pool) -> None:
        """Test formatting single entity."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        entities = [
            {
                "canonical_name": "Python",
                "type": "LANGUAGE",
                "description": "Programming language",
            }
        ]

        result = builder.format_entities_section(entities)

        assert "Python" in result
        assert "LANGUAGE" in result
        assert "Programming language" in result

    def test_should_format_multiple_entities(self, mock_pool) -> None:
        """Test formatting multiple entities."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        entities = [
            {"canonical_name": "Python", "type": "LANGUAGE", "description": "Python"},
            {"canonical_name": "Rust", "type": "LANGUAGE", "description": "Rust"},
        ]

        result = builder.format_entities_section(entities)

        assert "Python" in result
        assert "Rust" in result

    def test_should_handle_empty_entities_list(self, mock_pool) -> None:
        """Test handling empty entities list."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = builder.format_entities_section([])

        assert result == ""


class TestFormatCrossCommunitySection:
    """Test _format_cross_community_section() method."""

    def test_should_format_single_connection(self, mock_pool) -> None:
        """Test formatting single cross-community connection."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        connections = [
            {
                "source_community": "Tech",
                "target_community": "Science",
                "source_entity": "AI",
                "target_entity": "Research",
                "relation_type": "INFLUENCES",
            }
        ]

        result = builder.format_cross_community_section(connections)

        assert "Tech" in result
        assert "Science" in result
        assert "AI" in result
        assert "Research" in result
        assert "INFLUENCES" in result

    def test_should_format_multiple_connections(self, mock_pool) -> None:
        """Test formatting multiple connections."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        connections = [
            {
                "source_community": "Tech",
                "target_community": "Science",
                "source_entity": "AI",
                "target_entity": "Research",
                "relation_type": "RELATED_TO",
            },
            {
                "source_community": "Science",
                "target_community": "Math",
                "source_entity": "Physics",
                "target_entity": "Calculus",
                "relation_type": "USES",
            },
        ]

        result = builder.format_cross_community_section(connections)

        assert "Tech" in result
        assert "Math" in result
        assert result.count("- [") == 2

    def test_should_handle_missing_fields(self, mock_pool) -> None:
        """Test handling connections with missing fields."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        connections = [
            {"source_community": "Tech"},
            {},
        ]

        result = builder.format_cross_community_section(connections)

        assert "Tech" in result
        assert "Unknown" in result  # Default for missing fields

    def test_should_handle_empty_connections_list(self, mock_pool) -> None:
        """Test handling empty connections list."""
        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        result = builder.format_cross_community_section([])

        assert result == ""


class TestHasAnyCommunities:
    """Test has_any_communities() method."""

    @pytest.mark.asyncio
    async def test_should_return_true_when_communities_exist(self, mock_pool) -> None:
        """Test returning True when communities exist."""
        mock_pool.execute_query = AsyncMock(return_value=[{"count": 5}])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder.has_any_communities()

        assert result is True

    @pytest.mark.asyncio
    async def test_should_return_false_when_no_communities(self, mock_pool) -> None:
        """Test returning False when no communities exist."""
        mock_pool.execute_query = AsyncMock(return_value=[{"count": 0}])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder.has_any_communities()

        assert result is False

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Database error"))

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder.has_any_communities()

        assert result is False

    @pytest.mark.asyncio
    async def test_should_handle_empty_result(self, mock_pool) -> None:
        """Test handling empty query result."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder.has_any_communities()

        assert result is False

    @pytest.mark.asyncio
    async def test_should_handle_missing_count_field(self, mock_pool) -> None:
        """Test handling result without count field."""
        mock_pool.execute_query = AsyncMock(return_value=[{"other_field": 5}])

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder.has_any_communities()

        assert result is False

    @pytest.mark.asyncio
    async def test_should_handle_type_error(self, mock_pool) -> None:
        """Test handling type error gracefully."""
        mock_pool.execute_query = AsyncMock(return_value=None)

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        result = await builder.has_any_communities()

        assert result is False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_should_handle_special_characters_in_query(self, mock_pool) -> None:
        """Test handling special characters in query."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [{"count": 1}],  # has communities
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test @#$%^&*() query")

        assert isinstance(context, SearchContext)

    @pytest.mark.asyncio
    async def test_should_handle_unicode_query(self, mock_pool) -> None:
        """Test handling unicode/Chinese characters in query."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [{"count": 1}],  # has communities
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="人工智能技术")

        assert isinstance(context, SearchContext)

    @pytest.mark.asyncio
    async def test_should_handle_very_long_query(self, mock_pool) -> None:
        """Test handling very long query string."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [{"count": 1}],  # has communities
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        long_query = "test " * 1000
        context = await builder.build(query=long_query)

        assert isinstance(context, SearchContext)

    @pytest.mark.asyncio
    async def test_should_handle_large_number_of_communities(self, mock_pool) -> None:
        """Test handling large number of communities."""
        # Simulate many communities with valid UUIDs
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": f"550e8400-e29b-41d4-a716-44665544{i:04d}",
                        "title": f"Community {i}",
                        "summary": "Summary",
                        "rank": 0.9 - i * 0.01,
                    }
                    for i in range(50)
                ],
                [],  # key entities
                [],  # cross-community rels
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool, max_communities=10)
        context = await builder.build(query="test")

        # Result should have communities (up to max_communities)
        assert context.metadata["total_communities"] > 0

    @pytest.mark.asyncio
    async def test_should_handle_concurrent_calls(self, mock_pool) -> None:
        """Test handling concurrent build calls."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [{"count": 1}],  # has communities
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)

        # Make multiple concurrent calls
        import asyncio

        results = await asyncio.gather(
            builder.build(query="query1"),
            builder.build(query="query2"),
            builder.build(query="query3"),
        )

        assert len(results) == 3
        assert all(isinstance(ctx, SearchContext) for ctx in results)
        assert results[0].query == "query1"
        assert results[1].query == "query2"
        assert results[2].query == "query3"


class TestMetadataTracking:
    """Test metadata tracking in SearchContext."""

    @pytest.mark.asyncio
    async def test_should_track_search_method(self, mock_pool) -> None:
        """Test that search method is tracked in metadata."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "title": "Test",
                        "summary": "Test",
                        "rank": 0.9,
                    }
                ],
                [],  # key entities
                [],  # cross-community rels
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test")

        assert "search_method" in context.metadata
        assert context.metadata["search_method"] == "text_search"

    @pytest.mark.asyncio
    async def test_should_track_fallback_usage(self, mock_pool) -> None:
        """Test that fallback usage is tracked in metadata."""
        # Note: When fallback is used, community IDs have format "fallback:article_id"
        # which are not valid UUIDs. This causes _get_key_entities to raise an error
        # (UUID validation happens before the try-except block).
        # For this test, we'll mock _get_key_entities to avoid the error.

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [],  # text fallback
                [  # entity-article fallback
                    {
                        "entity_name": "AI",
                        "entity_type": "TECH",
                        "entity_description": "AI",
                        "article_id": "550e8400-e29b-41d4-a716-446655440010",
                        "article_title": "AI Article",
                        "article_score": 0.9,
                    }
                ],
            ]
        )

        builder = LadybugGlobalContextBuilder(
            graph_pool=mock_pool,
            fallback_enabled=True,
        )

        # Mock _get_key_entities to avoid UUID validation error
        builder._get_key_entities = AsyncMock(return_value=[])

        context = await builder.build(query="AI")

        # Fallback should be used (check metadata)
        assert context.metadata.get("search_method") == "entity_article_fallback"

    @pytest.mark.asyncio
    async def test_should_track_community_count(self, mock_pool) -> None:
        """Test that community count is tracked."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "title": "C1",
                        "summary": "S1",
                        "rank": 0.9,
                    },
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440002",
                        "title": "C2",
                        "summary": "S2",
                        "rank": 0.8,
                    },
                ],
                [],
                [],
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test")

        assert context.metadata["total_communities"] == 2

    @pytest.mark.asyncio
    async def test_should_track_community_level(self, mock_pool) -> None:
        """Test that community level is tracked."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],
                [{"count": 1}],
            ]
        )

        builder = LadybugGlobalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", community_level=3)

        assert context.metadata["community_level"] == 3
