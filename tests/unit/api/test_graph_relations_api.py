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

        mock_graph_repo = MagicMock()
        mock_graph_repo.get_entity = AsyncMock(
            return_value={
                "id": "entity-123",
                "canonical_name": "Apple",
                "type": "Organization",
                "aliases": ["AAPL"],
                "description": "Tech company",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
        mock_graph_repo.get_entity_relations = AsyncMock(return_value=[])
        mock_graph_repo.get_related_entities = AsyncMock(return_value=[])
        mock_graph_repo.get_entity_articles = AsyncMock(return_value=[])

        result = await get_entity(name="Apple", limit=10, _="test-key", graph_repo=mock_graph_repo)

        assert result.data.entity.canonical_name == "Apple"
        assert result.data.entity.type == "Organization"

    @pytest.mark.asyncio
    async def test_get_entity_not_found(self) -> None:
        """Test GET /graph/entities/{name} handles not found."""
        from api.endpoints.graph import get_entity

        mock_graph_repo = MagicMock()
        mock_graph_repo.get_entity = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_entity(name="NonExistent", limit=10, _="test-key", graph_repo=mock_graph_repo)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_article_graph_success(self) -> None:
        """Test GET /graph/articles/{id}/graph returns graph."""
        from api.endpoints.graph import get_article_graph

        mock_graph_repo = MagicMock()
        mock_graph_repo.get_article = AsyncMock(
            return_value={
                "id": "article-123",
                "title": "Test Article",
                "category": "Tech",
                "publish_time": "2024-01-01T00:00:00",
                "score": 0.95,
            }
        )
        mock_graph_repo.get_article_entities = AsyncMock(return_value=[])
        mock_graph_repo.get_article_relationships = AsyncMock(return_value=[])
        mock_graph_repo.get_related_articles = AsyncMock(return_value=[])

        result = await get_article_graph(
            article_id="article-123", _="test-key", graph_repo=mock_graph_repo
        )

        assert result.data.article.title == "Test Article"

    @pytest.mark.asyncio
    async def test_get_entity_relations_success(self) -> None:
        """Test GET /graph/relations returns relation types."""
        from api.endpoints.graph import get_entity_relations

        mock_graph_repo = MagicMock()
        mock_graph_repo.get_relation_types = AsyncMock(
            return_value=[
                {"relation_type": "LOCATED_IN", "target_count": 10, "primary_direction": "out"},
            ]
        )

        result = await get_entity_relations(
            entity="Apple",
            entity_type="Organization",
            _="test-key",
            graph_repo=mock_graph_repo,
        )

        assert len(result.data) == 1
        assert result.data[0].relation_type == "LOCATED_IN"

    @pytest.mark.asyncio
    async def test_search_relations_success(self) -> None:
        """Test GET /graph/relations/search returns matching relations."""
        from api.endpoints.graph import search_relations

        mock_graph_repo = MagicMock()
        mock_graph_repo.find_by_relation_types = AsyncMock(
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

        result = await search_relations(
            entity="Apple",
            entity_type="Organization",
            relation_types=None,
            limit=50,
            _="test-key",
            graph_repo=mock_graph_repo,
        )

        assert len(result.data) == 1
        assert result.data[0].target_name == "Cupertino"


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
