# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for delete_orphan_articles empty-list guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.storage.ladybug.article_repo import LadybugArticleRepo


@pytest.fixture
def mock_pool():
    return AsyncMock()


@pytest.fixture
def repo(mock_pool):
    return LadybugArticleRepo(pool=mock_pool)


class TestDeleteOrphanArticlesEmptyGuard:
    """empty valid_article_ids must NOT delete all Article nodes."""

    async def test_empty_list_returns_zero(self, repo, mock_pool):
        result = await repo.delete_orphan_articles([])
        assert result == 0
        # Must NOT execute any query
        mock_pool.execute_query.assert_not_called()

    async def test_empty_list_logs_spec_keyword(self, repo):
        """R-DATA-001: WARNING log must carry the spec-mandated keyword."""
        with patch("modules.storage.ladybug.article_repo.log") as mock_log:
            result = await repo.delete_orphan_articles([])

        assert result == 0
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.args[0] == "delete_orphan_articles_empty_list_guard"

    async def test_non_empty_list_executes_query(self, repo, mock_pool):
        mock_pool.execute_query.return_value = [{"deleted": 3}]
        result = await repo.delete_orphan_articles(["id1", "id2"])
        assert result == 3
        mock_pool.execute_query.assert_called_once()

    async def test_non_empty_result_zero(self, repo, mock_pool):
        mock_pool.execute_query.return_value = [{"deleted": 0}]
        result = await repo.delete_orphan_articles(["id1"])
        assert result == 0

    async def test_empty_result_returns_zero(self, repo, mock_pool):
        mock_pool.execute_query.return_value = []
        result = await repo.delete_orphan_articles(["id1"])
        assert result == 0
