# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for graph API endpoints."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestGraphModels:
    """Tests for graph request/response models."""

    def test_entity_response_model(self) -> None:
        """Test EntityResponse model."""
        from api.endpoints.graph import EntityResponse

        entity = EntityResponse(
            id="entity-123",
            canonical_name="Apple Inc.",
            type="Organization",
            aliases=["Apple", "AAPL"],
            description="Technology company",
            updated_at="2024-01-01T00:00:00",
        )
        assert entity.id == "entity-123"
        assert entity.canonical_name == "Apple Inc."
        assert entity.type == "Organization"
        assert len(entity.aliases) == 2

    def test_entity_relationship_model(self) -> None:
        """Test EntityRelationship model."""
        from api.endpoints.graph import EntityRelationship

        rel = EntityRelationship(
            target="Cupertino",
            relation_type="LOCATED_IN",
            source_article_id=None,
            created_at=None,
        )
        assert rel.target == "Cupertino"
        assert rel.relation_type == "LOCATED_IN"

    def test_entity_with_relations_model(self) -> None:
        """Test EntityWithRelations model."""
        from api.endpoints.graph import EntityRelationship, EntityResponse, EntityWithRelations

        entity = EntityWithRelations(
            entity=EntityResponse(
                id="e1",
                canonical_name="Apple",
                type="Organization",
                aliases=None,
                description=None,
                updated_at=None,
            ),
            relationships=[
                EntityRelationship(
                    target="Cupertino",
                    relation_type="LOCATED_IN",
                    source_article_id=None,
                    created_at=None,
                ),
            ],
            related_entities=[],
            mentioned_in_articles=[],
        )
        assert entity.entity.canonical_name == "Apple"
        assert len(entity.relationships) == 1

    def test_article_graph_node_model(self) -> None:
        """Test ArticleGraphNode model."""
        from api.endpoints.graph import ArticleGraphNode

        node = ArticleGraphNode(
            id="article-123",
            title="Test Article",
            category="Tech",
            publish_time="2024-01-01T00:00:00",
            score=0.95,
        )
        assert node.id == "article-123"
        assert node.title == "Test Article"

    def test_article_graph_relationship_model(self) -> None:
        """Test ArticleGraphRelationship model."""
        from api.endpoints.graph import ArticleGraphRelationship

        rel = ArticleGraphRelationship(
            source_id="Apple",
            target_id="Cupertino",
            relation_type="LOCATED_IN",
            properties={"source_article_id": "a1"},
        )
        assert rel.source_id == "Apple"
        assert rel.target_id == "Cupertino"

    def test_relation_type_summary_model(self) -> None:
        """Test RelationTypeSummary model."""
        from api.endpoints.graph import RelationTypeSummary

        summary = RelationTypeSummary(
            relation_type="LOCATED_IN",
            target_count=150,
            primary_direction="outbound",
        )
        assert summary.relation_type == "LOCATED_IN"
        assert summary.target_count == 150

    def test_related_entity_result_model(self) -> None:
        """Test RelatedEntityResult model."""
        from api.endpoints.graph import RelatedEntityResult

        result = RelatedEntityResult(
            relation_type="WORKS_FOR",
            direction="outbound",
            target_name="Apple",
            target_type="Organization",
            target_description="Tech company",
            weight=0.9,
        )
        assert result.relation_type == "WORKS_FOR"
        assert result.target_name == "Apple"
        assert result.weight == 0.9

    def test_relation_type_info_model(self) -> None:
        """Test RelationTypeInfo model."""
        from api.endpoints.graph import RelationTypeInfo

        info = RelationTypeInfo(
            name="位于",
            name_en="LOCATED_IN",
            category="SPATIAL",
            is_symmetric=False,
            description="Entity located in a place",
            alias_count=3,
        )
        assert info.name == "位于"
        assert info.name_en == "LOCATED_IN"
        assert info.alias_count == 3


class TestGraphRouter:
    """Tests for graph router configuration."""

    def test_router_prefix(self) -> None:
        """Test router has correct prefix."""
        from api.endpoints.graph import router

        assert router.prefix == "/graph"

    def test_router_tags(self) -> None:
        """Test router has correct tags."""
        from api.endpoints.graph import router

        assert "graph" in router.tags


