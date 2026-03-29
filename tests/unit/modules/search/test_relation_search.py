# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for relation type filtering in search engines and context builders."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.graph_store.relation_type_normalizer import RelationTypeNormalizer
from modules.search.context.global_context import GlobalContextBuilder
from modules.search.context.local_context import LocalContextBuilder
from modules.search.engines.local_search import LocalSearchEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4j connection pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    llm = AsyncMock()
    llm.call = AsyncMock(return_value="Test answer")
    return llm


@pytest.fixture
def local_context_builder(mock_neo4j_pool):
    """Create LocalContextBuilder with mock pool."""
    return LocalContextBuilder(
        neo4j_pool=mock_neo4j_pool,
        default_max_tokens=8000,
    )


@pytest.fixture
def global_context_builder(mock_neo4j_pool):
    """Create GlobalContextBuilder with mock pool."""
    return GlobalContextBuilder(
        neo4j_pool=mock_neo4j_pool,
        default_max_tokens=12000,
    )


# ---------------------------------------------------------------------------
# Task 9.1: LocalSearchEngine with relation_types
# ---------------------------------------------------------------------------


class TestLocalSearchWithRelationTypes:
    """Test LocalSearchEngine passes relation_types to context builder."""

    @pytest.mark.asyncio
    async def test_local_search_with_relation_types(self, mock_neo4j_pool, mock_llm):
        """Test that search passes relation_types to context builder."""
        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        # Mock context builder build method
        mock_context = MagicMock()
        mock_context.total_tokens = 500
        mock_context.sections = []
        mock_context.to_prompt = MagicMock(return_value="Context")
        mock_context.metadata = {}

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search(
            query="华为合作",
            relation_types=["PARTNERS_WITH"],
            use_llm=True,
        )

        # Verify relation_types was passed to context builder
        engine._context_builder.build.assert_called_once()
        call_kwargs = engine._context_builder.build.call_args
        assert call_kwargs.kwargs.get("relation_types") == ["PARTNERS_WITH"]

    @pytest.mark.asyncio
    async def test_local_search_without_relation_types(self, mock_neo4j_pool, mock_llm):
        """Test that search works without relation_types (backward compatible)."""
        engine = LocalSearchEngine(
            neo4j_pool=mock_neo4j_pool,
            llm=mock_llm,
        )

        mock_context = MagicMock()
        mock_context.total_tokens = 500
        mock_context.sections = []
        mock_context.to_prompt = MagicMock(return_value="Context")
        mock_context.metadata = {}

        engine._context_builder.build = AsyncMock(return_value=mock_context)

        result = await engine.search(query="华为")

        # Verify relation_types defaults to None
        engine._context_builder.build.assert_called_once()
        call_kwargs = engine._context_builder.build.call_args
        assert call_kwargs.kwargs.get("relation_types") is None


# ---------------------------------------------------------------------------
# Task 9.2: LocalContextBuilder with relation types
# ---------------------------------------------------------------------------


