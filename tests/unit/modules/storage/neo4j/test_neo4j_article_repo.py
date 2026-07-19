# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for Neo4jArticleRepo.

After the Article node slim-down (design.md §D2), the graph Article node
stores only ``{pg_id, created_at}`` (Neo4j). Business fields
(title / category / publish_time / score) are no longer persisted on the
node — callers that need them must batch-fetch from PostgreSQL via
``ArticleRepository.fetch_titles_by_pg_ids``.
"""

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
    """Tests for create_article method (post-slim-down signature)."""

    @pytest.mark.asyncio
    async def test_create_article_accepts_only_article_id(self):
        """T028: create_article must accept only article_id (pg_id).

        After the slim-down, title / category / publish_time / score are
        no longer accepted. Verifies the Cypher only sets pg_id (and
        created_at via ON CREATE SET).
        """
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"neo4j_id": "neo4j-123"}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.create_article(article_id="pg-uuid-123")

        assert result == "neo4j-123"
        mock_pool.execute_query.assert_called_once()
        call_args = mock_pool.execute_query.call_args
        cypher = call_args[0][0]
        # Cypher must NOT set title/category/publish_time/score on the node.
        assert (
            "title" not in cypher.lower()
        ), f"create_article Cypher must not reference title: {cypher}"
        assert (
            "category" not in cypher.lower()
        ), f"create_article Cypher must not reference category: {cypher}"
        assert (
            "publish_time" not in cypher.lower()
        ), f"create_article Cypher must not reference publish_time: {cypher}"
        assert (
            "score" not in cypher.lower()
        ), f"create_article Cypher must not reference score: {cypher}"
        # Params must contain only pg_id.
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert set(params.keys()) == {
            "pg_id"
        }, f"create_article params must be only pg_id, got {set(params.keys())}"

    @pytest.mark.asyncio
    async def test_create_article_uses_merg_on_create_created_at(self):
        """T028: Cypher must MERGE on pg_id and set created_at on create."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"neo4j_id": "neo4j-456"}])

        repo = Neo4jArticleRepo(mock_pool)
        await repo.create_article(article_id="pg-uuid-456")

        call_args = mock_pool.execute_query.call_args
        cypher = call_args[0][0]
        assert (
            "MERGE (a:Article {pg_id: $pg_id})" in cypher
        ), f"create_article must MERGE on pg_id: {cypher}"
        assert "ON CREATE SET" in cypher, "create_article must set created_at on create"
        assert (
            "a.created_at = datetime()" in cypher
        ), "create_article must set created_at = datetime() on create"

    @pytest.mark.asyncio
    async def test_create_article_failure_raises_runtime_error(self):
        """T028: empty result raises RuntimeError."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        with pytest.raises(RuntimeError, match="Failed to create article node"):
            await repo.create_article(article_id="pg-uuid-fail")


class TestFindArticleByPgId:
    """Tests for find_article_by_id method (post-slim-down return shape)."""

    @pytest.mark.asyncio
    async def test_find_article_by_id_returns_only_slim_fields(self):
        """T028: find_article_by_id returns only {neo4j_id, pg_id, created_at}."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo4j-123",
                    "pg_id": "pg-uuid-123",
                    "created_at": "2026-07-20T00:00:00Z",
                }
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_id("pg-uuid-123")

        assert result is not None
        assert set(result.keys()) == {
            "neo4j_id",
            "pg_id",
            "created_at",
        }, f"find_article_by_id must return only slim fields, got {set(result.keys())}"
        assert result["pg_id"] == "pg-uuid-123"

    @pytest.mark.asyncio
    async def test_find_article_by_id_not_found(self):
        """T028: find_article_by_id returns None for nonexistent article."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_id("nonexistent")

        assert result is None


class TestFindArticleByNeo4jId:
    """Tests for find_article_by_graph_id method (post-slim-down return shape)."""

    @pytest.mark.asyncio
    async def test_find_by_graph_id_returns_only_slim_fields(self):
        """T028: find_article_by_graph_id returns only {neo4j_id, pg_id, created_at}."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo4j-internal-123",
                    "pg_id": "pg-uuid-123",
                    "created_at": "2026-07-20T00:00:00Z",
                }
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_graph_id("neo4j-internal-123")

        assert result is not None
        assert set(result.keys()) == {"neo4j_id", "pg_id", "created_at"}, (
            f"find_article_by_graph_id must return only slim fields, " f"got {set(result.keys())}"
        )
        assert result["neo4j_id"] == "neo4j-internal-123"

    @pytest.mark.asyncio
    async def test_find_by_graph_id_not_found(self):
        """T028: find_article_by_graph_id returns None for nonexistent ID."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.find_article_by_graph_id("nonexistent")

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
            from_article_id="article-1",
            to_article_id="article-2",
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_relation_with_time_gap(self):
        """Test creating relation with time gap."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        await repo.create_followed_by_relation(
            from_article_id="article-1",
            to_article_id="article-2",
            time_gap_hours=24.5,
        )

        call_args = mock_pool.execute_query.call_args
        params = call_args[0][1]
        assert "time_gap_hours" in params
        assert params["time_gap_hours"] == 24.5


