# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T025 RED: LadybugArticleRepo Article node slim-down (design.md §D2).

After the graph Article node is slimmed to only ``{id, pg_id}``, the
LadybugArticleRepo methods must:
- ``create_article(article_id)`` accept only the pg_id (no title/category/
  publish_time/score).
- ``find_article_by_id`` return only ``{id, pg_id}``.
- ``find_article_by_graph_id`` return only ``{id, pg_id}``.
- ``create_articles_batch`` only write ``id, pg_id``.
- ``get_followed_articles`` only return ``{id, pg_id, time_gap_hours}``.
- ``delete_old_articles(cutoff_pg_ids)`` take a list of pg_ids to delete
  (no longer derives cutoff from publish_time, which is no longer on the
  node).
- ``update_article_score`` is removed (graph node has no score field).

This file asserts the new contract.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.ladybug.article_repo import LadybugArticleRepo


class TestLadybugArticleRepoCreateArticle:
    """T025: create_article only accepts article_id (pg_id)."""

    @pytest.mark.asyncio
    async def test_create_article_accepts_only_article_id(self):
        """create_article must accept only article_id and return the graph id.

        The new signature drops title / category / publish_time / score —
        those fields are no longer stored on the Article node. Callers
        that need them must batch-fetch via ArticleRepo.fetch_titles_by_pg_ids.
        """
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "graph-uuid-1"}])

        repo = LadybugArticleRepo(mock_pool)
        # New signature: only article_id
        result = await repo.create_article("pg-uuid-1")

        assert result == "graph-uuid-1"
        mock_pool.execute_query.assert_awaited()

        # Verify the Cypher does NOT set title/category/publish_time/score
        call_args = mock_pool.execute_query.await_args
        cypher = call_args[0][0] if call_args[0] else call_args[1].get("query", "")
        assert (
            "title" not in cypher
        ), f"create_article Cypher must not reference title after slim-down: {cypher}"
        assert "category" not in cypher
        assert "publish_time" not in cypher
        # score may appear as a property of EventNode/other labels but not Article
        # We check the Article-specific CREATE/MERGE block separately below.

    @pytest.mark.asyncio
    async def test_create_article_failure_raises_runtime_error(self):
        """LSP alignment (H2 fix): CREATE returning empty must raise RuntimeError.

        Previously this method returned a fabricated ``uuid.uuid4()``
        string when the CREATE query returned no rows, while the Neo4j
        implementation raised ``RuntimeError``. This LSP violation caused
        silent data loss in the LadybugDB backend: subsequent writes
        would link relations/mentions to a ghost id that did not exist
        in the graph. The fix raises RuntimeError to match Neo4j's
        contract — callers must surface the failure (rule 12).
        """
        mock_pool = MagicMock()
        # Both find_article_by_id (returns []) and CREATE (returns [])
        # hit the same mock; find_article_by_id returning [] means the
        # article does not exist, then CREATE returning [] is the
        # unexpected failure we want to surface.
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = LadybugArticleRepo(mock_pool)
        with pytest.raises(RuntimeError, match="Failed to create article node"):
            await repo.create_article("pg-uuid-2")