class TestLocalContextWithRelationTypes:
    """Test LocalContextBuilder handles relation type filtering."""

    @pytest.mark.asyncio
    async def test_local_context_with_symmetric_type(self, local_context_builder, mock_neo4j_pool):
        """Test context building with a symmetric relation type."""
        # Mock: entities found
        mock_neo4j_pool.execute_query.side_effect = [
            # _find_query_entities -> returns entity names
            [{"name": "华为"}],
            # _get_entities_with_details
            [{"canonical_name": "华为", "type": "ORG", "description": "科技公司"}],
            # _get_related_entities
            [{"canonical_name": "比亚迪", "type": "ORG", "connection_count": 3}],
            # _get_relationships (UNION ALL for typed)
            [
                {
                    "source_name": "华为",
                    "target_name": "比亚迪",
                    "relation_type": "PARTNERS_WITH",
                    "is_symmetric": True,
                }
            ],
            # _get_related_articles
            [],
        ]

        context = await local_context_builder.build(
            query="华为",
            relation_types=["PARTNERS_WITH"],
        )

        # Check that relationships section includes direction info
        rel_section = None
        for section in context.sections:
            if section.name == "Relationships":
                rel_section = section
                break

        assert rel_section is not None
        assert "PARTNERS_WITH" in rel_section.content
        assert "双向" in rel_section.content

    @pytest.mark.asyncio
    async def test_local_context_with_asymmetric_type(self, local_context_builder, mock_neo4j_pool):
        """Test context building with an asymmetric relation type."""
        mock_neo4j_pool.execute_query.side_effect = [
            # _find_query_entities
            [{"name": "工信部"}],
            # _get_entities_with_details
            [{"canonical_name": "工信部", "type": "GOV", "description": "监管机构"}],
            # _get_related_entities
            [{"canonical_name": "华为", "type": "ORG", "connection_count": 5}],
            # _get_relationships (UNION ALL for typed)
            [
                {
                    "source_name": "工信部",
                    "target_name": "华为",
                    "relation_type": "REGULATES",
                    "is_symmetric": False,
                }
            ],
            # _get_related_articles
            [],
        ]

        context = await local_context_builder.build(
            query="工信部",
            relation_types=["REGULATES"],
        )

        rel_section = None
        for section in context.sections:
            if section.name == "Relationships":
                rel_section = section
                break

        assert rel_section is not None
        assert "REGULATES" in rel_section.content
        assert "单向" in rel_section.content

    @pytest.mark.asyncio
    async def test_local_context_without_relation_types(
        self, local_context_builder, mock_neo4j_pool
    ):
        """Test that default behavior is unchanged when no relation_types."""
        mock_neo4j_pool.execute_query.side_effect = [
            # _find_query_entities
            [{"name": "华为"}],
            # _get_entities_with_details
            [{"canonical_name": "华为", "type": "ORG", "description": "科技公司"}],
            # _get_related_entities
            [],
            # _get_relationships (default RELATED_TO query)
            [
                {
                    "source_name": "华为",
                    "target_name": "比亚迪",
                    "relation_type": "合作",
                    "is_symmetric": False,
                }
            ],
            # _get_related_articles
            [],
        ]

        context = await local_context_builder.build(query="华为")

        # Should not have filtered_relation_types in metadata
        assert "filtered_relation_types" not in context.metadata


# ---------------------------------------------------------------------------
# Task 9.3: GlobalContextBuilder with relation type info
# ---------------------------------------------------------------------------


class TestGlobalContextWithRelationTypes:
    """Test GlobalContextBuilder includes relation type info."""

    @pytest.mark.asyncio
    async def test_global_context_includes_relation_types(
        self, global_context_builder, mock_neo4j_pool
    ):
        """Test that global context includes relation type direction info."""
        # _find_relevant_communities needs to return at least 2 communities
        # for _get_cross_community_relationships to be called.
        mock_neo4j_pool.execute_query.side_effect = [
            # _find_relevant_communities: first cypher (community search) -> 2 communities
            [
                {
                    "id": "comm1",
                    "title": "Tech",
                    "summary": "Tech community",
                    "rank": 0.9,
                    "entity_count": 5,
                },
                {
                    "id": "comm2",
                    "title": "Auto",
                    "summary": "Auto community",
                    "rank": 0.8,
                    "entity_count": 3,
                },
            ],
            # _get_key_entities
            [
                {
                    "canonical_name": "华为",
                    "type": "ORG",
                    "description": "科技公司",
                    "degree": 10,
                    "community_count": 2,
                }
            ],
            # _get_cross_community_relationships: typed query
            [
                {
                    "source_community": "Tech",
                    "target_community": "Auto",
                    "source_entity": "华为",
                    "target_entity": "比亚迪",
                    "relation_type": "PARTNERS_WITH",
                }
            ],
            # _get_cross_community_relationships: generic query
            [
                {
                    "source_community": "Tech",
                    "target_community": "Gov",
                    "source_entity": "华为",
                    "target_entity": "工信部",
                    "relation_type": "监管",
                }
            ],
        ]

        context = await global_context_builder.build(query="科技")

        cross_section = None
        for section in context.sections:
            if section.name == "Cross-Community Connections":
                cross_section = section
                break

        assert cross_section is not None
        assert "PARTNERS_WITH" in cross_section.content
        assert "双向" in cross_section.content
        assert "监管" in cross_section.content
        assert "单向" in cross_section.content


