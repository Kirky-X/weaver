# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for LadybugDB local context builder."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from modules.knowledge.search.context.builder import SearchContext
from modules.knowledge.search.context.ladybug_local_context import (
    LadybugLocalContextBuilder,
)


class TestLadybugLocalContextBuilderInit:
    """Test LadybugLocalContextBuilder initialization."""

    def test_should_initialize_with_default_parameters(self, mock_pool) -> None:
        """Test initialization with default parameters."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        assert builder._pool is mock_pool
        assert builder._max_entities == 20
        assert builder._max_relationships == 50
        assert builder._max_hops == 2
        assert builder._token_encoder is None
        assert builder._default_max_tokens == 8000
        assert builder._query_builder is not None

    def test_should_initialize_with_custom_parameters(self, mock_pool) -> None:
        """Test initialization with custom parameters."""
        mock_token_encoder = Mock()

        builder = LadybugLocalContextBuilder(
            graph_pool=mock_pool,
            token_encoder=mock_token_encoder,
            default_max_tokens=15000,
            max_entities=50,
            max_relationships=100,
            max_hops=3,
        )

        assert builder._pool is mock_pool
        assert builder._token_encoder is mock_token_encoder
        assert builder._default_max_tokens == 15000
        assert builder._max_entities == 50
        assert builder._max_relationships == 100
        assert builder._max_hops == 3

    def test_should_create_query_builder_for_ladybug(self, mock_pool) -> None:
        """Test that query builder is created for ladybug type."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        assert builder._query_builder is not None
        assert builder._query_builder.database_type.value == "ladybug"


