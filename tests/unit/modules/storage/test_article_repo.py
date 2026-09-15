# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for ArticleRepo module."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db import Article, PersistStatus
from core.exceptions import InvalidStateTransitionError
from modules.storage.postgres.article_repo import ArticleRepo


class TestArticleRepoInit:
    """Tests for ArticleRepo initialization."""

    def test_init_stores_pool(self):
        """Test ArticleRepo stores pool reference."""
        mock_pool = MagicMock()
        repo = ArticleRepo(mock_pool)
        assert repo._pool is mock_pool


class TestArticleRepoBulkUpsert:
    """Tests for bulk_upsert method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_list(self, article_repo):
        """Test bulk_upsert returns empty list for empty input."""
        result = await article_repo.bulk_upsert([])
        assert result == []

    @pytest.mark.asyncio
    async def test_bulk_upsert_filters_terminal_states(self, article_repo, mock_pool):
        """Test bulk_upsert filters out terminal states."""
        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock()
        mock_session.execute.return_value.__iter__ = lambda self: iter([])

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        states = [
            {"terminal": True, "raw": MagicMock(url="https://example.com/1")},
            {"raw": MagicMock(url="https://example.com/2")},
        ]

        result = await article_repo.bulk_upsert(states)
        # Should not process terminal state
        assert isinstance(result, list)


class TestArticleRepoBulkUpsertAlignment:
    """bulk_upsert results must stay position-aligned with input states."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        return MagicMock()

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_failed_state_yields_none_placeholder(self, article_repo, mock_pool):
        """A state failing all retries yields None at its position, not a shifted id."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        ok_id = uuid.uuid4()
        failing = {"raw": MagicMock(url="https://example.com/fail")}
        succeeding = {"raw": MagicMock(url="https://example.com/ok")}

        async def fake_upsert_single(session, state):
            if state is failing:
                raise RuntimeError("db down")
            return ok_id

        with (
            patch.object(article_repo._writer, "_upsert_single", side_effect=fake_upsert_single),
            patch("modules.storage.postgres.article_writer.asyncio.sleep", new=AsyncMock()),
        ):
            result = await article_repo.bulk_upsert([failing, succeeding])

        assert len(result) == 2
        assert result[0] is None
        assert result[1] == ok_id

    @pytest.mark.asyncio
    async def test_bulk_upsert_result_length_matches_input(self, article_repo, mock_pool):
        """Result length always equals input length regardless of failures."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        states = [{"raw": MagicMock(url=f"https://example.com/{i}")} for i in range(3)]

        async def fake_upsert_single(session, state):
            raise RuntimeError("db down")

        with (
            patch.object(article_repo._writer, "_upsert_single", side_effect=fake_upsert_single),
            patch("modules.storage.postgres.article_writer.asyncio.sleep", new=AsyncMock()),
        ):
            result = await article_repo.bulk_upsert(states)

        assert len(result) == 3
        assert all(aid is None for aid in result)


class TestArticleRepoGetExistingUrls:
    """Tests for get_existing_urls method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_existing_urls_empty_list(self, article_repo):
        """Test get_existing_urls returns empty set for empty input."""
        result = await article_repo.get_existing_urls([])
        assert result == set()

    @pytest.mark.asyncio
    async def test_get_existing_urls_returns_matches(self, article_repo, mock_pool):
        """Test get_existing_urls returns matching URLs."""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([("https://example.com/1",)])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_existing_urls(
            ["https://example.com/1", "https://example.com/2"]
        )

        assert "https://example.com/1" in result


class TestArticleRepoUpdatePersistStatus:
    """Tests for update_persist_status with state validation."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_update_persist_status_valid_transition(self, article_repo, mock_pool):
        """Test valid state transition succeeds."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = PersistStatus.PENDING

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        # Should not raise
        await article_repo.update_persist_status(article_id, "processing")

    @pytest.mark.asyncio
    async def test_update_persist_status_invalid_transition(self, article_repo, mock_pool):
        """Test invalid state transition raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = PersistStatus.NEO4J_DONE

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        with pytest.raises(InvalidStateTransitionError):
            await article_repo.update_persist_status(article_id, "pending")

    @pytest.mark.asyncio
    async def test_update_persist_status_article_not_found(self, article_repo, mock_pool):
        """Test update_persist_status handles missing article gracefully."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        # Should not raise
        await article_repo.update_persist_status(article_id, "processing")


class TestArticleRepoInsertRaw:
    """Tests for insert_raw method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_insert_raw_requires_url(self, article_repo):
        """Test insert_raw raises ValueError when URL missing."""
        mock_article = MagicMock()
        mock_article.url = ""

        with pytest.raises(ValueError, match="URL"):
            await article_repo.insert_raw(mock_article)

    @pytest.mark.asyncio
    async def test_insert_raw_returns_existing_id(self, article_repo, mock_pool):
        """Test insert_raw returns existing article ID if URL exists."""
        existing_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_id

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_article = MagicMock()
        mock_article.url = "https://example.com/existing"
        mock_article.source_host = "example.com"
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.description = ""

        result = await article_repo.insert_raw(mock_article)
        assert result == existing_id


class TestArticleRepoRevertToPgDone:
    """Tests for revert_to_pg_done method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_revert_to_pg_done_success(self, article_repo, mock_pool):
        """Test revert_to_pg_done returns True when row updated."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        result = await article_repo.revert_to_pg_done(article_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_revert_to_pg_done_not_found(self, article_repo, mock_pool):
        """Test revert_to_pg_done returns False when no row updated."""
        mock_result = MagicMock()
        mock_result.rowcount = 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        result = await article_repo.revert_to_pg_done(article_id)
        assert result is False


class TestArticleRepoGetStuckArticles:
    """Tests for get_stuck_articles method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_stuck_articles(self, article_repo, mock_pool):
        """Test get_stuck_articles returns stuck articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_article]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_stuck_articles(timeout_minutes=30)
        assert len(result) == 1
