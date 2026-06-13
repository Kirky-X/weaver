# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for BaseGlobalContextBuilder - Template Method pattern."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.context.base_global_context import BaseGlobalContextBuilder

# Valid UUIDs for tests
UUID_C1 = "550e8400-e29b-41d4-a716-446655440001"
UUID_C2 = "550e8400-e29b-41d4-a716-446655440002"


class ConcreteGlobalContextBuilder(BaseGlobalContextBuilder):
    """Concrete implementation for testing BaseGlobalContextBuilder."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Use Neo4j query builder by default for testing
        from core.db.graph_query import create_graph_query_builder

        self._query_builder = create_graph_query_builder("neo4j")

    async def _vector_search_communities(self, query: str, level: int) -> list[dict[str, Any]]:
        return []

    async def _find_entity_article_fallback(self, query: str) -> list[dict[str, Any]]:
        return []

    async def _get_cross_community_relationships(
        self, communities: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return []


def _make_pool() -> AsyncMock:
    """Create a mock graph pool."""
    pool = AsyncMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


class TestBaseGlobalContextBuilderBuild:
    """Tests for build() Template Method."""

    @pytest.mark.asyncio
    async def test_build_no_communities_at_all(self) -> None:
        """Returns hint when no communities exist."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [],  # text fallback
                [{"count": 0}],  # has_any_communities
            ]
        )
        builder = ConcreteGlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("test query")
        assert ctx.metadata.get("hint") is not None
        assert "rebuild" in ctx.metadata["hint"]

    @pytest.mark.asyncio
    async def test_build_no_relevant_communities_but_some_exist(self) -> None:
        """Returns no communities found when communities exist but none match."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [],  # text search
                [],  # text fallback
                [{"count": 5}],  # has_any_communities
            ]
        )
        builder = ConcreteGlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("test query")
        assert ctx.metadata.get("total_communities") == 0

    @pytest.mark.asyncio
    async def test_build_with_communities(self) -> None:
        """Builds context with community data and key entities."""
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [  # text search
                    {
                        "id": UUID_C1,
                        "title": "Tech",
                        "summary": "Technology community",
                        "rank": 5.0,
                        "entity_count": 10,
                    }
                ]
            if call_count == 2:
                return [  # key entities
                    {
                        "canonical_name": "Entity1",
                        "type": "ORG",
                        "degree": 5,
                        "community_count": 1,
                    }
                ]
            return []  # cross-community (only 1 comm)

        pool.execute_query = mock_execute
        builder = ConcreteGlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("tech query")

        assert ctx.metadata["total_communities"] == 1
        assert ctx.metadata["search_method"] == "text_search"
        # Should have Community Summaries and Key Entities sections
        section_names = [s.name for s in ctx.sections]
        assert "Community Summaries" in section_names
        assert "Key Entities" in section_names

    @pytest.mark.asyncio
    async def test_build_skips_supplementary_when_hook_returns_true(self) -> None:
        """Skips key entities and cross-community rels when _should_skip_supplementary is True."""

        class SkipSupplementaryBuilder(ConcreteGlobalContextBuilder):
            def _should_skip_supplementary(self, used_fallback: bool) -> bool:
                return True

        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [  # text search
                    {
                        "id": UUID_C1,
                        "title": "Tech",
                        "summary": "Summary",
                        "rank": 5.0,
                        "entity_count": 10,
                    }
                ],
            ]
        )
        builder = SkipSupplementaryBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("tech query")

        section_names = [s.name for s in ctx.sections]
        assert "Community Summaries" in section_names
        assert "Key Entities" not in section_names
        assert "Cross-Community Connections" not in section_names

    @pytest.mark.asyncio
    async def test_build_with_cross_community_rels(self) -> None:
        """Builds context with cross-community relationships."""
        pool = _make_pool()

        class CrossCommBuilder(ConcreteGlobalContextBuilder):
            async def _get_cross_community_relationships(
                self, communities: list[dict[str, Any]]
            ) -> list[dict[str, Any]]:
                return [
                    {
                        "source_community": "Tech",
                        "target_community": "Finance",
                        "source_entity": "A",
                        "target_entity": "B",
                        "relation_type": "INVESTS_IN",
                    }
                ]

        pool.execute_query = AsyncMock(
            side_effect=[
                [  # text search
                    {
                        "id": UUID_C1,
                        "title": "Tech",
                        "summary": "S1",
                        "rank": 5.0,
                        "entity_count": 10,
                    },
                    {
                        "id": UUID_C2,
                        "title": "Finance",
                        "summary": "S2",
                        "rank": 4.0,
                        "entity_count": 8,
                    },
                ],
                [  # key entities
                    {
                        "canonical_name": "E1",
                        "type": "ORG",
                        "description": "d",
                        "degree": 5,
                        "community_count": 2,
                    }
                ],
            ]
        )
        builder = CrossCommBuilder(graph_pool=pool, fallback_enabled=False)
        ctx = await builder.build("tech finance")

        section_names = [s.name for s in ctx.sections]
        assert "Cross-Community Connections" in section_names

    @pytest.mark.asyncio
    async def test_build_with_fallback_metadata(self) -> None:
        """Sets fallback_source metadata when fallback is used."""

        class FallbackBuilder(ConcreteGlobalContextBuilder):
            async def _find_entity_article_fallback(self, query: str) -> list[dict[str, Any]]:
                return [
                    {
                        "id": "entity:AI",
                        "title": "AI",
                        "summary": "Artificial Intelligence",
                        "rank": 0.8,
                    }
                ]

        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = FallbackBuilder(graph_pool=pool, fallback_enabled=True)
        ctx = await builder.build("AI")

        assert ctx.metadata.get("fallback_source") == "entity_article"
        assert ctx.metadata["search_method"] == "entity_article_fallback"


class TestBaseGlobalContextBuilderFindRelevantCommunities:
    """Tests for find_relevant_communities cascade."""

    @pytest.mark.asyncio
    async def test_vector_search_first(self) -> None:
        """Vector search is tried first when LLM client is available."""

        class VectorBuilder(ConcreteGlobalContextBuilder):
            async def _vector_search_communities(
                self, query: str, level: int
            ) -> list[dict[str, Any]]:
                return [{"id": UUID_C1, "title": "Found", "summary": "S", "rank": 1.0}]

        pool = _make_pool()
        mock_llm = MagicMock()
        builder = VectorBuilder(graph_pool=pool, llm_client=mock_llm)
        communities, used_fallback, method = await builder.find_relevant_communities("test", 0)

        assert len(communities) == 1
        assert method == "vector_similarity"
        assert used_fallback is False

    @pytest.mark.asyncio
    async def test_text_search_when_no_llm(self) -> None:
        """Text search is used when no LLM client."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [{"id": UUID_C1, "title": "T", "summary": "S", "rank": 1.0}],
            ]
        )
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        communities, used_fallback, method = await builder.find_relevant_communities("test", 0)

        assert method == "text_search"
        assert used_fallback is False

    @pytest.mark.asyncio
    async def test_fallback_when_all_else_fails(self) -> None:
        """Entity-article fallback is used when vector and text search fail."""

        class FallbackBuilder(ConcreteGlobalContextBuilder):
            async def _find_entity_article_fallback(self, query: str) -> list[dict[str, Any]]:
                return [{"id": "entity:X", "title": "X", "summary": "S", "rank": 0.5}]

        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = FallbackBuilder(graph_pool=pool, fallback_enabled=True)
        communities, used_fallback, method = await builder.find_relevant_communities("test", 0)

        assert method == "entity_article_fallback"
        assert used_fallback is True

    @pytest.mark.asyncio
    async def test_no_results_when_fallback_disabled(self) -> None:
        """Returns empty when fallback is disabled and other methods fail."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = ConcreteGlobalContextBuilder(graph_pool=pool, fallback_enabled=False)
        communities, used_fallback, method = await builder.find_relevant_communities("test", 0)

        assert communities == []
        assert method == "none"


class TestBaseGlobalContextBuilderHasKeyEntities:
    """Tests for _get_key_entities with UUID filtering."""

    @pytest.mark.asyncio
    async def test_filters_non_uuid_ids(self) -> None:
        """Filters out non-UUID IDs like fallback results."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "canonical_name": "E1",
                    "type": "ORG",
                    "description": "Desc",
                    "degree": 5,
                    "community_count": 1,
                }
            ]
        )
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        # Mix of UUID and non-UUID IDs
        communities = [
            {"id": UUID_C1},
            {"id": "fallback:a1"},
            {"id": "entity:AI"},
        ]
        result = await builder._get_key_entities(communities)
        assert len(result) == 1
        # Verify only UUID was passed to query
        call_args = pool.execute_query.call_args
        assert call_args[0][1]["community_ids"] == [UUID_C1]

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_non_uuid(self) -> None:
        """Returns empty when all IDs are non-UUID."""
        pool = _make_pool()
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        communities = [
            {"id": "fallback:a1"},
            {"id": "entity:AI"},
        ]
        result = await builder._get_key_entities(communities)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_communities(self) -> None:
        """Returns empty for empty communities list."""
        pool = _make_pool()
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        result = await builder._get_key_entities([])
        assert result == []