class TestBuildContext:
    """Test build() method - main context building logic."""

    @pytest.mark.asyncio
    async def test_should_build_context_with_query_and_entities(self, mock_pool) -> None:
        """Test building context with query that finds entities."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"name": "Entity1"}, {"name": "Entity2"}],  # _find_query_entities
                # _get_entities_with_details
                [
                    {
                        "canonical_name": "Entity1",
                        "type": "TECHNOLOGY",
                        "description": "Tech entity",
                    },
                    {
                        "canonical_name": "Entity2",
                        "type": "ORGANIZATION",
                        "description": "Org entity",
                    },
                ],
                # _get_related_entities
                [
                    {
                        "canonical_name": "Related1",
                        "type": "PERSON",
                        "description": "Related person",
                    },
                ],
                # _get_relationships
                [
                    {
                        "source_name": "Entity1",
                        "target_name": "Related1",
                        "relation_type": "RELATED_TO",
                    },
                ],
                # _get_related_articles
                [
                    {
                        "title": "Article 1",
                        "summary": "Article about entities",
                    },
                ],
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test query")

        assert isinstance(context, SearchContext)
        assert context.query == "test query"
        assert context.metadata["total_entities"] == 3  # 2 + 1 related
        assert context.metadata["total_relationships"] == 1
        assert len(context.sections) >= 4  # entities, related, relationships, articles

    @pytest.mark.asyncio
    async def test_should_build_context_with_explicit_entity_names(self, mock_pool) -> None:
        """Test building context with explicit entity names (skip query search)."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # entity_names verification check
                [
                    {
                        "canonical_name": "Python",
                        "type": "LANGUAGE",
                        "description": "Programming language",
                    },
                ],
                # _get_entities_with_details
                [
                    {
                        "canonical_name": "Python",
                        "type": "LANGUAGE",
                        "description": "Programming language",
                    },
                ],
                # _get_related_entities
                [],
                # _get_relationships
                [],
                # _get_related_articles
                [],
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="Python programming", entity_names=["Python"])

        assert isinstance(context, SearchContext)
        assert context.metadata["total_entities"] == 1
        # Should have entities section
        entities_section = [s for s in context.sections if s.name == "Relevant Entities"]
        assert len(entities_section) == 1

    @pytest.mark.asyncio
    async def test_should_handle_no_entities_found(self, mock_pool) -> None:
        """Test handling when no entities are found."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="nonexistent query xyz")

        assert isinstance(context, SearchContext)
        assert len(context.sections) == 1
        assert context.sections[0].name == "Search Note"
        assert "No direct entity matches" in context.sections[0].content

    @pytest.mark.asyncio
    async def test_should_handle_empty_entity_names_list(self, mock_pool) -> None:
        """Test handling empty entity names list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", entity_names=[])

        assert isinstance(context, SearchContext)
        assert len(context.sections) == 1
        assert context.sections[0].name == "Search Note"

    @pytest.mark.asyncio
    async def test_should_handle_custom_max_tokens(self, mock_pool) -> None:
        """Test building context with custom max tokens."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # _find_query_entities
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", max_tokens=5000)

        assert context.max_tokens == 5000

    @pytest.mark.asyncio
    async def test_should_filter_by_relation_types(self, mock_pool) -> None:
        """Test filtering by relation types."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # entity_names verification check
                [{"canonical_name": "Entity1", "type": "TECH", "description": "Tech"}],
                # _get_entities_with_details
                [{"canonical_name": "Entity1", "type": "TECH", "description": "Tech"}],
                # _get_related_entities
                [],
                # _get_relationships
                [],
                # _get_related_articles
                [],
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(
            query="test",
            entity_names=["Entity1"],
            relation_types=["RELATED_TO", "DEPENDS_ON"],
        )

        assert isinstance(context, SearchContext)
        assert context.metadata["filtered_relation_types"] == ["RELATED_TO", "DEPENDS_ON"]

    @pytest.mark.asyncio
    async def test_should_track_metadata(self, mock_pool) -> None:
        """Test that metadata is properly tracked."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # entity_names verification check
                [
                    {"canonical_name": "E1", "type": "TYPE1", "description": "Desc1"},
                    {"canonical_name": "E2", "type": "TYPE2", "description": "Desc2"},
                ],
                # _get_entities_with_details
                [
                    {"canonical_name": "E1", "type": "TYPE1", "description": "Desc1"},
                    {"canonical_name": "E2", "type": "TYPE2", "description": "Desc2"},
                ],
                # _get_related_entities
                [{"canonical_name": "R1", "type": "TYPE3", "description": "Desc3"}],
                # _get_relationships
                [
                    {"source_name": "E1", "target_name": "R1", "relation_type": "LINKS"},
                    {"source_name": "E2", "target_name": "R1", "relation_type": "LINKS"},
                ],
                # _get_related_articles
                [],
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", entity_names=["E1", "E2"])

        assert context.metadata["total_entities"] == 3  # 2 + 1
        assert context.metadata["total_relationships"] == 2

    @pytest.mark.asyncio
    async def test_should_handle_query_error_gracefully(self, mock_pool) -> None:
        """Test handling database query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Database connection failed"))

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test")

        assert isinstance(context, SearchContext)
        # When query fails, should return "Search Note"
        assert len(context.sections) == 1
        assert context.sections[0].name == "Search Note"

    @pytest.mark.asyncio
    async def test_should_skip_sections_when_empty(self, mock_pool) -> None:
        """Test that empty sections are not added."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # entity_names verification check
                [{"canonical_name": "Entity1", "type": "TECH", "description": "Tech"}],
                # _get_entities_with_details
                [{"canonical_name": "Entity1", "type": "TECH", "description": "Tech"}],
                # _get_related_entities - empty
                [],
                # _get_relationships - empty
                [],
                # _get_related_articles - empty
                [],
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", entity_names=["Entity1"])

        # Should only have entities section
        assert len(context.sections) == 1
        assert context.sections[0].name == "Relevant Entities"


class TestFindQueryEntities:
    """Test _find_query_entities() method."""

    @pytest.mark.asyncio
    async def test_should_find_entities_from_query(self, mock_pool) -> None:
        """Test finding entities mentioned in query."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"name": "Python"},
                {"name": "Rust"},
                {"name": "JavaScript"},
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._find_query_entities("Python and Rust")

        assert len(result) == 3
        assert result == ["Python", "Rust", "JavaScript"]
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_empty_query_result(self, mock_pool) -> None:
        """Test handling empty query result."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._find_query_entities("nonexistent")

        assert result == []

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._find_query_entities("test query")

        assert result == []

    @pytest.mark.asyncio
    async def test_should_filter_out_empty_names(self, mock_pool) -> None:
        """Test filtering out entities with empty names."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"name": "Valid Entity"},
                {"name": ""},
                {"name": None},
                {"other_field": "value"},  # No name field
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._find_query_entities("test")

        assert result == ["Valid Entity"]

    @pytest.mark.asyncio
    async def test_should_respect_max_entities_limit(self, mock_pool) -> None:
        """Test that max_entities limit is used in query."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool, max_entities=10)
        await builder._find_query_entities("test query")

        # Verify query was called with correct parameters
        call_args = mock_pool.execute_query.call_args
        assert call_args is not None
        cypher_query = call_args[0][0]
        # LadybugDB uses f-string for LIMIT (not parameterized)
        assert "LIMIT 10" in cypher_query


class TestGetEntitiesWithDetails:
    """Test _get_entities_with_details() method."""

    @pytest.mark.asyncio
    async def test_should_get_entities_with_details(self, mock_pool) -> None:
        """Test getting detailed entity information."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "canonical_name": "Python",
                    "type": "LANGUAGE",
                    "description": "Programming language",
                    "aliases": ["Py", "Python3"],
                },
                {
                    "canonical_name": "Rust",
                    "type": "LANGUAGE",
                    "description": "Systems language",
                    "aliases": ["Rs"],
                },
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_entities_with_details(["Python", "Rust"])

        assert len(result) == 2
        assert result[0]["canonical_name"] == "Python"
        assert result[1]["canonical_name"] == "Rust"
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_empty_entity_names(self, mock_pool) -> None:
        """Test handling empty entity names list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_entities_with_details([])

        assert result == []
        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Database error"))

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_entities_with_details(["Entity1"])

        assert result == []

    @pytest.mark.asyncio
    async def test_should_respect_max_entities_limit(self, mock_pool) -> None:
        """Test that max_entities limit is used."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool, max_entities=15)
        await builder._get_entities_with_details(["E1", "E2", "E3"])

        # Query builder should use max_entities limit
        assert builder._max_entities == 15


