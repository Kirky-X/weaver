# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for Neo4jArticleRepo."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.neo4j.article_repo import Neo4jArticleRepo


class TestNeo4jArticleRepoInit:
    """Tests for Neo4jArticleRepo initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        repo = Neo4jArticleRepo(mock_pool)
        assert repo._pool is mock_pool


class TestCreateArticle:
    """Tests for create_article method."""

    @pytest.mark.asyncio
    async def test_create_article_success(self):
        """Test successful article creation."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"neo4j_id": "neo4j-123"}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.create_article(
            pg_id="pg-uuid-123",
            title="Test Article",
            category="tech",
            publish_time=datetime.now(),
            score=0.85,
        )

        assert result == "neo4j-123"
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_article_without_score(self):
        """Test article creation without score."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"neo4j_id": "neo4j-456"}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.create_article(
            pg_id="pg-uuid-456",
            title="Test Article",
            category="finance",
            publish_time=None,
        )

        assert result == "neo4j-456"

    @pytest.mark.asyncio
    async def test_create_article_failure(self):
        """Test article creation failure."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        with pytest.raises(RuntimeError, match="Failed to create article node"):
            await repo.create_article(
                pg_id="pg-uuid-fail",
                title="Fail Article",
                category="tech",
                publish_time=None,
            )


class TestFindArticleByPgId:
    """Tests for find_article_by_pg_id method."""

    @pytest.mark.asyncio
    async def test_find_article_found(self):
        """Test finding an existing article."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo4j-123",
                    "pg_id": "pg-uuid-123",
                    "title": "Found Article",
                    "category": "tech",
                    "publish_time": None,
                    "score": 0.9,
                    "created_at": None,
                }
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_pg_id("pg-uuid-123")

        assert result is not None
        assert result["pg_id"] == "pg-uuid-123"
        assert result["title"] == "Found Article"

    @pytest.mark.asyncio
    async def test_find_article_not_found(self):
        """Test finding a nonexistent article."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_pg_id("nonexistent")

        assert result is None


class TestFindArticleByNeo4jId:
    """Tests for find_article_by_neo4j_id method."""

    @pytest.mark.asyncio
    async def test_find_by_neo4j_id_found(self):
        """Test finding article by Neo4j ID."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo4j-internal-123",
                    "pg_id": "pg-uuid-123",
                    "title": "Test",
                    "category": "tech",
                    "publish_time": None,
                    "score": None,
                    "created_at": None,
                }
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_neo4j_id("neo4j-internal-123")

        assert result is not None
        assert result["neo4j_id"] == "neo4j-internal-123"

    @pytest.mark.asyncio
    async def test_find_by_neo4j_id_not_found(self):
        """Test finding article by nonexistent Neo4j ID."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_neo4j_id("nonexistent")

        assert result is None


class TestCreateFollowedByRelation:
    """Tests for create_followed_by_relation method."""

    @pytest.mark.asyncio
    async def test_create_relation_basic(self):
        """Test creating basic FOLLOWED_BY relation."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        await repo.create_followed_by_relation(
            from_pg_id="article-1",
            to_pg_id="article-2",
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_relation_with_time_gap(self):
        """Test creating relation with time gap."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        await repo.create_followed_by_relation(
            from_pg_id="article-1",
            to_pg_id="article-2",
            time_gap_hours=24.5,
        )

        # Verify query was called with time_gap_hours
        call_args = mock_pool.execute_query.call_args
        params = call_args[0][1]
        assert "time_gap_hours" in params
        assert params["time_gap_hours"] == 24.5


