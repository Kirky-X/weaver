# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GlobalContextBuilder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.context.global_context import GlobalContextBuilder


def _make_pool() -> AsyncMock:
    """Create a mock Neo4jPool."""
    pool = AsyncMock()
    return pool


class TestGlobalContextBuilderInit:
    """Tests for initialization."""

    def test_default_params(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        assert builder._max_communities == 10
        assert builder._max_entities_per_community == 5
        assert builder._fallback_enabled is True

    def test_custom_params(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(
            graph_pool=pool,
            max_communities=20,
            max_entities_per_community=10,
            fallback_enabled=False,
        )
        assert builder._max_communities == 20
        assert builder._fallback_enabled is False


class TestGlobalContextBuilderBuild:
    """Tests for build method."""

    @pytest.mark.asyncio
    async def test_build_no_communities_at_all(self) -> None:
        """Returns hint when no communities exist."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [],  # _find_relevant_communities -> _vector_search_communities
                [],  # _text_search_communities
                [],  # _find_entity_article_fallback (disabled)
                [{"count": 0}],  # _has_any_communities
            ]
        )
        builder = GlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("test query")
        assert ctx.metadata.get("hint") is not None
        assert "rebuild" in ctx.metadata["hint"]

    @pytest.mark.asyncio
    async def test_build_no_relevant_communities(self) -> None:
        """Returns no communities found message."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [],  # _vector_search (no llm_client)
                [],  # _text_search returns empty
                [{"count": 5}],  # _has_any_communities returns True
            ]
        )
        builder = GlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("test query")
        assert ctx.metadata.get("total_communities") == 0

    @pytest.mark.asyncio
    async def test_build_with_communities(self) -> None:
        """Builds context with community data."""
        pool = _make_pool()
        communities = [
            {
                "id": "c1",
                "title": "Tech",
                "summary": "Technology community",
                "rank": 5.0,
                "entity_count": 10,
            }
        ]

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []  # vector search (no llm)
            if call_count == 2:
                return communities  # text search
            if call_count == 3:
                return [
                    {"canonical_name": "Entity1", "type": "ORG", "degree": 5, "community_count": 1}
                ]  # key entities
            if call_count == 4:
                return []  # cross-community (only 1 comm)
            return []

        pool.execute_query = mock_execute
        builder = GlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("tech query")

        assert len(ctx.sections) >= 1
        assert ctx.metadata["total_communities"] == 1
        assert ctx.metadata["search_method"] == "text_search"


class TestFormatCommunities:
    """Tests for formatting methods."""

    def test_format_communities_section(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        communities = [
            {"title": "Tech", "summary": "Summary", "entity_count": 5},
        ]
        result = builder._format_communities_section(communities)
        assert "Tech" in result
        assert "5" in result

    def test_format_entities_section(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        entities = [
            {"canonical_name": "华为", "type": "组织", "description": "Tech"},
        ]
        result = builder._format_entities_section(entities)
        assert "华为" in result

    def test_format_cross_community_section(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        connections = [
            {
                "source_community": "Tech",
                "target_community": "Finance",
                "source_entity": "A",
                "target_entity": "B",
                "relation_type": "PARTNERS_WITH",
            },
        ]
        result = builder._format_cross_community_section(connections)
        assert "Tech" in result
        assert "Finance" in result
        assert "双向" in result  # PARTNERS_WITH is symmetric

    def test_format_cross_community_asymmetric(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        connections = [
            {
                "source_community": "Gov",
                "target_community": "Tech",
                "source_entity": "A",
                "target_entity": "B",
                "relation_type": "REGULATES",
            },
        ]
        result = builder._format_cross_community_section(connections)
        assert "单向" in result


class TestHasAnyCommunities:
    """Tests for _has_any_communities."""

    @pytest.mark.asyncio
    async def test_has_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"count": 5}])
        builder = GlobalContextBuilder(graph_pool=pool)
        assert await builder._has_any_communities() is True

    @pytest.mark.asyncio
    async def test_no_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"count": 0}])
        builder = GlobalContextBuilder(graph_pool=pool)
        assert await builder._has_any_communities() is False

    @pytest.mark.asyncio
    async def test_error_returns_false(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=None)
        builder = GlobalContextBuilder(graph_pool=pool)
        assert await builder._has_any_communities() is False


