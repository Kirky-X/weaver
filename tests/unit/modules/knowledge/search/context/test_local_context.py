# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LocalContextBuilder - comprehensive coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db.safe_query import InvalidIdentifierError
from modules.knowledge.search.context.local_context import LocalContextBuilder


def _make_pool() -> AsyncMock:
    """Create a mock Neo4jPool."""
    return AsyncMock()


class TestLocalContextBuilderBuild:
    """Tests for build() method."""

    @pytest.mark.asyncio
    async def test_build_no_entities(self) -> None:
        """Returns no entities found when query matches nothing."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = LocalContextBuilder(graph_pool=pool)
        ctx = await builder.build("unknown entity")

        assert len(ctx.sections) == 2
        assert ctx.sections[0].name == "Search Note"
        assert ctx.sections[1].name == "No Entities Found"

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
        builder = LocalContextBuilder(graph_pool=pool)
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
        builder = LocalContextBuilder(graph_pool=pool)
        ctx = await builder.build("华为", entity_names=["华为"], relation_types=["PARTNERS_WITH"])

        assert ctx.metadata.get("filtered_relation_types") == ["PARTNERS_WITH"]

    @pytest.mark.asyncio
    async def test_build_with_custom_max_tokens(self) -> None:
        """Test build with custom max_tokens."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = LocalContextBuilder(graph_pool=pool)
        ctx = await builder.build("test", max_tokens=4000)

        assert ctx.max_tokens == 4000

    @pytest.mark.asyncio
    async def test_build_auto_finds_entities(self) -> None:
        """Test build auto-finds entities when no entity_names provided."""
        pool = _make_pool()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"name": "华为"}]  # _find_query_entities
            if call_count == 2:
                return [
                    {"canonical_name": "华为", "type": "组织", "description": "Tech", "aliases": []}
                ]
            return []

        pool.execute_query = mock_execute
        builder = LocalContextBuilder(graph_pool=pool)
        ctx = await builder.build("华为")

        assert ctx.metadata.get("total_entities", 0) >= 1


class TestLocalContextBuilderFindQueryEntities:
    """Tests for _find_query_entities."""

    @pytest.mark.asyncio
    async def test_finds_entities(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"name": "华为"}])
        builder = LocalContextBuilder(graph_pool=pool)
        names = await builder._find_query_entities("华为")
        assert names == ["华为"]

    @pytest.mark.asyncio
    async def test_error_returns_empty(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("db error"))
        builder = LocalContextBuilder(graph_pool=pool)
        names = await builder._find_query_entities("华为")
        assert names == []

    @pytest.mark.asyncio
    async def test_no_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = LocalContextBuilder(graph_pool=pool)
        names = await builder._find_query_entities("nonexistent")
        assert names == []

    @pytest.mark.asyncio
    async def test_filters_none_names(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[{"name": "华为"}, {"name": None}])
        builder = LocalContextBuilder(graph_pool=pool)
        names = await builder._find_query_entities("华为")
        assert names == ["华为"]


