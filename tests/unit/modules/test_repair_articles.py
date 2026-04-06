# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for repair-articles command."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMainFunction:
    """Tests for the main() function."""

    @patch("sys.exit")
    def test_main_default_args(self, mock_exit):
        """Test main() with default arguments."""
        with patch(
            "modules.management.commands.repair_articles.argparse.ArgumentParser.parse_args"
        ) as mock_parse:
            with patch("modules.management.commands.repair_articles.asyncio.run") as mock_run:
                mock_parse.return_value = argparse.Namespace(limit=10, force=False, dry_run=False)
                from modules.management.commands.repair_articles import main

                main()
                mock_exit.assert_called_with(0)

    @patch("sys.exit")
    def test_main_keyboard_interrupt(self, mock_exit):
        """Test main() handles KeyboardInterrupt."""
        with patch(
            "modules.management.commands.repair_articles.argparse.ArgumentParser.parse_args"
        ) as mock_parse:
            with patch("modules.management.commands.repair_articles.asyncio.run") as mock_run:
                mock_parse.return_value = argparse.Namespace(limit=10, force=False, dry_run=False)
                mock_run.side_effect = KeyboardInterrupt()
                from modules.management.commands.repair_articles import main

                main()
                mock_exit.assert_called_with(130)

    @patch("sys.exit")
    def test_main_exception(self, mock_exit):
        """Test main() handles general exceptions."""
        with patch(
            "modules.management.commands.repair_articles.argparse.ArgumentParser.parse_args"
        ) as mock_parse:
            with patch("modules.management.commands.repair_articles.asyncio.run") as mock_run:
                mock_parse.return_value = argparse.Namespace(limit=10, force=False, dry_run=False)
                mock_run.side_effect = RuntimeError("Test error")
                from modules.management.commands.repair_articles import main

                main()
                mock_exit.assert_called_with(1)


class TestRepairArticlesDryRun:
    """Tests for repair_articles in dry_run mode."""

    @pytest.mark.asyncio
    async def test_dry_run_no_articles(self):
        """Test dry_run with no incomplete articles."""
        with patch(
            "modules.management.commands.repair_articles._init_minimal_container"
        ) as mock_init:
            with patch(
                "modules.management.commands.repair_articles._shutdown_minimal_container"
            ) as mock_shutdown:
                mock_init.return_value = (
                    AsyncMock(),
                    AsyncMock(),
                    AsyncMock(),
                    MagicMock(),
                    MagicMock(),
                )

                # Mock ArticleRepo where it's imported (in repair_articles function)
                with patch("modules.storage.postgres.article_repo.ArticleRepo") as mock_repo_class:
                    mock_repo = AsyncMock()
                    mock_repo.get_incomplete_articles = AsyncMock(return_value=[])
                    mock_repo_class.return_value = mock_repo

                    from modules.management.commands.repair_articles import repair_articles

                    result = await repair_articles(limit=10, force=False, dry_run=True)
                    assert result == 0

    @pytest.mark.asyncio
    async def test_dry_run_with_articles(self):
        """Test dry_run with incomplete articles."""
        mock_article = MagicMock()
        mock_article.id = "test-id"
        mock_article.title = "Test Title"
        mock_article.body = "Test Body"
        mock_article.source_url = "https://example.com"
        mock_article.source_host = "example.com"
        mock_article.is_news = True
        mock_article.publish_time = None
        mock_article.category = None
        mock_article.score = None
        mock_article.credibility_score = None
        mock_article.summary = None
        mock_article.quality_score = None

        with patch(
            "modules.management.commands.repair_articles._init_minimal_container"
        ) as mock_init:
            with patch(
                "modules.management.commands.repair_articles._shutdown_minimal_container"
            ) as mock_shutdown:
                mock_init.return_value = (
                    AsyncMock(),
                    AsyncMock(),
                    AsyncMock(),
                    MagicMock(),
                    MagicMock(),
                )

                with patch("modules.storage.postgres.article_repo.ArticleRepo") as mock_repo_class:
                    mock_repo = AsyncMock()
                    mock_repo.get_incomplete_articles = AsyncMock(return_value=[mock_article])
                    mock_repo_class.return_value = mock_repo

                    from modules.management.commands.repair_articles import repair_articles

                    result = await repair_articles(limit=10, force=False, dry_run=True)
                    assert result == 1