class TestEntityArticleFallback:
    """Tests for _find_entity_article_fallback."""

    @pytest.mark.asyncio
    async def test_empty_query_tokens(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._find_entity_article_fallback("")
        assert result == []

    @pytest.mark.asyncio
    async def test_fallback_returns_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "entity_name": "华为",
                    "article_id": "a1",
                    "article_title": "华为新闻",
                    "entity_description": "科技公司",
                    "article_score": 0.9,
                },
            ]
        )
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._find_entity_article_fallback("华为")
        assert len(result) == 1
        assert result[0]["id"].startswith("fallback:")

    @pytest.mark.asyncio
    async def test_fallback_no_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._find_entity_article_fallback("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_fallback_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._find_entity_article_fallback("query")
        assert result == []


class TestVectorSearchCommunities:
    """Tests for _vector_search_communities."""

    @pytest.mark.asyncio
    async def test_vector_search_no_llm_client(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool, llm_client=None)
        result = await builder._vector_search_communities("test", 0)
        assert result == []

    @pytest.mark.asyncio
    async def test_vector_search_with_results(self) -> None:
        pool = _make_pool()
        mock_llm = MagicMock()
        mock_llm.embed_default = AsyncMock(return_value=[[0.1] * 128])

        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "c1",
                    "title": "Tech Community",
                    "summary": "A tech summary",
                    "rank": 5.0,
                    "entity_count": 10,
                    "full_content": "Full content here",
                    "key_entities": ["Entity1"],
                    "score": 0.85,
                },
            ]
        )

        builder = GlobalContextBuilder(graph_pool=pool, llm_client=mock_llm)
        result = await builder._vector_search_communities("test query", 0)

        assert len(result) == 1
        assert result[0]["similarity_score"] == 0.85
        assert result[0]["title"] == "Tech Community"

    @pytest.mark.asyncio
    async def test_vector_search_no_embeddings(self) -> None:
        pool = _make_pool()
        mock_llm = MagicMock()
        mock_llm.embed_default = AsyncMock(return_value=[[]])

        builder = GlobalContextBuilder(graph_pool=pool, llm_client=mock_llm)
        result = await builder._vector_search_communities("test", 0)
        assert result == []

    @pytest.mark.asyncio
    async def test_vector_search_handles_error(self) -> None:
        pool = _make_pool()
        mock_llm = MagicMock()
        mock_llm.embed_default = AsyncMock(side_effect=Exception("Embedding failed"))

        builder = GlobalContextBuilder(graph_pool=pool, llm_client=mock_llm)
        result = await builder._vector_search_communities("test", 0)
        assert result == []