# ---------------------------------------------------------------------------
# Cypher pattern selection tests
# ---------------------------------------------------------------------------


class TestCypherPatternSelection:
    """Test RelationTypeNormalizer.get_cypher_pattern correctness."""

    def test_cypher_pattern_symmetric(self):
        """Symmetric relation produces undirected pattern."""
        pattern = RelationTypeNormalizer.get_cypher_pattern("PARTNERS_WITH", True)
        assert pattern == "-[r:PARTNERS_WITH]-"

    def test_cypher_pattern_asymmetric(self):
        """Asymmetric relation produces directed pattern."""
        pattern = RelationTypeNormalizer.get_cypher_pattern("REGULATES", False)
        assert pattern == "-[r:REGULATES]->"

    def test_cypher_pattern_related_to(self):
        """RELATED_TO is treated as directed when not flagged symmetric."""
        pattern = RelationTypeNormalizer.get_cypher_pattern("RELATED_TO", False)
        assert pattern == "-[r:RELATED_TO]->"

    def test_cypher_pattern_in_cypher_query(self):
        """Verify pattern is valid in a Cypher MATCH clause."""
        pattern = RelationTypeNormalizer.get_cypher_pattern("INVESTS_IN", False)
        cypher = f"MATCH (a:Entity){pattern}(b:Entity) RETURN a, b"
        assert "-[r:INVESTS_IN]->" in cypher
        assert "MATCH" in cypher

    def test_is_known_symmetric_positive(self, local_context_builder):
        """Known symmetric types return True."""
        assert local_context_builder._is_known_symmetric("PARTNERS_WITH")
        assert local_context_builder._is_known_symmetric("COLLABORATES_WITH")
        assert local_context_builder._is_known_symmetric("RELATED_TO")

    def test_is_known_symmetric_negative(self, local_context_builder):
        """Non-symmetric types return False."""
        assert not local_context_builder._is_known_symmetric("REGULATES")
        assert not local_context_builder._is_known_symmetric("INVESTS_IN")
        assert not local_context_builder._is_known_symmetric("OWNS")


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


class TestFormatRelationWithDirection:
    """Test _format_relation_with_direction output."""

    def test_format_symmetric_relation(self):
        """Symmetric relation shows 双向."""
        result = LocalContextBuilder._format_relation_with_direction(
            {
                "source_name": "华为",
                "target_name": "比亚迪",
                "relation_type": "PARTNERS_WITH",
                "is_symmetric": True,
            }
        )
        assert "华为" in result
        assert "比亚迪" in result
        assert "PARTNERS_WITH" in result
        assert "双向" in result

    def test_format_asymmetric_relation(self):
        """Asymmetric relation shows 单向."""
        result = LocalContextBuilder._format_relation_with_direction(
            {
                "source_name": "工信部",
                "target_name": "华为",
                "relation_type": "REGULATES",
                "is_symmetric": False,
            }
        )
        assert "工信部" in result
        assert "华为" in result
        assert "REGULATES" in result
        assert "单向" in result

    def test_format_default_relation(self):
        """Default relation (no is_symmetric) shows 单向."""
        result = LocalContextBuilder._format_relation_with_direction(
            {
                "source_name": "A",
                "target_name": "B",
                "relation_type": "RELATED_TO",
            }
        )
        assert "单向" in result
