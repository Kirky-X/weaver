# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LocalContextBuilder."""

from __future__ import annotations

from unittest.mock import AsyncMock

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
    async def test_build_with_provided_entity_names(self) -> None:
        """Builds context with pre-specified entity names."""
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    {
                        "canonical_name": "华为",
                        "type": "组织机构",
                        "description": "科技公司",
                        "aliases": ["Huawei"],
                    }
                ]
            if call_count == 2:
                return [{"canonical_name": "比亚迪", "type": "组织机构", "connection_count": 3}]
            if call_count == 3:
                return [
                    {
                        "source_name": "华为",
                        "target_name": "比亚迪",
                        "relation_type": "合作",
                        "is_symmetric": True,
                    }
                ]
            if call_count == 4:
                return [
                    {
                        "id": "a1",
                        "title": "新闻",
                        "summary": "华为比亚迪合作",
                        "publish_time": "2025-01-01",
                    }
                ]
            return []

        pool.execute_query = mock_execute
        builder = LocalContextBuilder(neo4j_pool=pool)
        ctx = await builder.build("华为", entity_names=["华为"])

        assert ctx.metadata.get("total_entities", 0) > 0

    @pytest.mark.asyncio
    async def test_build_with_relation_types_filter(self) -> None:
        """Builds context with relation type filtering."""
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    {"canonical_name": "华为", "type": "组织", "description": "Tech", "aliases": []}
                ]
            if call_count == 2:
                return []
            if call_count == 3:
                return []
            return []

        pool.execute_query = mock_execute
        builder = LocalContextBuilder(neo4j_pool=pool)
        ctx = await builder.build("华为", entity_names=["华为"], relation_types=["PARTNERS_WITH"])

        assert ctx.metadata.get("filtered_relation_types") == ["PARTNERS_WITH"]


class TestFormatMethods:
    """Tests for formatting methods."""

    def test_format_entities_section(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        entities = [
            {"canonical_name": "华为", "type": "组织机构", "description": "科技公司"},
        ]
        result = builder._format_entities_section(entities)
        assert "华为" in result

    def test_format_entities_no_description(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        entities = [
            {"canonical_name": "华为", "type": "组织"},
        ]
        result = builder._format_entities_section(entities, include_description=False)
        assert "华为" in result

    def test_format_relationships_section(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        rels = [
            {"source_name": "A", "target_name": "B", "relation_type": "合作", "is_symmetric": True},
        ]
        result = builder._format_relationships_section(rels)
        assert "A" in result
        assert "B" in result

    def test_format_articles_section(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool)
        articles = [
            {"title": "Test Article", "summary": "Summary text"},
        ]
        result = builder._format_articles_section(articles)
        assert "Test Article" in result


class TestStaticMethods:
    """Tests for static helper methods."""

    def test_is_known_symmetric(self) -> None:
        assert LocalContextBuilder._is_known_symmetric("PARTNERS_WITH") is True
        assert LocalContextBuilder._is_known_symmetric("RELATED_TO") is True
        assert LocalContextBuilder._is_known_symmetric("REGULATES") is False

    def test_format_relation_with_direction_symmetric(self) -> None:
        rel = {
            "source_name": "A",
            "target_name": "B",
            "relation_type": "PARTNERS_WITH",
            "is_symmetric": True,
        }
        result = LocalContextBuilder._format_relation_with_direction(rel)
        assert "双向" in result

    def test_format_relation_with_direction_asymmetric(self) -> None:
        rel = {
            "source_name": "A",
            "target_name": "B",
            "relation_type": "REGULATES",
            "is_symmetric": False,
        }
        result = LocalContextBuilder._format_relation_with_direction(rel)
        assert "单向" in result


class TestBuildRelMatchClause:
    """Tests for _build_rel_match_clause."""

    def test_default_clause(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool, max_hops=2)
        clause = builder._build_rel_match_clause()
        assert "RELATED_TO" in clause
        assert "1..2" in clause

    def test_typed_clause(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(neo4j_pool=pool, max_hops=2)
        clause = builder._build_rel_match_clause(
            relation_types=["PARTNERS_WITH", "COLLABORATES_WITH"]
        )
        assert "PARTNERS_WITH" in clause
        assert "COLLABORATES_WITH" in clause


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