class TestTextSearchCommunities:
    """Tests for _text_search_communities."""

    @pytest.mark.asyncio
    async def test_text_search_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "c1",
                    "title": "Tech",
                    "summary": "Summary",
                    "rank": 5.0,
                    "entity_count": 10,
                },
            ]
        )

        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._text_search_communities("tech", 0)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_text_search_fallback_to_top_ranked(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [],  # exact match returns empty
                [
                    {
                        "id": "c1",
                        "title": "Top",
                        "summary": "Top summary",
                        "rank": 10.0,
                        "entity_count": 20,
                    }
                ],
            ]
        )

        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._text_search_communities("nonexistent", 0)

        assert len(result) == 1
        assert result[0]["title"] == "Top"

    @pytest.mark.asyncio
    async def test_text_search_all_fail(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._text_search_communities("test", 0)

        assert result == []


class TestGetKeyEntities:
    """Tests for _get_key_entities."""

    @pytest.mark.asyncio
    async def test_get_key_entities_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "canonical_name": "Entity1",
                    "type": "ORG",
                    "description": "Desc",
                    "degree": 5,
                    "community_count": 3,
                },
            ]
        )

        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_key_entities([{"id": "c1"}])

        assert len(result) == 1
        assert result[0]["canonical_name"] == "Entity1"

    @pytest.mark.asyncio
    async def test_get_key_entities_empty_communities(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_key_entities([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_key_entities_no_ids(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_key_entities([{"id": None}])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_key_entities_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_key_entities([{"id": "c1"}])
        assert result == []


class TestGetCrossCommunityRelationships:
    """Tests for _get_cross_community_relationships."""

    @pytest.mark.asyncio
    async def test_cross_community_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "source_community": "Tech",
                    "target_community": "Finance",
                    "source_entity": "A",
                    "target_entity": "B",
                    "relation_type": "INVESTS_IN",
                },
            ]
        )

        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_cross_community_relationships([{"id": "c1"}, {"id": "c2"}])

        assert len(result) == 2  # typed + generic results combined

    @pytest.mark.asyncio
    async def test_cross_community_single_community(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_cross_community_relationships([{"id": "c1"}])
        assert result == []

    @pytest.mark.asyncio
    async def test_cross_community_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_cross_community_relationships([{"id": "c1"}, {"id": "c2"}])
        assert result == []


class TestBuildWithFullFlow:
    """Tests for build method with complete flow."""

    @pytest.mark.asyncio
    async def test_build_with_vector_search_results(self) -> None:
        pool = _make_pool()
        mock_llm = MagicMock()
        mock_llm.embed_default = AsyncMock(return_value=[[0.1] * 128])

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # vector search communities
                return [
                    {
                        "id": "c1",
                        "title": "Tech",
                        "summary": "Summary",
                        "rank": 5.0,
                        "entity_count": 10,
                        "full_content": "Full content",
                        "key_entities": [],
                        "score": 0.9,
                    }
                ]
            if call_count == 2:
                return [
                    {
                        "canonical_name": "E1",
                        "type": "ORG",
                        "description": "d",
                        "degree": 5,
                        "community_count": 1,
                    }
                ]
            return []

        pool.execute_query = mock_execute
        builder = GlobalContextBuilder(graph_pool=pool, llm_client=mock_llm)
        ctx = await builder.build("tech query")

        assert ctx.metadata["total_communities"] == 1
        assert ctx.metadata["search_method"] == "vector_similarity"

    @pytest.mark.asyncio
    async def test_build_with_fallback(self) -> None:
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return []  # vector and text search empty
            if call_count == 3:
                # fallback
                return [
                    {
                        "entity_name": "华为",
                        "article_id": "a1",
                        "article_title": "华为新闻",
                        "entity_description": "科技公司",
                        "article_score": 0.9,
                    },
                ]
            if call_count == 4:
                return [
                    {
                        "canonical_name": "E1",
                        "type": "ORG",
                        "description": "d",
                        "degree": 5,
                        "community_count": 1,
                    }
                ]
            return []

        pool.execute_query = mock_execute
        builder = GlobalContextBuilder(graph_pool=pool, fallback_enabled=True)
        ctx = await builder.build("华为")

        assert ctx.metadata.get("fallback_source") == "entity_article"
        assert ctx.metadata["search_method"] == "entity_article_fallback"

    @pytest.mark.asyncio
    async def test_build_with_cross_community_rels(self) -> None:
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    {"id": "c1", "title": "Tech", "summary": "S1", "rank": 5.0, "entity_count": 10}
                ]  # text search
            if call_count == 2:
                return [
                    {
                        "canonical_name": "E1",
                        "type": "ORG",
                        "description": "d",
                        "degree": 5,
                        "community_count": 2,
                    }
                ]  # key entities
            if call_count == 3:
                return [
                    {
                        "source_community": "Tech",
                        "target_community": "Finance",
                        "source_entity": "A",
                        "target_entity": "B",
                        "relation_type": "INVESTS_IN",
                    }
                ]
            if call_count == 4:
                return [
                    {
                        "source_community": "Tech",
                        "target_community": "Finance",
                        "source_entity": "A",
                        "target_entity": "B",
                        "relation_type": "RELATED_TO",
                    }
                ]
            return []

        pool.execute_query = mock_execute
        builder = GlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("tech finance")

        assert ctx.metadata["total_communities"] == 1


class TestBuildMapReduceContext:
    """Tests for build_map_reduce_context."""

    @pytest.mark.asyncio
    async def test_map_reduce_with_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[{"canonical_name": "E1", "type": "ORG", "description": "Desc"}]
        )

        builder = GlobalContextBuilder(graph_pool=pool, fallback_enabled=False)

        with patch.object(
            builder,
            "_find_relevant_communities",
            new_callable=AsyncMock,
            return_value=(
                [
                    {
                        "id": "c1",
                        "title": "Tech",
                        "summary": "Summary",
                        "rank": 5.0,
                        "entity_count": 10,
                    }
                ],
                False,
                "text_search",
            ),
        ):
            contexts = await builder.build_map_reduce_context("tech")

            assert len(contexts) == 1

    @pytest.mark.asyncio
    async def test_map_reduce_no_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = GlobalContextBuilder(graph_pool=pool, fallback_enabled=False)

        with patch.object(
            builder,
            "_find_relevant_communities",
            new_callable=AsyncMock,
            return_value=([], False, "none"),
        ):
            contexts = await builder.build_map_reduce_context("test")

            assert contexts == []


class TestGetCommunityEntities:
    """Tests for _get_community_entities."""

    @pytest.mark.asyncio
    async def test_get_community_entities_empty_id(self) -> None:
        pool = _make_pool()
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_community_entities("")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_community_entities_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {"canonical_name": "Entity1", "type": "ORG", "description": "A company"},
            ]
        )

        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_community_entities("c1")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_community_entities_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = GlobalContextBuilder(graph_pool=pool)
        result = await builder._get_community_entities("c1")
        assert result == []


class TestHasAnyCommunitiesExtended:
    """Extended tests for _has_any_communities."""

    @pytest.mark.asyncio
    async def test_has_communities_with_level(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"count": 3}])
        builder = GlobalContextBuilder(graph_pool=pool)
        assert await builder._has_any_communities(level=0) is True

    @pytest.mark.asyncio
    async def test_has_communities_malformed_result(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"wrong_key": 5}])
        builder = GlobalContextBuilder(graph_pool=pool)
        # get("count", 0) returns 0 -> False
        assert await builder._has_any_communities() is False

    @pytest.mark.asyncio
    async def test_has_communities_empty_result(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = GlobalContextBuilder(graph_pool=pool)
        assert await builder._has_any_communities() is False