class TestLocalContextBuilderGetEntitiesWithDetails:
    """Tests for _get_entities_with_details."""

    @pytest.mark.asyncio
    async def test_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "canonical_name": "华为",
                    "type": "组织",
                    "description": "Tech",
                    "aliases": ["Huawei"],
                },
            ]
        )
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_entities_with_details(["华为"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_names(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_entities_with_details([])
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_entities_with_details(["华为"])
        assert result == []


class TestLocalContextBuilderGetRelatedEntities:
    """Tests for _get_related_entities."""

    @pytest.mark.asyncio
    async def test_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {"canonical_name": "比亚迪", "type": "组织", "connection_count": 3},
            ]
        )
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_related_entities(["华为"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_names(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_related_entities([])
        assert result == []

    @pytest.mark.asyncio
    async def test_with_relation_types(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_related_entities(["华为"], relation_types=["PARTNERS_WITH"])
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_related_entities(["华为"])
        assert result == []


class TestLocalContextBuilderGetRelationships:
    """Tests for _get_relationships."""

    @pytest.mark.asyncio
    async def test_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "source_name": "华为",
                    "target_name": "比亚迪",
                    "relation_type": "合作",
                    "is_symmetric": True,
                },
            ]
        )
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_relationships(["华为"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_names(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_relationships([])
        assert result == []

    @pytest.mark.asyncio
    async def test_validates_relation_types(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_relationships(["华为"], relation_types=["PARTNERS_WITH"])
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_rejects_cypher_injection(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(return_value=[])
        builder = LocalContextBuilder(graph_pool=pool)

        with pytest.raises((InvalidIdentifierError, ValueError)):
            await builder._get_relationships(
                ["华为"],
                relation_types=["KNOWS']; MATCH (n) DETACH DELETE n //"],
            )

    @pytest.mark.asyncio
    async def test_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_relationships(["华为"])
        assert result == []


class TestLocalContextBuilderGetRelatedArticles:
    """Tests for _get_related_articles."""

    @pytest.mark.asyncio
    async def test_with_results(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "a1",
                    "title": "新闻",
                    "summary": "华为新闻",
                    "publish_time": "2025-01-01",
                },
            ]
        )
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_related_articles(["华为"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_names(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_related_articles([])
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(side_effect=Exception("DB error"))
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder._get_related_articles(["华为"])
        assert result == []

    @pytest.mark.asyncio
    async def test_with_article_repo(self) -> None:
        """Test article body enrichment from PostgreSQL."""
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "a1",
                    "title": "新闻",
                    "summary": "华为新闻",
                    "publish_time": "2025-01-01",
                },
            ]
        )
        mock_article_repo = AsyncMock()
        mock_article = MagicMock()
        mock_article.body = "华为发布了新产品。这是一个重要的里程碑。"
        mock_article_repo.get = AsyncMock(return_value=mock_article)

        builder = LocalContextBuilder(graph_pool=pool, article_repo=mock_article_repo)
        result = await builder._get_related_articles(["华为"])

        assert len(result) == 1
        assert "body_excerpt" in result[0]


class TestLocalContextBuilderFormatMethods:
    """Tests for formatting methods."""

    def test_format_entities_section(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        entities = [
            {"canonical_name": "华为", "type": "组织机构", "description": "科技公司"},
        ]
        result = builder.format_entities_section(entities)
        assert "华为" in result

    def test_format_entities_no_description(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        entities = [
            {"canonical_name": "华为", "type": "组织"},
        ]
        result = builder.format_entities_section(entities, include_description=False)
        assert "华为" in result

    def test_format_relationships_section(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        rels = [
            {"source_name": "A", "target_name": "B", "relation_type": "合作", "is_symmetric": True},
        ]
        result = builder.format_relationships_section(rels)
        assert "A" in result
        assert "B" in result

    def test_format_articles_section(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        articles = [
            {"title": "Test Article", "summary": "Summary text"},
        ]
        result = builder.format_articles_section(articles)
        assert "Test Article" in result

    def test_format_articles_with_body_excerpt(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        articles = [
            {"title": "Test Article", "summary": "Summary", "body_excerpt": "Key excerpt"},
        ]
        result = builder.format_articles_section(articles)
        assert "原文片段" in result


class TestLocalContextBuilderStaticMethods:
    """Tests for static helper methods."""

    def test_is_known_symmetric(self) -> None:
        assert LocalContextBuilder.is_known_symmetric("PARTNERS_WITH") is True
        assert LocalContextBuilder.is_known_symmetric("RELATED_TO") is True
        assert LocalContextBuilder.is_known_symmetric("COLLABORATES_WITH") is True
        assert LocalContextBuilder.is_known_symmetric("REGULATES") is False
        assert LocalContextBuilder.is_known_symmetric("INVESTS_IN") is False

    def test_format_relation_with_direction_symmetric(self) -> None:
        rel = {
            "source_name": "A",
            "target_name": "B",
            "relation_type": "PARTNERS_WITH",
            "is_symmetric": True,
        }
        result = LocalContextBuilder.format_relation_with_direction(rel)
        assert "双向" in result
        assert "A" in result
        assert "B" in result

    def test_format_relation_with_direction_asymmetric(self) -> None:
        rel = {
            "source_name": "A",
            "target_name": "B",
            "relation_type": "REGULATES",
            "is_symmetric": False,
        }
        result = LocalContextBuilder.format_relation_with_direction(rel)
        assert "单向" in result

    def test_format_relation_default_values(self) -> None:
        rel = {}
        result = LocalContextBuilder.format_relation_with_direction(rel)
        assert "Unknown" in result
        assert "RELATED_TO" in result


class TestLocalContextBuilderBuildRelMatchClause:
    """Tests for _build_rel_match_clause."""

    def test_default_clause(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool, max_hops=2)
        clause = builder._build_rel_match_clause()
        assert "RELATED_TO" in clause
        assert "1..2" in clause

    def test_typed_clause(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool, max_hops=2)
        clause = builder._build_rel_match_clause(
            relation_types=["PARTNERS_WITH", "COLLABORATES_WITH"]
        )
        assert "PARTNERS_WITH" in clause
        assert "COLLABORATES_WITH" in clause

    def test_custom_max_hops(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool, max_hops=3)
        clause = builder._build_rel_match_clause()
        assert "1..3" in clause


class TestLocalContextBuilderExtractKeyExcerpt:
    """Tests for _extract_key_excerpt method."""

    def test_extracts_matching_sentences(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)

        body = "华为发布了新产品。比亚迪也发布了新产品。这是另一句话。华为和比亚迪合作了。"
        excerpt = builder.extract_key_excerpt(body, ["华为"], max_tokens=300)

        assert "华为" in excerpt

    def test_fallback_to_head_tail(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)

        body = "这是第一句话。这是第二句话。这是第三句话。这是第四句话。"
        excerpt = builder.extract_key_excerpt(body, ["不存在的实体"], max_tokens=300)

        assert len(excerpt) > 0

    def test_empty_body(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)

        excerpt = builder.extract_key_excerpt("", ["华为"], max_tokens=300)
        assert excerpt == ""


class TestLocalContextBuilderFetchArticleBodies:
    """Tests for _fetch_article_bodies."""

    @pytest.mark.asyncio
    async def test_no_article_repo(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool, article_repo=None)
        result = await builder.fetch_article_bodies(["a1"])
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_ids(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        result = await builder.fetch_article_bodies([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_with_article_repo(self) -> None:
        pool = _make_pool()
        mock_article = MagicMock()
        mock_article.body = "Article body content"
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(return_value=mock_article)

        builder = LocalContextBuilder(graph_pool=pool, article_repo=mock_repo)
        result = await builder.fetch_article_bodies(["a1"])

        assert "a1" in result
        assert result["a1"] == "Article body content"

    @pytest.mark.asyncio
    async def test_handles_fetch_error(self) -> None:
        pool = _make_pool()
        mock_repo = AsyncMock()
        mock_repo.get = AsyncMock(side_effect=Exception("DB error"))

        builder = LocalContextBuilder(graph_pool=pool, article_repo=mock_repo)
        result = await builder.fetch_article_bodies(["a1"])

        assert result == {}


class TestLocalContextBuilderInit:
    """Tests for initialization."""

    def test_default_params(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        assert builder._max_entities == 20
        assert builder._max_relationships == 50
        assert builder._max_hops == 2

    def test_custom_params(self) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(
            graph_pool=pool,
            max_entities=30,
            max_relationships=100,
            max_hops=3,
        )
        assert builder._max_entities == 30
        assert builder._max_hops == 3


class TestLocalContextBuilderSecurity:
    """Security tests for Cypher injection prevention."""

    @pytest.mark.parametrize(
        "relation_type",
        [
            "PARTNERS_WITH",
            "COLLABORATES_WITH",
            "RELATED_TO",
            "中文关系",
            "KNOWS",
        ],
    )
    def test_build_rel_match_clause_accepts_valid_types(self, relation_type) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        clause = builder._build_rel_match_clause(relation_types=[relation_type])
        assert relation_type in clause

    @pytest.mark.parametrize(
        "relation_type",
        [
            "partners_with",
            "KNOWS']; MATCH (n) DETACH DELETE n //",
            "123INVALID",
            "invalid-type",
            "type with space",
        ],
    )
    def test_build_rel_match_clause_rejects_malicious_types(self, relation_type) -> None:
        pool = _make_pool()
        builder = LocalContextBuilder(graph_pool=pool)
        with pytest.raises((InvalidIdentifierError, ValueError)):
            builder._build_rel_match_clause(relation_types=[relation_type])

    @pytest.mark.asyncio
    async def test_build_with_malicious_relation_types_raises_error(self) -> None:
        pool = _make_pool()
        pool.execute_query = AsyncMock(
            return_value=[
                {"canonical_name": "华为", "type": "组织", "description": "", "aliases": []}
            ]
        )
        builder = LocalContextBuilder(graph_pool=pool)

        with pytest.raises((InvalidIdentifierError, ValueError)):
            await builder.build(
                "华为",
                entity_names=["华为"],
                relation_types=["MALICIOUS`; DROP ALL //"],
            )