class TestGraphEndpoints:
    """Tests for graph endpoint functions."""

    @pytest.mark.asyncio
    async def test_get_entity_success(self) -> None:
        """Test GET /graph/entities/{name} returns entity."""
        from api.endpoints.graph import get_entity

        mock_session = AsyncMock()

        # Mock entity query
        entity_result = MagicMock()
        entity_result.single = AsyncMock(
            return_value={
                "id": "entity-123",
                "canonical_name": "Apple",
                "type": "Organization",
                "aliases": ["AAPL"],
                "description": "Tech company",
                "updated_at": MagicMock(isoformat=lambda: "2024-01-01T00:00:00"),
            }
        )

        # Mock relationships query
        rel_result = MagicMock()
        rel_result.__aiter__ = lambda self: self
        rel_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        # Mock related entities query
        related_result = MagicMock()
        related_result.__aiter__ = lambda self: self
        related_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        # Mock articles query
        articles_result = MagicMock()
        articles_result.__aiter__ = lambda self: self
        articles_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        mock_session.run = AsyncMock(
            side_effect=[entity_result, rel_result, related_result, articles_result]
        )

        mock_neo4j = MagicMock()
        mock_neo4j.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_neo4j.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_entity(name="Apple", limit=10, _="test-key", neo4j=mock_neo4j)

        assert result.data.entity.canonical_name == "Apple"
        assert result.data.entity.type == "Organization"

    @pytest.mark.asyncio
    async def test_get_entity_not_found(self) -> None:
        """Test GET /graph/entities/{name} handles not found."""
        from api.endpoints.graph import get_entity

        mock_session = AsyncMock()

        entity_result = MagicMock()
        entity_result.single = AsyncMock(return_value=None)

        mock_session.run = AsyncMock(return_value=entity_result)

        mock_neo4j = MagicMock()
        mock_neo4j.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_neo4j.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_entity(name="NonExistent", limit=10, _="test-key", neo4j=mock_neo4j)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_article_graph_success(self) -> None:
        """Test GET /graph/articles/{id}/graph returns graph."""
        from api.endpoints.graph import get_article_graph

        mock_session = AsyncMock()

        # Mock article query
        article_result = MagicMock()
        article_result.single = AsyncMock(
            return_value={
                "id": "article-123",
                "title": "Test Article",
                "category": "Tech",
                "publish_time": MagicMock(isoformat=lambda: "2024-01-01T00:00:00"),
                "score": 0.95,
            }
        )

        # Mock entities query
        entities_result = MagicMock()
        entities_result.__aiter__ = lambda self: self
        entities_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        # Mock relationships query
        rels_result = MagicMock()
        rels_result.__aiter__ = lambda self: self
        rels_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        # Mock related articles query
        related_result = MagicMock()
        related_result.__aiter__ = lambda self: self
        related_result.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        mock_session.run = AsyncMock(
            side_effect=[article_result, entities_result, rels_result, related_result]
        )

        mock_neo4j = MagicMock()
        mock_neo4j.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_neo4j.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_article_graph(article_id="article-123", _="test-key", neo4j=mock_neo4j)

        assert result.data.article.title == "Test Article"

    @pytest.mark.asyncio
    async def test_get_entity_relations_success(self) -> None:
        """Test GET /graph/relations returns relation types."""
        from api.endpoints.graph import get_entity_relations

        mock_neo4j = AsyncMock()

        with patch("api.endpoints.graph.Neo4jEntityRepo") as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.get_relation_types = AsyncMock(
                return_value=[
                    {"relation_type": "LOCATED_IN", "target_count": 10, "primary_direction": "out"},
                ]
            )
            mock_repo_class.return_value = mock_repo

            result = await get_entity_relations(
                entity="Apple",
                entity_type="Organization",
                _="test-key",
                neo4j=mock_neo4j,
            )

        assert len(result.data) == 1
        assert result.data[0].relation_type == "LOCATED_IN"

    @pytest.mark.asyncio
    async def test_search_relations_success(self) -> None:
        """Test GET /graph/relations/search returns matching relations."""
        from api.endpoints.graph import search_relations

        mock_neo4j = AsyncMock()

        with patch("api.endpoints.graph.Neo4jEntityRepo") as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.find_by_relation_types = AsyncMock(
                return_value=[
                    {
                        "relation_type": "LOCATED_IN",
                        "direction": "out",
                        "target_name": "Cupertino",
                        "target_type": "Location",
                        "target_description": "City in California",
                        "weight": 0.9,
                    },
                ]
            )
            mock_repo_class.return_value = mock_repo

            result = await search_relations(
                entity="Apple",
                entity_type="Organization",
                relation_types=None,
                limit=50,
                _="test-key",
                neo4j=mock_neo4j,
            )

        assert len(result.data) == 1
        assert result.data[0].target_name == "Cupertino"

    @pytest.mark.asyncio
    async def test_list_relation_types_success(self) -> None:
        """Test GET /graph/relation-types returns types."""
        from unittest.mock import AsyncMock

        from api.endpoints.graph import list_relation_types, set_postgres_pool

        # Set up mock pool
        mock_pool = MagicMock()
        mock_session = AsyncMock()

        # Create a simple row object with real string attributes
        class MockRow:
            name = "位于"
            name_en = "LOCATED_IN"
            category = "SPATIAL"
            is_symmetric = False
            description = "Located in"
            alias_count = 2

        # Mock result that iterates over rows
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([MockRow()])
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Create async context manager for session_context
        async_context = MagicMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.session_context = MagicMock(return_value=async_context)

        set_postgres_pool(mock_pool)

        result = await list_relation_types(_="test-key")

        assert len(result.data) == 1
        assert result.data[0].name == "位于"


class TestGraphEndpointsRoutes:
    """Tests for graph endpoint routes."""

    def test_router_has_entity_route(self) -> None:
        """Test router has entity endpoint."""
        from api.endpoints.graph import router

        routes = [route.path for route in router.routes]
        assert "/graph/entities/{name}" in routes

    def test_router_has_article_graph_route(self) -> None:
        """Test router has article graph endpoint."""
        from api.endpoints.graph import router

        routes = [route.path for route in router.routes]
        assert "/graph/articles/{article_id}/graph" in routes

    def test_router_has_relations_route(self) -> None:
        """Test router has relations endpoint."""
        from api.endpoints.graph import router

        routes = [route.path for route in router.routes]
        assert "/graph/relations" in routes

    def test_router_has_relations_search_route(self) -> None:
        """Test router has relations search endpoint."""
        from api.endpoints.graph import router

        routes = [route.path for route in router.routes]
        assert "/graph/relations/search" in routes

    def test_router_has_relation_types_route(self) -> None:
        """Test router has relation types endpoint."""
        from api.endpoints.graph import router

        routes = [route.path for route in router.routes]
        assert "/graph/relation-types" in routes
