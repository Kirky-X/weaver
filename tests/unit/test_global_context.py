# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GlobalContextBuilder Entity-Article fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class MockRecord:
    """Minimal mock for neo4j.Record (dict-like)."""

    def __init__(self, data: dict):
        self._data = data

    def __iter__(self):
        return iter(self._data.items())

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)


class MockNeo4jPool:
    """Mock Neo4jPool that returns configurable query results.

    For Community queries: returns _community_results.
    For Entity-Article fallback queries: applies token-based filtering
    against entity_name, article_title, article_summary (case-insensitive).
    """

    def __init__(self, community_results: list | None = None, fallback_results: list | None = None):
        self._community_results = community_results
        self._fallback_raw = fallback_results or []
        self._query_count = 0
        self._fallback_called = False

    def set_fallback_results(self, results: list):
        self._fallback_raw = results

    async def execute_query(self, cypher: str, params: dict | None = None):
        self._query_count += 1
        # If the cypher contains "(a:Article)-[:MENTIONS]->" it's the fallback
        if "(a:Article)-[:MENTIONS]->" in cypher:
            self._fallback_called = True
            tokens = [t.lower() for t in params.get("tokens") or []]
            if not tokens:
                return []
            filtered = []
            for record in self._fallback_raw:
                d = dict(record) if hasattr(record, "_data") else record
                name = (d.get("entity_name") or "").lower()
                title = (d.get("article_title") or "").lower()
                summary = (d.get("article_summary") or "").lower()
                if any(tok in name or tok in title or tok in summary for tok in tokens):
                    filtered.append(record)

            # Simulate Cypher ORDER BY article_score DESC, entity_degree DESC
            def sort_key(record):
                d = dict(record) if hasattr(record, "_data") else record
                score = float(d.get("article_score") or 0.5)
                degree = float(d.get("entity_degree") or 0)
                return (score, degree)

            filtered.sort(key=sort_key, reverse=True)
            return filtered
        # Otherwise it's a Community query
        return self._community_results or []