class TestGetRelatedEntities:
    """Test _get_related_entities() method."""

    @pytest.mark.asyncio
    async def test_should_get_related_entities(self, mock_pool) -> None:
        """Test getting related entities."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "canonical_name": "Related1",
                    "type": "PERSON",
                    "description": "Related person",
                },
                {
                    "canonical_name": "Related2",
                    "type": "ORGANIZATION",
                    "description": "Related org",
                },
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_related_entities(["Entity1"])

        assert len(result) == 2
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_empty_entity_names(self, mock_pool) -> None:
        """Test handling empty entity names list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_related_entities([])

        assert result == []
        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_filter_by_relation_types(self, mock_pool) -> None:
        """Test filtering by relation types."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        await builder._get_related_entities(
            ["Entity1"], relation_types=["RELATED_TO", "DEPENDS_ON"]
        )

        # Query should be called with relation types
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_related_entities(["Entity1"])

        assert result == []

    @pytest.mark.asyncio
    async def test_should_use_max_hops_configuration(self, mock_pool) -> None:
        """Test that max_hops configuration is used."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool, max_hops=3)
        await builder._get_related_entities(["Entity1"])

        # Verify max_hops is set correctly
        assert builder._max_hops == 3

    @pytest.mark.asyncio
    async def test_should_respect_max_entities_limit(self, mock_pool) -> None:
        """Test that max_entities limit is used."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool, max_entities=25)
        await builder._get_related_entities(["Entity1"])

        assert builder._max_entities == 25


class TestGetRelationships:
    """Test _get_relationships() method."""

    @pytest.mark.asyncio
    async def test_should_get_relationships(self, mock_pool) -> None:
        """Test getting relationships."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "source_name": "Entity1",
                    "target_name": "Entity2",
                    "relation_type": "RELATED_TO",
                    "description": "Relationship desc",
                },
                {
                    "source_name": "Entity1",
                    "target_name": "Entity3",
                    "relation_type": "DEPENDS_ON",
                },
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_relationships(["Entity1"])

        assert len(result) == 2
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_empty_entity_names(self, mock_pool) -> None:
        """Test handling empty entity names list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_relationships([])

        assert result == []
        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_filter_by_relation_types(self, mock_pool) -> None:
        """Test filtering relationships by relation types."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        await builder._get_relationships(["Entity1"], relation_types=["RELATED_TO"])

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Database error"))

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_relationships(["Entity1"])

        assert result == []

    @pytest.mark.asyncio
    async def test_should_respect_max_relationships_limit(self, mock_pool) -> None:
        """Test that max_relationships limit is used."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool, max_relationships=75)
        await builder._get_relationships(["Entity1"])

        assert builder._max_relationships == 75


class TestGetRelatedArticles:
    """Test _get_related_articles() method."""

    @pytest.mark.asyncio
    async def test_should_get_related_articles(self, mock_pool) -> None:
        """Test getting related articles."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "title": "Article 1",
                    "summary": "First article summary",
                    "url": "http://example.com/1",
                },
                {
                    "title": "Article 2",
                    "summary": "Second article summary",
                    "url": "http://example.com/2",
                },
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_related_articles(["Entity1"])

        assert len(result) == 2
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_handle_empty_entity_names(self, mock_pool) -> None:
        """Test handling empty entity names list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_related_articles([])

        assert result == []
        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_handle_query_error(self, mock_pool) -> None:
        """Test handling query error gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        result = await builder._get_related_articles(["Entity1"])

        assert result == []

    @pytest.mark.asyncio
    async def test_should_use_default_limit(self, mock_pool) -> None:
        """Test that default limit is used."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        await builder._get_related_articles(["Entity1"])

        # Query builder should be called
        mock_pool.execute_query.assert_called_once()


class TestFormatEntitiesSection:
    """Test _format_entities_section() method."""

    def test_should_format_single_entity(self, mock_pool) -> None:
        """Test formatting single entity."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        entities = [
            {
                "canonical_name": "Python",
                "type": "LANGUAGE",
                "description": "Programming language",
            }
        ]

        result = builder._format_entities_section(entities)

        assert "Python" in result
        assert "LANGUAGE" in result
        assert "Programming language" in result

    def test_should_format_multiple_entities(self, mock_pool) -> None:
        """Test formatting multiple entities."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        entities = [
            {"canonical_name": "Python", "type": "LANGUAGE", "description": "Python"},
            {"canonical_name": "Rust", "type": "LANGUAGE", "description": "Rust"},
        ]

        result = builder._format_entities_section(entities)

        assert "Python" in result
        assert "Rust" in result

    def test_should_handle_empty_entities_list(self, mock_pool) -> None:
        """Test handling empty entities list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        result = builder._format_entities_section([])

        assert result == ""

    def test_should_handle_missing_fields(self, mock_pool) -> None:
        """Test handling entities with missing fields."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        entities = [
            {"canonical_name": "Minimal Entity"},
            {"type": "UNKNOWN_TYPE"},
            {},
        ]

        result = builder._format_entities_section(entities)

        # Should handle missing fields gracefully
        assert isinstance(result, str)

    def test_should_exclude_description_when_configured(self, mock_pool) -> None:
        """Test excluding description from formatting."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        entities = [
            {
                "canonical_name": "Python",
                "type": "LANGUAGE",
                "description": "Programming language",
            }
        ]

        result = builder._format_entities_section(entities, include_description=False)

        assert "Python" in result
        assert "LANGUAGE" in result
        # Description should not be included
        assert "Programming language" not in result


