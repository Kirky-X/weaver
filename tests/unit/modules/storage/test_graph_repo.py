# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.storage.graph_repo module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGraphRepositoryInit:
    """Test GraphRepository initialization."""

    def test_init(self):
        """Test initialization."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = MagicMock()
        mock_query_builder = MagicMock()

        repo = GraphRepository(mock_pool, mock_query_builder)

        assert repo._pool is mock_pool
        assert repo._query_builder is mock_query_builder

    def test_init_with_fallback(self):
        """Test initialization with fallback."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = MagicMock()
        mock_query_builder = MagicMock()
        mock_fallback_pool_factory = MagicMock()
        mock_fallback_query_builder = MagicMock()

        repo = GraphRepository(
            mock_pool,
            mock_query_builder,
            fallback_pool_factory=mock_fallback_pool_factory,
            fallback_query_builder=mock_fallback_query_builder,
        )

        assert repo._fallback_pool_factory is mock_fallback_pool_factory
        assert repo._fallback_query_builder is mock_fallback_query_builder

    def test_database_type_property(self):
        """Test database_type property."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = MagicMock()
        mock_query_builder = MagicMock()
        mock_query_builder.database_type = MagicMock(value="neo4j")

        repo = GraphRepository(mock_pool, mock_query_builder)

        assert repo.database_type == "neo4j"


class TestGraphRepositoryGetEntity:
    """Test get_entity method."""

    @pytest.fixture
    def repo(self):
        """Create GraphRepository with mock pool."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = AsyncMock()
        mock_query_builder = MagicMock()
        mock_query_builder.build_get_entity_query = MagicMock(return_value="QUERY")
        return GraphRepository(mock_pool, mock_query_builder)

    @pytest.mark.asyncio
    async def test_get_entity_found(self, repo):
        """Test get_entity finds entity."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "1",
                    "canonical_name": "Test Entity",
                    "type": "Person",
                    "aliases": ["alias1"],
                    "description": "A test entity",
                    "updated_at": None,
                }
            ]
        )

        entity = await repo.get_entity("Test Entity")

        assert entity is not None
        assert entity["canonical_name"] == "Test Entity"
        assert entity["type"] == "Person"

    @pytest.mark.asyncio
    async def test_get_entity_not_found(self, repo):
        """Test get_entity returns None when not found."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        entity = await repo.get_entity("NonExistent")

        assert entity is None


class TestGraphRepositoryGetEntityRelations:
    """Test get_entity_relations method."""

    @pytest.fixture
    def repo(self):
        """Create GraphRepository with mock pool."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = AsyncMock()
        mock_query_builder = MagicMock()
        mock_query_builder.build_get_entity_relations_query = MagicMock(return_value="QUERY")
        return GraphRepository(mock_pool, mock_query_builder)

    @pytest.mark.asyncio
    async def test_get_entity_relations(self, repo):
        """Test get_entity_relations returns relations."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "target": "Entity2",
                    "relation_type": "RELATED_TO",
                    "source_article_id": "article1",
                    "created_at": None,
                }
            ]
        )

        relations = await repo.get_entity_relations("Entity1")

        assert len(relations) == 1
        assert relations[0]["target"] == "Entity2"


class TestGraphRepositoryGetRelatedEntities:
    """Test get_related_entities method."""

    @pytest.fixture
    def repo(self):
        """Create GraphRepository with mock pool."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = AsyncMock()
        mock_query_builder = MagicMock()
        mock_query_builder.build_get_related_entities_query = MagicMock(return_value="QUERY")
        return GraphRepository(mock_pool, mock_query_builder)

    @pytest.mark.asyncio
    async def test_get_related_entities(self, repo):
        """Test get_related_entities returns entities."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "2",
                    "canonical_name": "Related Entity",
                    "type": "Person",
                    "aliases": None,
                    "description": None,
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        )

        entities = await repo.get_related_entities("Entity1")

        assert len(entities) == 1
        assert entities[0]["canonical_name"] == "Related Entity"


class TestGraphRepositoryGetArticle:
    """Test get_article method.

    After the Article node slim-down (design.md §D2), graph queries only
    return ``a.pg_id AS id``; business fields are batch-fetched from
    PostgreSQL via ``article_repo.fetch_titles_by_pg_ids``.
    """

    @pytest.fixture
    def repo(self):
        """Create GraphRepository with mock pool and mock article_repo."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = AsyncMock()
        mock_query_builder = MagicMock()
        mock_query_builder.build_get_article_graph_query = MagicMock(return_value="QUERY")
        mock_article_repo = MagicMock()
        mock_article_repo.fetch_titles_by_pg_ids = AsyncMock(
            return_value={
                "article1": {
                    "title": "Test Article",
                    "category": "news",
                    "publish_time": None,
                    "score": 0.95,
                }
            }
        )
        return GraphRepository(mock_pool, mock_query_builder, article_repo=mock_article_repo)

    @pytest.mark.asyncio
    async def test_get_article_found(self, repo):
        """Test get_article finds article and enriches from PG."""
        repo._pool.execute_query = AsyncMock(return_value=[{"id": "article1"}])

        article = await repo.get_article("article1")

        assert article is not None
        assert article["id"] == "article1"
        assert article["title"] == "Test Article"
        assert article["category"] == "news"
        assert article["score"] == 0.95

    @pytest.mark.asyncio
    async def test_get_article_not_found(self, repo):
        """Test get_article returns None when not found."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        article = await repo.get_article("nonexistent")

        assert article is None

    @pytest.mark.asyncio
    async def test_get_article_degraded_without_article_repo(self):
        """Degraded mode returns pg_id only when article_repo is None."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = AsyncMock()
        mock_query_builder = MagicMock()
        mock_query_builder.build_get_article_graph_query = MagicMock(return_value="QUERY")
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "orphan1"}])

        repo = GraphRepository(mock_pool, mock_query_builder)  # article_repo=None
        article = await repo.get_article("orphan1")

        assert article is not None
        assert article["id"] == "orphan1"
        assert article["title"] == ""
        assert article["category"] is None


class TestGraphRepositoryGetVisualizationNodes:
    """Test get_visualization_nodes method."""

    @pytest.fixture
    def repo(self):
        """Create GraphRepository with mock pool."""
        from modules.storage.graph_repo import GraphRepository

        mock_pool = AsyncMock()
        mock_query_builder = MagicMock()
        mock_query_builder.build_visualization_nodes_query = MagicMock(return_value="QUERY")
        return GraphRepository(mock_pool, mock_query_builder)

    @pytest.mark.asyncio
    async def test_get_visualization_nodes(self, repo):
        """Test get_visualization_nodes returns nodes."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "entity1",
                    "label": "Entity",
                    "type": "Person",
                    "description": None,
                    "degree": 5,
                }
            ]
        )

        nodes = await repo.get_visualization_nodes(limit=100)

        assert len(nodes) == 1
        assert nodes[0]["degree"] == 5
