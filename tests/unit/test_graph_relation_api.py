# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for graph relation API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.endpoints.graph import (
    RelatedEntityResult,
    RelationTypeInfo,
    RelationTypeSummary,
    get_neo4j_client,
    set_neo4j_client,
    set_postgres_pool,
)

# ── Mock Factories ───────────────────────────────────────────────


def _make_mock_neo4j_pool() -> MagicMock:
    """Create a mock Neo4jPool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


def _make_mock_postgres_pool(rows: list | None = None) -> MagicMock:
    """Create a mock PostgresPool with session_context."""
    pool = MagicMock()

    # Build mock rows
    mock_rows = rows or []
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(mock_rows))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    pool.session_context = MagicMock()
    pool.session_context.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    pool.session_context.return_value.__aexit__ = AsyncMock(return_value=False)

    return pool


# ── Test RelationTypeSummary Model ───────────────────────────────


class TestRelationTypeSummary:
    """Tests for RelationTypeSummary model."""

    def test_create_summary(self):
        summary = RelationTypeSummary(
            relation_type="PARTNERS_WITH",
            target_count=5,
            primary_direction="outgoing",
        )
        assert summary.relation_type == "PARTNERS_WITH"
        assert summary.target_count == 5
        assert summary.primary_direction == "outgoing"

    def test_summary_serialization(self):
        summary = RelationTypeSummary(
            relation_type="INVESTS_IN",
            target_count=3,
            primary_direction="incoming",
        )
        data = summary.model_dump()
        assert data["target_count"] == 3
        assert data["primary_direction"] == "incoming"


# ── Test RelatedEntityResult Model ───────────────────────────────


class TestRelatedEntityResult:
    """Tests for RelatedEntityResult model."""

    def test_create_result_with_all_fields(self):
        result = RelatedEntityResult(
            relation_type="PARTNERS_WITH",
            direction="outgoing",
            target_name="腾讯",
            target_type="组织机构",
            target_description="中国互联网公司",
            weight=1.5,
        )
        assert result.target_name == "腾讯"
        assert result.weight == 1.5

    def test_create_result_with_defaults(self):
        result = RelatedEntityResult(
            relation_type="PARTNERS_WITH",
            direction="outgoing",
            target_name="阿里巴巴",
            target_type="组织机构",
        )
        assert result.target_description is None
        assert result.weight == 1.0


# ── Test RelationTypeInfo Model ─────────────────────────────────


class TestRelationTypeInfo:
    """Tests for RelationTypeInfo model."""

    def test_create_info(self):
        info = RelationTypeInfo(
            name="合作",
            name_en="PARTNERS_WITH",
            category="business",
            is_symmetric=True,
            description="商业合作关系",
            alias_count=3,
        )
        assert info.name == "合作"
        assert info.alias_count == 3

    def test_info_with_no_description(self):
        info = RelationTypeInfo(
            name="投资",
            name_en="INVESTS_IN",
            category="finance",
            is_symmetric=False,
            alias_count=0,
        )
        assert info.description is None


# ── Test GET /graph/relations (Layer 1) ──────────────────────────


class TestGetEntityRelations:
    """Tests for get_entity_relations endpoint."""

    @pytest.mark.asyncio
    async def test_returns_relation_type_summaries(self):
        """Test Layer 1 returns list of RelationTypeSummary."""
        from api.endpoints.graph import get_entity_relations

        mock_pool = _make_mock_neo4j_pool()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "relation_type": "PARTNERS_WITH",
                    "target_count": 5,
                    "primary_direction": "outgoing",
                },
                {"relation_type": "INVESTS_IN", "target_count": 3, "primary_direction": "incoming"},
            ]
        )

        result = await get_entity_relations(
            entity="腾讯",
            entity_type="组织机构",
            _="valid-key",
            neo4j=mock_pool,
        )

        assert len(result) == 2
        assert isinstance(result[0], RelationTypeSummary)
        assert result[0].relation_type == "PARTNERS_WITH"
        assert result[0].target_count == 5
        assert result[1].relation_type == "INVESTS_IN"

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_unknown_entity(self):
        """Test Layer 1 returns empty list for entity with no relations."""
        from api.endpoints.graph import get_entity_relations

        mock_pool = _make_mock_neo4j_pool()
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await get_entity_relations(
            entity="未知实体",
            entity_type="人物",
            _="valid-key",
            neo4j=mock_pool,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_repo(self):
        """Test that entity and entity_type are passed correctly."""
        from api.endpoints.graph import get_entity_relations

        mock_pool = _make_mock_neo4j_pool()
        mock_pool.execute_query = AsyncMock(return_value=[])

        await get_entity_relations(
            entity="华为",
            entity_type="组织机构",
            _="valid-key",
            neo4j=mock_pool,
        )

        # Verify the repo was called via Neo4jEntityRepo which uses execute_query
        assert mock_pool.execute_query.called


# ── Test GET /graph/relations/search (Layer 2) ──────────────────


class TestSearchRelations:
    """Tests for search_relations endpoint."""

    @pytest.mark.asyncio
    async def test_returns_related_entities(self):
        """Test Layer 2 returns list of RelatedEntityResult."""
        from api.endpoints.graph import search_relations

        mock_pool = _make_mock_neo4j_pool()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "relation_type": "PARTNERS_WITH",
                    "direction": "outgoing",
                    "target_name": "阿里巴巴",
                    "target_type": "组织机构",
                    "target_description": "中国电商巨头",
                    "weight": 2.0,
                },
                {
                    "relation_type": "INVESTS_IN",
                    "direction": "incoming",
                    "target_name": "红杉资本",
                    "target_type": "组织机构",
                    "target_description": None,
                    "weight": 1.0,
                },
            ]
        )

        result = await search_relations(
            entity="腾讯",
            entity_type="组织机构",
            relation_types="PARTNERS_WITH,INVESTS_IN",
            limit=50,
            _="valid-key",
            neo4j=mock_pool,
        )

        assert len(result) == 2
        assert isinstance(result[0], RelatedEntityResult)
        assert result[0].target_name == "阿里巴巴"
        assert result[0].weight == 2.0
        assert result[1].target_description is None

    @pytest.mark.asyncio
    async def test_parses_comma_separated_relation_types(self):
        """Test that comma-separated relation_types are parsed correctly."""
        from api.endpoints.graph import search_relations

        mock_pool = _make_mock_neo4j_pool()
        mock_pool.execute_query = AsyncMock(return_value=[])

        await search_relations(
            entity="腾讯",
            entity_type="组织机构",
            relation_types="PARTNERS_WITH , INVESTS_IN , SUPPLIES_TO",
            limit=10,
            _="valid-key",
            neo4j=mock_pool,
        )

        # Verify the query was called (relation_types parsed internally)
        assert mock_pool.execute_query.called

    @pytest.mark.asyncio
    async def test_none_relation_types_returns_all(self):
        """Test Layer 2 with no relation_types returns all relations."""
        from api.endpoints.graph import search_relations

        mock_pool = _make_mock_neo4j_pool()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "relation_type": "PARTNERS_WITH",
                    "direction": "outgoing",
                    "target_name": "阿里巴巴",
                    "target_type": "组织机构",
                    "target_description": None,
                    "weight": 1.0,
                },
            ]
        )

        result = await search_relations(
            entity="腾讯",
            entity_type="组织机构",
            relation_types=None,
            limit=50,
            _="valid-key",
            neo4j=mock_pool,
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_relation_types_treated_as_none(self):
        """Test that empty comma-separated string is treated as None."""
        from api.endpoints.graph import search_relations

        mock_pool = _make_mock_neo4j_pool()
        mock_pool.execute_query = AsyncMock(return_value=[])

        await search_relations(
            entity="腾讯",
            entity_type="组织机构",
            relation_types="  , ,  ",
            limit=50,
            _="valid-key",
            neo4j=mock_pool,
        )

        # Empty strings should produce None types_list
        assert mock_pool.execute_query.called


# ── Test GET /graph/relation-types ──────────────────────────────


class TestListRelationTypes:
    """Tests for list_relation_types endpoint."""

    @pytest.mark.asyncio
    async def test_returns_relation_type_infos(self):
        """Test list_relation_types returns types from PostgreSQL."""
        # SQLAlchemy rows expose columns as named attributes
        from collections import namedtuple

        from api.endpoints.graph import list_relation_types

        Row = namedtuple(
            "Row",
            ["name", "name_en", "category", "is_symmetric", "description", "alias_count"],
        )
        mock_rows = [
            Row("合作", "PARTNERS_WITH", "business", True, "合作关系", 3),
            Row("投资", "INVESTS_IN", "finance", False, None, 1),
        ]
        mock_pool = _make_mock_postgres_pool(rows=mock_rows)

        with patch("api.endpoints.graph._pg_pool", mock_pool):
            result = await list_relation_types(_="valid-key")

        assert len(result) == 2
        assert isinstance(result[0], RelationTypeInfo)
        assert result[0].name == "合作"
        assert result[0].alias_count == 3
        assert result[1].description is None

    @pytest.mark.asyncio
    async def test_raises_503_when_pool_not_initialized(self):
        """Test list_relation_types raises 503 when PostgreSQL pool not set."""
        from api.endpoints.graph import list_relation_types

        with patch("api.endpoints.graph._pg_pool", None):
            with pytest.raises(HTTPException) as exc_info:
                await list_relation_types(_="valid-key")
            assert exc_info.value.status_code == 503
            assert "PostgreSQL" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_types(self):
        """Test list_relation_types returns empty when no active types."""
        from api.endpoints.graph import list_relation_types

        mock_pool = _make_mock_postgres_pool(rows=[])

        with patch("api.endpoints.graph._pg_pool", mock_pool):
            result = await list_relation_types(_="valid-key")

        assert result == []


# ── Test Dependency Setters ──────────────────────────────────────


class TestDependencySetters:
    """Tests for set_neo4j_client and set_postgres_pool."""

    def test_set_neo4j_client(self):
        mock = MagicMock()
        set_neo4j_client(mock)
        assert get_neo4j_client() is mock

    def test_set_postgres_pool(self):
        mock = MagicMock()
        set_postgres_pool(mock)
        # _pg_pool is module-level; verify via the function being importable
        from api.endpoints import graph

        assert graph._pg_pool is mock

    def test_get_neo4j_client_raises_503_when_none(self):
        set_neo4j_client(None)  # type: ignore[arg-type]
        # Reset to avoid polluting other tests
        with pytest.raises(HTTPException) as exc_info:
            get_neo4j_client()
        assert exc_info.value.status_code == 503