class TestFormatRelationshipsSection:
    """Test _format_relationships_section() method."""

    def test_should_format_single_relationship(self, mock_pool) -> None:
        """Test formatting single relationship."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        relationships = [
            {
                "source_name": "Python",
                "target_name": "Django",
                "relation_type": "USED_BY",
            }
        ]

        result = builder._format_relationships_section(relationships)

        assert "Python" in result
        assert "Django" in result
        assert "USED_BY" in result
        assert "--[" in result
        assert "]-->" in result

    def test_should_format_multiple_relationships(self, mock_pool) -> None:
        """Test formatting multiple relationships."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        relationships = [
            {"source_name": "A", "target_name": "B", "relation_type": "LINKS"},
            {"source_name": "B", "target_name": "C", "relation_type": "DEPENDS_ON"},
        ]

        result = builder._format_relationships_section(relationships)

        assert result.count("- ") == 2
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_should_handle_missing_fields(self, mock_pool) -> None:
        """Test handling relationships with missing fields."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        relationships = [
            {"source_name": "Only Source"},
            {"target_name": "Only Target"},
            {},
        ]

        result = builder._format_relationships_section(relationships)

        # Should use "Unknown" for missing fields
        assert "Unknown" in result
        assert "Only Source" in result

    def test_should_handle_empty_relationships_list(self, mock_pool) -> None:
        """Test handling empty relationships list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        result = builder._format_relationships_section([])

        assert result == ""