class TestRepairArticlesForceMode:
    """Tests for repair_articles with force mode."""

    @pytest.mark.asyncio
    async def test_force_mode_multiple_batches(self):
        """Test force mode processes multiple batches."""
        mock_article = MagicMock()
        mock_article.id = "test-id"
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.source_url = "https://example.com"
        mock_article.source_host = "example.com"
        mock_article.is_news = True
        mock_article.publish_time = None
        mock_article.category = None
        mock_article.score = None
        mock_article.credibility_score = None
        mock_article.summary = None
        mock_article.quality_score = None

        with patch(
            "modules.management.commands.repair_articles._init_minimal_container"
        ) as mock_init:
            with patch(
                "modules.management.commands.repair_articles._shutdown_minimal_container"
            ) as mock_shutdown:
                mock_init.return_value = (
                    AsyncMock(),
                    AsyncMock(),
                    AsyncMock(),
                    MagicMock(),
                    MagicMock(),
                )

                with patch("modules.storage.postgres.article_repo.ArticleRepo") as mock_repo_class:
                    mock_repo = AsyncMock()
                    # First call returns article, second returns empty
                    mock_repo.get_incomplete_articles = AsyncMock(side_effect=[[mock_article], []])
                    mock_repo_class.return_value = mock_repo

                    from modules.management.commands.repair_articles import repair_articles

                    result = await repair_articles(limit=10, force=True, dry_run=True)
                    assert result == 1


class TestRepairArticlesLimit:
    """Tests for limit parameter."""

    @pytest.mark.asyncio
    async def test_limit_passed_to_repo(self):
        """Test that limit is passed to get_incomplete_articles."""
        with patch(
            "modules.management.commands.repair_articles._init_minimal_container"
        ) as mock_init:
            with patch(
                "modules.management.commands.repair_articles._shutdown_minimal_container"
            ) as mock_shutdown:
                mock_init.return_value = (
                    AsyncMock(),
                    AsyncMock(),
                    AsyncMock(),
                    MagicMock(),
                    MagicMock(),
                )

                with patch("modules.storage.postgres.article_repo.ArticleRepo") as mock_repo_class:
                    mock_repo = AsyncMock()
                    mock_repo.get_incomplete_articles = AsyncMock(return_value=[])
                    mock_repo_class.return_value = mock_repo

                    from modules.management.commands.repair_articles import repair_articles

                    await repair_articles(limit=25, force=False, dry_run=True)
                    mock_repo.get_incomplete_articles.assert_called_with(limit=25)


class TestInitMinimalContainer:
    """Tests for _init_minimal_container function."""

    @pytest.mark.asyncio
    async def test_init_returns_expected_services(self):
        """Test that _init_minimal_container returns all expected services."""
        from modules.management.commands.repair_articles import _init_minimal_container

        with patch("modules.management.commands.repair_articles.Settings") as mock_settings:
            with patch("modules.management.commands.repair_articles.PostgresPool") as mock_pg:
                with patch("modules.management.commands.repair_articles.RedisClient") as mock_redis:
                    with patch("modules.management.commands.repair_articles.LLMClient") as mock_llm:
                        with patch(
                            "modules.management.commands.repair_articles.PromptLoader"
                        ) as mock_prompt:
                            mock_settings.return_value = MagicMock()
                            mock_pg.return_value.startup = AsyncMock()
                            mock_redis.return_value.startup = AsyncMock()
                            mock_llm.create_from_config = AsyncMock()

                            result = await _init_minimal_container()

                            assert len(result) == 5


class TestShutdownMinimalContainer:
    """Tests for _shutdown_minimal_container function."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_all_services(self):
        """Test that all services are properly shut down."""
        from modules.management.commands.repair_articles import _shutdown_minimal_container

        mock_pg = AsyncMock()
        mock_redis = AsyncMock()
        mock_llm = AsyncMock()

        await _shutdown_minimal_container(mock_pg, mock_redis, mock_llm)

        mock_llm.close.assert_called_once()
        mock_redis.shutdown.assert_called_once()
        mock_pg.shutdown.assert_called_once()
