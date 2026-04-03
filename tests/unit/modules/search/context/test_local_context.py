# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LocalContextBuilder (search module)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.context.local_context import LocalContextBuilder


def _make_pool() -> AsyncMock:
    """Create a mock Neo4jPool."""
    return AsyncMock()


class TestLocalContextBuilderInit:
    """Tests for initialization."""

    def test_default_params(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        assert builder._max_entities == 20
        assert builder._max_relationships == 50
        assert builder._max_hops == 2

    def test_custom_params(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(
            neo4j_pool=pool,
            max_entities=30,
            max_relationships=100,
            max_hops=3,
        )
        assert builder._max_entities == 30
        assert builder._max_hops == 3


class TestLocalContextBuilderBuild:
    """Tests for build method."""

    @pytest.mark.asyncio
    async def test_build_no_entities(self) -> None:
        """Returns no entities found when query matches nothing."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = LocalContextBuilder(neo4j_pool=pool)
        ctx = await builder.build("unknown entity")

        assert len(ctx.sections) == 1
        assert ctx.sections[0].name == "No Entities Found"

    @pytest.mark.asyncio
    async def test_build_with_entity_names(self) -> None:
        """Builds context with pre-specified entity names."""
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_entities_with_details
                return [
                    {"canonical_name": "华为", "type": "ORG", "description": "Tech"},
                    {"canonical_name": "腾讯", "type": "ORG", "description": "Internet"},
                ]
            if call_count == 2:
                # _get_related_entities - returns empty (no related entities)
                return []
            if call_count == 3:
                # _get_relationships
                return [
                    {
                        "source_name": "华为",
                        "target_name": "腾讯",
                        "relation_type": "合作",
                        "is_symmetric": True,
                    },
                ]
            if call_count == 4:
                # _get_related_articles
                return [
                    {"id": "a1", "title": "Article 1", "summary": "Summary 1"},
                ]
            return []

        pool.execute_query = mock_execute
        builder = LocalContextBuilder(neo4j_pool=pool)
        ctx = await builder.build("华为 tech", entity_names=["华为"])

        assert len(ctx.sections) >= 2
        assert ctx.metadata["total_entities"] == 2

    @pytest.mark.asyncio
    async def test_build_with_articles_section(self) -> None:
        """Builds context with articles section."""
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_entities_with_details
                return [
                    {"canonical_name": "华为", "type": "ORG", "description": "Tech"},
                ]
            if call_count == 2:
                # _get_related_entities - returns empty
                return []
            if call_count == 3:
                # _get_relationships
                return [
                    {
                        "source_name": "华为",
                        "target_name": "腾讯",
                        "relation_type": "INVESTS_IN",
                        "is_symmetric": False,
                    },
                ]
            if call_count == 4:
                # _get_related_articles
                return [
                    {"id": "a1", "title": "华为新闻", "summary": "华为发布新成果"},
                ]
            return []

        pool.execute_query = mock_execute
        builder = LocalContextBuilder(neo4j_pool=pool)
        ctx = await builder.build("华为", entity_names=["华为"])

        assert len(ctx.sections) >= 2
        assert ctx.metadata["total_entities"] == 1
        assert ctx.metadata["total_relationships"] == 1
        # Articles section exists but total_articles not tracked in metadata
        # Check for Source Articles section instead
        section_names = [s.name for s in ctx.sections]
        assert "Source Articles" in section_names

    @pytest.mark.asyncio
    async def test_build_error_handling(self) -> None:
        """Test build handles errors gracefully."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(neo4j_pool=pool)
        ctx = await builder.build("error query")

        assert len(ctx.sections) >= 1


class TestFindQueryEntities:
    """Tests for _find_query_entities."""

    @pytest.mark.asyncio
    async def test_finds_entities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"name": "华为"}])
        builder = LocalContextBuilder(neo4j_pool=pool)
        names = await builder._find_query_entities("华为")
        assert names == ["华为"]

    @pytest.mark.asyncio
    async def test_error_returns_empty(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("db error"))
        builder = LocalContextBuilder(neo4j_pool=pool)
        names = await builder._find_query_entities("华为")
        assert names == []


class TestGetEntitiesWithDetails:
    """Tests for _get_entities_with_details."""

    @pytest.mark.asyncio
    async def test_get_entities_with_details(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {"canonical_name": "华为", "type": "ORG", "description": "Tech"},
            ]
        )
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_entities_with_details(["华为"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_entities_with_details_empty(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_entities_with_details([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_entities_with_details_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_entities_with_details(["华为"])
        assert result == []


class TestGetRelationships:
    """Tests for _get_relationships."""

    @pytest.mark.asyncio
    async def test_get_relationships_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "source_name": "华为",
                    "target_name": "腾讯",
                    "relation_type": "INVESTS_IN",
                    "is_symmetric": False,
                },
            ]
        )
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_relationships(["华为", "腾讯"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_relationships_empty(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_relationships([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_relationships_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_relationships(["华为", "腾讯"])
        assert result == []


class TestGetRelatedArticles:
    """Tests for _get_related_articles."""

    @pytest.mark.asyncio
    async def test_get_related_articles_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {"id": "a1", "title": "News", "summary": "Summary"},
            ]
        )
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_related_articles(["华为"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_related_articles_empty(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_related_articles([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_related_articles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = await builder._get_related_articles(["华为"])
        assert result == []


class TestFormatEntitiesSection:
    """Tests for _format_entities_section."""

    def test_format_entities(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        entities = [
            {"canonical_name": "华为", "type": "ORG", "description": "Tech company"},
        ]
        result = builder._format_entities_section(entities)
        assert "华为" in result
        assert "ORG" in result

    def test_format_entities_empty(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = builder._format_entities_section([])
        assert result == ""


class TestFormatRelationshipSection:
    """Tests for _format_relationship_section."""

    def test_format_relationships(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        rels = [
            {
                "source_name": "A",
                "target_name": "B",
                "relation_type": "PARTNERS_WITH",
                "is_symmetric": True,
            },
        ]
        result = builder._format_relationships_section(rels)
        assert "A" in result
        assert "双向" in result

    def test_format_relationships_empty(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = builder._format_relationships_section([])
        assert result == ""


class TestFormatArticlesSection:
    """Tests for _format_articles_section."""

    def test_format_articles_with_content(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        articles = [
            {"title": "Article 1", "summary": "A summary of article 1"},
            {"title": "Article 2", "summary": ""},
        ]
        result = builder._format_articles_section(articles)
        assert "Article 1" in result
        assert "A summary" in result

    def test_format_articles_empty(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        result = builder._format_articles_section([])
        assert result == ""