class TestGlobalContextBuilderFallback:
    """Tests for GlobalContextBuilder Entity-Article fallback."""

    @pytest.mark.asyncio
    async def test_fallback_returns_entities_when_no_communities(self):
        """When Community nodes don't exist, fallback returns Article-Entity aggregation."""
        from modules.search.context.global_context import GlobalContextBuilder

        pool = MockNeo4jPool(
            community_results=[],  # No communities
            fallback_results=[
                MockRecord(
                    {
                        "entity_name": "小米",
                        "entity_type": "Company",
                        "entity_description": "中国智能手机制造商",
                        "article_id": "uuid-123",
                        "article_title": "小米投资AI领域",
                        "article_score": 0.85,
                        "entity_degree": 15,
                    }
                ),
            ],
        )

        builder = GlobalContextBuilder(neo4j_pool=pool)
        result = await builder._find_entity_article_fallback("小米 AI")

        assert len(result) == 1
        assert result[0]["id"].startswith("fallback:")
        assert "小米" in result[0]["title"]
        assert "小米投资AI领域" in result[0]["title"]
        assert result[0]["rank"] == pytest.approx(0.85)
        assert result[0]["entity_count"] == 1

    @pytest.mark.asyncio
    async def test_fallback_filters_by_query_keyword(self):
        """Fallback matches query tokens against entity_name and article title."""
        from modules.search.context.global_context import GlobalContextBuilder

        pool = MockNeo4jPool(
            community_results=[],
            fallback_results=[
                MockRecord(
                    {
                        "entity_name": "腾讯",
                        "entity_type": "Company",
                        "entity_description": "中国互联网巨头",
                        "article_id": "uuid-456",
                        "article_title": "腾讯云业务增长",
                        "article_score": 0.8,
                        "entity_degree": 20,
                    }
                ),
                MockRecord(
                    {
                        "entity_name": "阿里巴巴",
                        "entity_type": "Company",
                        "entity_description": "中国电商平台",
                        "article_id": "uuid-789",
                        "article_title": "阿里巴巴财报",
                        "article_score": 0.75,
                        "entity_degree": 18,
                    }
                ),
            ],
        )

        builder = GlobalContextBuilder(neo4j_pool=pool)
        # Query for "腾讯" should only match first record
        result = await builder._find_entity_article_fallback("腾讯")

        assert len(result) == 1
        assert "腾讯" in result[0]["title"]

    @pytest.mark.asyncio
    async def test_fallback_returns_empty_when_nothing_matches(self):
        """Fallback returns empty list when no entities/articles match query."""
        from modules.search.context.global_context import GlobalContextBuilder

        pool = MockNeo4jPool(
            community_results=[],
            fallback_results=[],  # No matching results
        )

        builder = GlobalContextBuilder(neo4j_pool=pool)
        result = await builder._find_entity_article_fallback("完全不存在的查询词XYZ")

        assert result == []

    @pytest.mark.asyncio
    async def test_build_sets_fallback_metadata_when_using_fallback(self):
        """build() sets metadata.fallback_source='entity_article' when results come from fallback."""
        from modules.search.context.global_context import GlobalContextBuilder

        pool = MockNeo4jPool(
            community_results=[],  # No communities
            fallback_results=[
                MockRecord(
                    {
                        "entity_name": "AI",
                        "entity_type": "Technology",
                        "entity_description": "人工智能",
                        "article_id": "uuid-001",
                        "article_title": "AI技术进展",
                        "article_score": 0.7,
                        "entity_degree": 5,
                    }
                ),
            ],
        )

        builder = GlobalContextBuilder(neo4j_pool=pool)
        context = await builder.build(query="AI", max_tokens=1000)

        assert context.metadata.get("fallback_source") == "entity_article"
        assert context.metadata.get("total_communities") == 1

    @pytest.mark.asyncio
    async def test_build_returns_empty_when_fallback_also_empty(self):
        """build() returns empty context when both Community and fallback queries return nothing."""
        from modules.search.context.global_context import GlobalContextBuilder

        pool = MockNeo4jPool(
            community_results=[],
            fallback_results=[],
        )

        builder = GlobalContextBuilder(neo4j_pool=pool)
        context = await builder.build(query="完全不存在的查询", max_tokens=1000)

        # Should have the "No Communities Found" section
        assert any(s.name == "No Communities Found" for s in context.sections)
        assert context.metadata.get("fallback_source") is None
        assert context.metadata.get("total_communities") == 0

    @pytest.mark.asyncio
    async def test_find_relevant_communities_calls_fallback_after_community_failure(self):
        """_find_relevant_communities calls _find_entity_article_fallback when Community returns empty."""
        from modules.search.context.global_context import GlobalContextBuilder

        pool = MockNeo4jPool(
            community_results=[],
            fallback_results=[
                MockRecord(
                    {
                        "entity_name": "华为",
                        "entity_type": "Company",
                        "entity_description": "中国科技公司",
                        "article_id": "uuid-hw",
                        "article_title": "华为发布新手机",
                        "article_score": 0.825,
                        "entity_degree": 10,
                    }
                ),
            ],
        )

        builder = GlobalContextBuilder(neo4j_pool=pool)
        result, used_fallback = await builder._find_relevant_communities("华为", level=0)

        assert used_fallback
        assert pool._fallback_called
        assert len(result) == 1
        assert "华为" in result[0]["title"]

    @pytest.mark.asyncio
    async def test_fallback_sorting_by_article_score(self):
        """Fallback results are sorted by article.score descending."""
        from modules.search.context.global_context import GlobalContextBuilder

        pool = MockNeo4jPool(
            community_results=[],
            fallback_results=[
                MockRecord(
                    {
                        "entity_name": "公司B",
                        "entity_type": "Company",
                        "entity_description": "描述",
                        "article_id": "uuid-b",
                        "article_title": "文章B",
                        "article_score": 0.55,
                        "entity_degree": 5,
                    }
                ),
                MockRecord(
                    {
                        "entity_name": "公司A",
                        "entity_type": "Company",
                        "entity_description": "描述",
                        "article_id": "uuid-a",
                        "article_title": "文章A",
                        "article_score": 0.925,
                        "entity_degree": 5,
                    }
                ),
            ],
        )

        builder = GlobalContextBuilder(neo4j_pool=pool)
        result = await builder._find_entity_article_fallback("公司")

        # companyA should be first (score=0.925) > companyB (score=0.55)
        assert len(result) == 2
        assert "公司A" in result[0]["title"]
        assert result[0]["rank"] == pytest.approx(0.925)
        assert result[1]["rank"] == pytest.approx(0.55)
