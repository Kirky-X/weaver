# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""MapperProtocol compliance tests.

Verifies that all Mapper classes implement the MapperProtocol interface
with correct method signatures and return types.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.mappers import (
    CommunityMapper,
    CommunitySearchResultMapper,
    MapperProtocol,
    Neo4jEntityMapper,
    PostgresArticleMapper,
)
from core.models.shared import (
    ArticleView,
    CommunitySearchResultView,
    CommunityView,
    EntityView,
)
from core.protocols import assert_implements

# ── Test: MapperProtocol definition ──────────────────────────────────


class TestMapperProtocolDefinition:
    """Verify MapperProtocol is properly defined as a Protocol."""

    def test_mapper_protocol_is_runtime_checkable(self) -> None:
        """MapperProtocol should be runtime_checkable."""
        assert getattr(MapperProtocol, "_is_protocol", False) is True

    def test_mapper_protocol_has_to_view_method(self) -> None:
        """MapperProtocol must define a to_view method."""
        assert hasattr(MapperProtocol, "to_view")


# ── Test: Mapper Protocol compliance ─────────────────────────────────


class TestMapperProtocolCompliance:
    """Verify each Mapper class implements MapperProtocol."""

    @pytest.mark.parametrize(
        "mapper_cls,view_cls",
        [
            (PostgresArticleMapper, ArticleView),
            (Neo4jEntityMapper, EntityView),
            (CommunityMapper, CommunityView),
            (CommunitySearchResultMapper, CommunitySearchResultView),
        ],
        ids=[
            "PostgresArticleMapper→ArticleView",
            "Neo4jEntityMapper→EntityView",
            "CommunityMapper→CommunityView",
            "CommunitySearchResultMapper→CommunitySearchResultView",
        ],
    )
    def test_mapper_implements_protocol(self, mapper_cls: type, view_cls: type) -> None:
        """Each Mapper must pass assert_implements for MapperProtocol."""
        assert_implements(mapper_cls, MapperProtocol)

    @pytest.mark.parametrize(
        "mapper_cls,view_cls",
        [
            (PostgresArticleMapper, ArticleView),
            (Neo4jEntityMapper, EntityView),
            (CommunityMapper, CommunityView),
            (CommunitySearchResultMapper, CommunitySearchResultView),
        ],
        ids=[
            "PostgresArticleMapper→ArticleView",
            "Neo4jEntityMapper→EntityView",
            "CommunityMapper→CommunityView",
            "CommunitySearchResultMapper→CommunitySearchResultView",
        ],
    )
    def test_mapper_docstring_declares_protocol(self, mapper_cls: type, view_cls: type) -> None:
        """Each Mapper docstring must declare 'Implements: MapperProtocol'."""
        docstring = mapper_cls.__doc__ or ""
        assert (
            "MapperProtocol" in docstring
        ), f"{mapper_cls.__name__} docstring must declare 'Implements: MapperProtocol'"


# ── Test: Mapper functional correctness ──────────────────────────────


class TestMapperFunctionalCorrectness:
    """Verify Mapper instances produce correct View objects."""

    def test_postgres_article_mapper_to_view(self) -> None:
        """PostgresArticleMapper should convert dict to ArticleView."""
        mapper = PostgresArticleMapper()
        data = {
            "id": "00000000-0000-0000-0000-000000000001",
            "source_url": "https://example.com/article",
            "title": "Test Article",
            "score": "0.85",
            "persist_status": "completed",
        }
        result = mapper.to_view(data)
        assert isinstance(result, ArticleView)
        assert result.title == "Test Article"
        assert result.score == 0.85

    def test_neo4j_entity_mapper_to_view(self) -> None:
        """Neo4jEntityMapper should convert dict to EntityView."""
        mapper = Neo4jEntityMapper()
        data = {
            "neo4j_id": "ent_1",
            "name": "Test Entity",
            "entity_type": "PERSON",
            "confidence": "0.95",
            "degree": "5",
        }
        result = mapper.to_view(data)
        assert isinstance(result, EntityView)
        assert result.canonical_name == "Test Entity"
        assert result.confidence == 0.95
        assert result.degree == 5

    def test_community_mapper_to_view(self) -> None:
        """CommunityMapper should convert dict to CommunityView."""
        mapper = CommunityMapper()
        data = {
            "id": "comm_1",
            "name": "Test Community",
            "level": 2,
            "rank": 0.8,
        }
        result = mapper.to_view(data)
        assert isinstance(result, CommunityView)
        assert result.title == "Test Community"

    def test_community_search_result_mapper_to_view(self) -> None:
        """CommunitySearchResultMapper should convert dict to CommunitySearchResultView."""
        mapper = CommunitySearchResultMapper()
        data = {
            "community_id": "comm_1",
            "score": "0.92",
            "title": "Test",
        }
        result = mapper.to_view(data)
        assert isinstance(result, CommunitySearchResultView)
        assert result.score == 0.92