class TestBaseGlobalContextBuilderHasAnyCommunities:
    """Tests for has_any_communities."""

    @pytest.mark.asyncio
    async def test_has_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"count": 5}])
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        assert await builder.has_any_communities() is True

    @pytest.mark.asyncio
    async def test_no_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"count": 0}])
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        assert await builder.has_any_communities() is False

    @pytest.mark.asyncio
    async def test_error_returns_false(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        assert await builder.has_any_communities() is False


class TestBaseGlobalContextBuilderGetCommunityEntities:
    """Tests for get_community_entities."""

    @pytest.mark.asyncio
    async def test_with_valid_id(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[{"canonical_name": "E1", "type": "ORG", "description": "Desc"}]
        )
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        result = await builder.get_community_entities(UUID_C1)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_id(self) -> None:
        pool = _make_pool()
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        result = await builder.get_community_entities("")
        assert result == []


class TestBaseGlobalContextBuilderBuildMapReduceContext:
    """Tests for build_map_reduce_context."""

    @pytest.mark.asyncio
    async def test_with_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            side_effect=[
                [  # text search
                    {
                        "id": UUID_C1,
                        "title": "Tech",
                        "summary": "Tech summary",
                        "rank": 0.9,
                    }
                ],
                [  # community entities
                    {"canonical_name": "E1", "type": "ORG", "description": "Desc"}
                ],
            ]
        )
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        contexts = await builder.build_map_reduce_context("tech", max_tokens_per_community=2000)

        assert len(contexts) == 1
        assert contexts[0].query == "tech"

    @pytest.mark.asyncio
    async def test_no_communities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        contexts = await builder.build_map_reduce_context("test")
        assert contexts == []


class TestBaseGlobalContextBuilderHooks:
    """Tests for hook methods."""

    def test_default_should_skip_supplementary(self) -> None:
        pool = _make_pool()
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        assert builder._should_skip_supplementary(False) is False
        assert builder._should_skip_supplementary(True) is False

    def test_default_include_cross_community_direction(self) -> None:
        pool = _make_pool()
        builder = ConcreteGlobalContextBuilder(graph_pool=pool)
        assert builder._include_cross_community_direction() is False