class TestGetFollowedArticles:
    """Tests for get_followed_articles method (post-slim-down return shape)."""

    @pytest.mark.asyncio
    async def test_get_outgoing_followed_returns_slim_fields(self):
        """T028: get_followed_articles returns only {neo4j_id, pg_id, time_gap_hours}."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo-1",
                    "pg_id": "pg-1",
                    "time_gap_hours": 12.0,
                },
                {
                    "neo4j_id": "neo-2",
                    "pg_id": "pg-2",
                    "time_gap_hours": 24.0,
                },
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_followed_articles(
            article_id="source-article",
            direction="outgoing",
            limit=10,
        )

        assert len(result) == 2
        assert set(result[0].keys()) == {"neo4j_id", "pg_id", "time_gap_hours"}, (
            f"get_followed_articles must return only slim fields, " f"got {set(result[0].keys())}"
        )
        assert result[0]["pg_id"] == "pg-1"

    @pytest.mark.asyncio
    async def test_get_incoming_followed_returns_slim_fields(self):
        """T028: incoming direction also returns only slim fields."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo-3",
                    "pg_id": "pg-3",
                    "time_gap_hours": 6.0,
                },
            ]
        )

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_followed_articles(
            article_id="source-article",
            direction="incoming",
            limit=5,
        )

        assert len(result) == 1
        assert set(result[0].keys()) == {"neo4j_id", "pg_id", "time_gap_hours"}
        assert result[0]["pg_id"] == "pg-3"

    @pytest.mark.asyncio
    async def test_get_followed_empty(self):
        """Test getting followed articles when none exist."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.get_followed_articles(
            article_id="isolated-article",
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

        assert result is True


class TestDeleteOldArticles:
    """Tests for delete_old_articles method (post-slim-down signature)."""

    @pytest.mark.asyncio
    async def test_delete_old_articles_accepts_pg_ids_list(self):
        """T028: delete_old_articles accepts cutoff_pg_ids list (not days int).

        P2/P7 fix: Cypher now uses ``collect`` + ``size`` to compute the
        deleted count *before* DETACH DELETE, and returns it as ``deleted``
        (not ``total``). Implementation also chunks into batches of 500
        pg_ids per call to bound transaction size. With 3 input pg_ids
        only one chunk is issued, so execute_query is called once.
        """
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"deleted": 3}])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.delete_old_articles(
            cutoff_pg_ids=["pg-1", "pg-2", "pg-3"],
        )

        assert result == 3
        mock_pool.execute_query.assert_called_once()
        call_args = mock_pool.execute_query.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params == {
            "pg_ids": ["pg-1", "pg-2", "pg-3"]
        }, f"delete_old_articles must pass pg_ids param, got {params}"

    @pytest.mark.asyncio
    async def test_delete_old_articles_empty_list_returns_zero(self):
        """T028: empty cutoff_pg_ids short-circuits without DB call."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.delete_old_articles(cutoff_pg_ids=[])

        assert result == 0
        mock_pool.execute_query.assert_not_called()


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


class TestUpdateArticleScoreRemoved:
    """T028: update_article_score is removed (graph node has no score field)."""

    def test_update_article_score_attribute_does_not_exist(self):
        """Neo4jArticleRepo must NOT have update_article_score method.

        After the Article node slim-down, the graph node no longer stores
        ``score``, so per-article score updates have no meaning. The method
        is removed from the implementation and the Protocol.
        """
        assert not hasattr(Neo4jArticleRepo, "update_article_score"), (
            "Neo4jArticleRepo.update_article_score must be removed after "
            "the Article node slim-down (design.md §D2)."
        )


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
    """Tests for list_all_article_ids method."""

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
        result = await repo.list_all_article_ids()

        assert len(result) == 2
        assert "id-1" in result

    @pytest.mark.asyncio
    async def test_list_all_pg_ids_empty(self):
        """Test listing pg_ids when no articles exist."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = Neo4jArticleRepo(mock_pool)
        result = await repo.list_all_article_ids()

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