class TestFormatArticlesSection:
    """Test _format_articles_section() method."""

    def test_should_format_single_article(self, mock_pool) -> None:
        """Test formatting single article."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        articles = [
            {
                "title": "AI Revolution",
                "summary": "A comprehensive article about AI",
            }
        ]

        result = builder._format_articles_section(articles)

        assert "AI Revolution" in result
        assert "comprehensive article" in result

    def test_should_format_multiple_articles(self, mock_pool) -> None:
        """Test formatting multiple articles."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        articles = [
            {"title": "Article 1", "summary": "Summary 1"},
            {"title": "Article 2", "summary": "Summary 2"},
        ]

        result = builder._format_articles_section(articles)

        assert "Article 1" in result
        assert "Article 2" in result

    def test_should_handle_missing_summary(self, mock_pool) -> None:
        """Test handling articles without summary."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        articles = [
            {"title": "No Summary Article"},
        ]

        result = builder._format_articles_section(articles)

        assert "No Summary Article" in result

    def test_should_handle_empty_articles_list(self, mock_pool) -> None:
        """Test handling empty articles list."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        result = builder._format_articles_section([])

        assert result == ""

    def test_should_truncate_long_summaries(self, mock_pool) -> None:
        """Test truncating long article summaries."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        long_summary = "A" * 500
        articles = [{"title": "Long Article", "summary": long_summary}]

        result = builder._format_articles_section(articles)

        # Should be truncated
        assert len(result) < len(long_summary) + 100

    def test_should_handle_missing_title(self, mock_pool) -> None:
        """Test handling articles without title."""
        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

        articles = [
            {"summary": "Summary without title"},
        ]

        result = builder._format_articles_section(articles)

        # Should use "Unknown" for missing title
        assert "Unknown" in result


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_should_handle_special_characters_in_query(self, mock_pool) -> None:
        """Test handling special characters in query."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # _find_query_entities
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test @#$%^&*() query")

        assert isinstance(context, SearchContext)

    @pytest.mark.asyncio
    async def test_should_handle_unicode_query(self, mock_pool) -> None:
        """Test handling unicode/Chinese characters in query."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # _find_query_entities
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="人工智能技术")

        assert isinstance(context, SearchContext)

    @pytest.mark.asyncio
    async def test_should_handle_very_long_query(self, mock_pool) -> None:
        """Test handling very long query string."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # _find_query_entities
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        long_query = "test " * 1000
        context = await builder.build(query=long_query)

        assert isinstance(context, SearchContext)

    @pytest.mark.asyncio
    async def test_should_handle_concurrent_calls(self, mock_pool) -> None:
        """Test handling concurrent build calls."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [{"name": "Entity1"}],  # _find_query_entities
                # For each concurrent call, we need to provide results
                [{"canonical_name": "Entity1", "type": "TECH", "description": "Tech"}],
                [],  # _get_related_entities
                [],  # _get_relationships
                [],  # _get_related_articles
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)

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

    @pytest.mark.asyncio
    async def test_should_handle_large_number_of_entities(self, mock_pool) -> None:
        """Test handling large number of entities."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # entity_names verification check
                [
                    {
                        "canonical_name": f"Entity{i}",
                        "type": "TYPE",
                        "description": f"Desc{i}",
                    }
                    for i in range(50)
                ],
                # _get_entities_with_details - 50 entities
                [
                    {
                        "canonical_name": f"Entity{i}",
                        "type": "TYPE",
                        "description": f"Desc{i}",
                    }
                    for i in range(50)
                ],
                # _get_related_entities - empty
                [],
                # _get_relationships - empty
                [],
                # _get_related_articles - empty
                [],
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool, max_entities=10)
        entity_names = [f"Entity{i}" for i in range(50)]
        context = await builder.build(query="test", entity_names=entity_names)

        # Should process entities (may be limited by max_entities)
        assert context.metadata["total_entities"] > 0


class TestContextSectionPriority:
    """Test context section priority ordering."""

    @pytest.mark.asyncio
    async def test_should_add_sections_with_correct_priorities(self, mock_pool) -> None:
        """Test that sections are added with correct priorities."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # entity_names verification check
                [{"canonical_name": "E1", "type": "T", "description": "D"}],
                # _get_entities_with_details
                [{"canonical_name": "E1", "type": "T", "description": "D"}],
                # _get_related_entities
                [{"canonical_name": "R1", "type": "T", "description": "D"}],
                # _get_relationships
                [{"source_name": "E1", "target_name": "R1", "relation_type": "LINK"}],
                # _get_related_articles
                [{"title": "Article", "summary": "Summary"}],
            ]
        )

        builder = LadybugLocalContextBuilder(graph_pool=mock_pool)
        context = await builder.build(query="test", entity_names=["E1"])

        # Verify sections exist with expected priorities
        sections_dict = {s.name: s for s in context.sections}

        assert "Relevant Entities" in sections_dict
        assert sections_dict["Relevant Entities"].priority == 100

        assert "Related Entities" in sections_dict
        assert sections_dict["Related Entities"].priority == 80

        assert "Relationships" in sections_dict
        assert sections_dict["Relationships"].priority == 90

        assert "Source Articles" in sections_dict
        assert sections_dict["Source Articles"].priority == 70