class TestGetFollowedArticles:
    """Tests for get_followed_articles method."""

    @pytest.mark.asyncio
    async def test_get_outgoing_followed(self):
        """Test getting outgoing followed articles."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo-1",
                    "pg_id": "pg-1",
                    "title": "Article 1",
                    "category": "tech",
                    "publish_time": None,
                },
                {
                    "neo4j_id": "neo-2",
                    "pg_id": "pg-2",
                    "title": "Article 2",
                    "category": "tech",
                    "publish_time": None,
                },
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_followed_articles(
            pg_id="source-article",
            direction="outgoing",
            limit=10,
        )

        assert len(result) == 2
        assert result[0]["pg_id"] == "pg-1"

    @pytest.mark.asyncio
    async def test_get_incoming_followed(self):
        """Test getting incoming (predecessor) articles."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo-3",
                    "pg_id": "pg-3",
                    "title": "Predecessor",
                    "category": "finance",
                    "publish_time": None,
                },
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_followed_articles(
            pg_id="source-article",
            direction="incoming",
            limit=5,
        )

        assert len(result) == 1
        assert result[0]["pg_id"] == "pg-3"

    @pytest.mark.asyncio
    async def test_get_followed_empty(self):
        """Test getting followed articles when none exist."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_followed_articles(
            pg_id="isolated-article",
            direction="outgoing",
        )

        assert result == []


class TestDeleteArticle:
    """Tests for delete_article method."""

    @pytest.mark.asyncio
    async def test_delete_article_success(self):
        """Test successful article deletion."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.delete_article("pg-to-delete")

        # delete_article always returns True after executing query
        assert result is True


class TestDeleteOldArticles:
    """Tests for delete_old_articles method."""

    @pytest.mark.asyncio
    async def test_delete_old_articles(self):
        """Test deleting old articles."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.delete_old_articles(days=90)

        mock_pool.execute_query.assert_called_once()


class TestGetArticleEntities:
    """Tests for get_article_entities method."""

    @pytest.mark.asyncio
    async def test_get_article_entities_found(self):
        """Test getting entities for an article."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "e1",
                    "entity_id": "ent-1",
                    "canonical_name": "Entity One",
                    "entity_type": "PERSON",
                    "role": "subject",
                },
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_article_entities("pg-article")

        assert len(result) == 1
        assert result[0]["canonical_name"] == "Entity One"

    @pytest.mark.asyncio
    async def test_get_article_entities_empty(self):
        """Test getting entities when none exist."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_article_entities("pg-article")

        assert result == []


class TestUpdateArticleScore:
    """Tests for update_article_score method."""

    @pytest.mark.asyncio
    async def test_update_score(self):
        """Test updating article score."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        await repo.update_article_score("pg-id", 0.95)

        mock_pool.execute_query.assert_called_once()


class TestDeleteOrphanArticles:
    """Tests for delete_orphan_articles method."""

    @pytest.mark.asyncio
    async def test_delete_orphans_with_valid_ids(self):
        """Test deleting orphans with valid ID list."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"orphan_count": 5}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.delete_orphan_articles(["id1", "id2", "id3"])

        assert result == 5

    @pytest.mark.asyncio
    async def test_delete_orphans_empty_list(self):
        """Test deleting all articles when no valid IDs provided."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 10}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.delete_orphan_articles([])

        assert result == 10


class TestListAllArticlePgIds:
    """Tests for list_all_article_pg_ids method."""

    @pytest.mark.asyncio
    async def test_list_all_pg_ids(self):
        """Test listing all article pg_ids."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"pg_id": "id-1"},
                {"pg_id": "id-2"},
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.list_all_article_pg_ids()

        assert len(result) == 2
        assert "id-1" in result

    @pytest.mark.asyncio
    async def test_list_all_pg_ids_empty(self):
        """Test listing pg_ids when no articles exist."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.list_all_article_pg_ids()

        assert result == []


class TestDeleteArticlesWithoutMentions:
    """Tests for delete_articles_without_mentions method."""

    @pytest.mark.asyncio
    async def test_delete_without_mentions(self):
        """Test deleting orphan articles without mentions."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.delete_articles_without_mentions()

        mock_pool.execute_query.assert_called_once()


class TestCountArticlesWithoutMentions:
    """Tests for count_articles_without_mentions method."""

    @pytest.mark.asyncio
    async def test_count_without_mentions(self):
        """Test counting orphan articles."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"orphan_count": 7}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.count_articles_without_mentions()

        assert result == 7

    @pytest.mark.asyncio
    async def test_count_without_mentions_zero(self):
        """Test counting orphan articles when none exist."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"orphan_count": 0}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.count_articles_without_mentions()

        assert result == 0