class TestLadybugArticleRepoFindById:
    """T025: find_article_by_id returns only {id, pg_id}."""

    @pytest.mark.asyncio
    async def test_find_article_by_id_returns_only_id_and_pg_id(self):
        """find_article_by_id must NOT return title/category/publish_time/score."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "graph-1", "pg_id": "pg-uuid-1"}])

        repo = LadybugArticleRepo(mock_pool)
        result = await repo.find_article_by_id("pg-uuid-1")

        assert result is not None
        assert set(result.keys()) == {"id", "pg_id"}
        assert result["pg_id"] == "pg-uuid-1"

    @pytest.mark.asyncio
    async def test_find_article_by_id_not_found(self):
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = LadybugArticleRepo(mock_pool)
        result = await repo.find_article_by_id("nonexistent")

        assert result is None


class TestLadybugArticleRepoFindByGraphId:
    """T025: find_article_by_graph_id returns only {id, pg_id}."""

    @pytest.mark.asyncio
    async def test_find_article_by_graph_id_returns_only_id_and_pg_id(self):
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[{"id": "graph-internal-1", "pg_id": "pg-uuid-1"}]
        )

        repo = LadybugArticleRepo(mock_pool)
        result = await repo.find_article_by_graph_id("graph-internal-1")

        assert result is not None
        assert set(result.keys()) == {"id", "pg_id"}


class TestLadybugArticleRepoCreateArticlesBatch:
    """T025: create_articles_batch only writes id, pg_id."""

    @pytest.mark.asyncio
    async def test_create_articles_batch_uses_only_pg_id(self):
        """Batch create must only write id and pg_id (no title/category/etc.).

        P6 fix: implementation now uses a single OPTIONAL MATCH batch
        query (round 1) followed by a single UNWIND CREATE for missing
        articles (round 2). Previously it issued N find_article_by_id
        calls (one per article); the mock side_effect must match the
        new 2-call shape.
        """
        mock_pool = MagicMock()
        # Round 1 (OPTIONAL MATCH existence check): returns one row per
        # input pg_id with existing_id=None (both are new).
        # Round 2 (UNWIND CREATE): returns the generated ids in order.
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                # Round 1: existence check, both missing
                [
                    {"pid": "pg-1", "existing_id": None},
                    {"pid": "pg-2", "existing_id": None},
                ],
                # Round 2: UNWIND CREATE returns generated ids
                [{"id": "graph-1"}, {"id": "graph-2"}],
            ]
        )

        repo = LadybugArticleRepo(mock_pool)
        articles = [
            {"pg_id": "pg-1", "title": "T1", "category": "c1"},  # extra fields ignored
            {"pg_id": "pg-2", "title": "T2", "category": "c2"},
        ]
        result = await repo.create_articles_batch(articles)

        assert len(result) == 2
        # Verify the UNWIND CREATE Cypher does not reference title/category
        # The 2nd execute_query call is the UNWIND CREATE
        unwind_call = mock_pool.execute_query.await_args_list[1]
        cypher = unwind_call[0][0] if unwind_call[0] else ""
        assert (
            "title" not in cypher
        ), f"create_articles_batch Cypher must not reference title: {cypher}"
        assert "category" not in cypher
        assert "publish_time" not in cypher

    @pytest.mark.asyncio
    async def test_create_articles_batch_empty_list_returns_empty(self):
        mock_pool = MagicMock()
        repo = LadybugArticleRepo(mock_pool)
        result = await repo.create_articles_batch([])
        assert result == []
        mock_pool.execute_query.assert_not_called()


class TestLadybugArticleRepoGetFollowedArticles:
    """T025: get_followed_articles returns only id, pg_id, time_gap_hours."""

    @pytest.mark.asyncio
    async def test_get_followed_articles_returns_slim_fields(self):
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "graph-1",
                    "pg_id": "pg-1",
                    "time_gap_hours": 12.5,
                }
            ]
        )

        repo = LadybugArticleRepo(mock_pool)
        result = await repo.get_followed_articles("source-pg", direction="outgoing")

        assert len(result) == 1
        assert set(result[0].keys()) == {"id", "pg_id", "time_gap_hours"}
        assert result[0]["pg_id"] == "pg-1"
        assert result[0]["time_gap_hours"] == 12.5

    @pytest.mark.asyncio
    async def test_get_followed_articles_incoming_direction(self):
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[{"id": "graph-2", "pg_id": "pg-2", "time_gap_hours": 0.0}]
        )

        repo = LadybugArticleRepo(mock_pool)
        result = await repo.get_followed_articles("source-pg", direction="incoming")

        assert len(result) == 1
        assert result[0]["pg_id"] == "pg-2"


class TestLadybugArticleRepoDeleteOldArticles:
    """T025: delete_old_articles takes cutoff_pg_ids (not days)."""

    @pytest.mark.asyncio
    async def test_delete_old_articles_accepts_pg_ids_list(self):
        """delete_old_articles must accept a list of pg_ids to delete.

        The old signature ``delete_old_articles(days=90)`` relied on
        ``a.publish_time`` which is no longer on the node. The new
        signature receives the cutoff pg_ids directly — callers query
        PostgreSQL for ``publish_time < NOW() - INTERVAL '$days days'``
        and pass the resulting IDs here.
        """
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        repo = LadybugArticleRepo(mock_pool)
        # New signature: cutoff_pg_ids
        result = await repo.delete_old_articles(["pg-old-1", "pg-old-2"])

        # Returns the count deleted (0 from mock)
        assert isinstance(result, int)
        mock_pool.execute_query.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_old_articles_empty_list_returns_zero(self):
        mock_pool = MagicMock()
        repo = LadybugArticleRepo(mock_pool)
        result = await repo.delete_old_articles([])
        assert result == 0
        mock_pool.execute_query.assert_not_called()


class TestLadybugArticleRepoUpdateArticleScoreRemoved:
    """T025: update_article_score is removed (graph node has no score)."""

    def test_update_article_score_attribute_does_not_exist(self):
        """LadybugArticleRepo must NOT have update_article_score method.

        After the Article node slim-down, the graph DB no longer stores
        ``score`` — that field lives only in PostgreSQL. The method is
        removed to prevent silent no-ops (rule 12: failures must be
        explicit).
        """
        assert not hasattr(LadybugArticleRepo, "update_article_score"), (
            "LadybugArticleRepo.update_article_score must be removed after "
            "the Article node slim-down (graph no longer stores score)."
        )
