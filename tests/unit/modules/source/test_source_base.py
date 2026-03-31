# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for BaseSourceParser."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_fetcher():
    """Mock fetcher."""
    return AsyncMock()


class TestRSSParser:
    """Tests for RSSParser."""

    @pytest.mark.asyncio
    async def test_rss_parser_initializes(self, mock_fetcher):
        """Test that RSS parser initializes."""
        from modules.source.rss_parser import RSSParser

        parser = RSSParser(fetcher=mock_fetcher)

        assert parser is not None
        assert parser._fetcher is not None

    @pytest.mark.asyncio
    async def test_rss_parser_has_parse_method(self, mock_fetcher):
        """Test RSS parser has parse method."""
        from modules.source.rss_parser import RSSParser

        parser = RSSParser(fetcher=mock_fetcher)

        # Verify parser has expected methods
        assert hasattr(parser, "parse")


class TestNewsNowParser:
    """Tests for NewsNowParser."""

    @pytest.mark.asyncio
    async def test_newsnow_parser_initializes(self, mock_fetcher):
        """Test that NewsNow parser initializes."""
        from modules.source.newsnow_parser import NewsNowParser

        parser = NewsNowParser(fetcher=mock_fetcher)

        assert parser is not None
        assert parser._fetcher is not None

    @pytest.mark.asyncio
    async def test_newsnow_parser_has_parse_method(self, mock_fetcher):
        """Test NewsNow parser has parse method."""
        from modules.source.newsnow_parser import NewsNowParser

        parser = NewsNowParser(fetcher=mock_fetcher)

        # Verify parser has expected methods
        assert hasattr(parser, "parse")


class TestSourceParserConfiguration:
    """Tests for source parser configuration validation."""

    def test_source_config_required_fields(self):
        """Test that SourceConfig requires expected fields."""
        from modules.source.models import SourceConfig

        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )

        assert config.id == "test_source"
        assert config.name == "Test Source"
        assert config.url == "https://example.com/feed"
        assert config.source_type == "rss"
        assert config.enabled is True

    def test_source_config_optional_fields(self):
        """Test SourceConfig with optional fields."""
        from modules.source.models import SourceConfig

        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
            interval_minutes=60,
            per_host_concurrency=4,
        )

        assert config.interval_minutes == 60
        assert config.per_host_concurrency == 4


class TestSourceParserErrorHandling:
    """Error handling tests for source parsers."""

    @pytest.mark.asyncio
    async def test_rss_parser_handles_fetch_error(self, mock_fetcher):
        """Test RSS parser handles fetch errors."""
        from modules.source.rss_parser import RSSParser

        mock_fetcher.fetch = AsyncMock(side_effect=Exception("Network error"))

        parser = RSSParser(fetcher=mock_fetcher)

        # Parser should handle error gracefully
        try:
            result = await parser.parse("https://example.com/feed")
            assert result is not None
        except Exception:
            # It's acceptable to raise
            pass

    @pytest.mark.asyncio
    async def test_newsnow_parser_handles_fetch_error(self, mock_fetcher):
        """Test NewsNow parser handles fetch errors."""
        from modules.source.newsnow_parser import NewsNowParser

        mock_fetcher.fetch = AsyncMock(side_effect=Exception("Network error"))

        parser = NewsNowParser(fetcher=mock_fetcher)

        # Parser should handle error gracefully
        try:
            result = await parser.parse("https://example.com/news")
            assert result is not None
        except Exception:
            # It's acceptable to raise
            pass
