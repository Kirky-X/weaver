# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for RSS Parser."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.source.models import SourceConfig
from modules.source.rss_parser import RSSParser


class TestRSSParserInit:
    """Test RSSParser initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_fetcher = MagicMock()
        parser = RSSParser(mock_fetcher)

        assert parser._fetcher == mock_fetcher


class TestRSSParserParse:
    """Test RSSParser parse method."""

    @pytest.fixture
    def mock_fetcher(self):
        """Create mock fetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock()
        return fetcher

    @pytest.fixture
    def parser(self, mock_fetcher):
        """Create RSSParser instance."""
        return RSSParser(mock_fetcher)

    @pytest.fixture
    def sample_config(self):
        """Create sample SourceConfig."""
        return SourceConfig(
            id="test-source-id",
            name="test_source",
            url="https://example.com/feed.xml",
        )

    @pytest.fixture
    def sample_rss_content(self):
        """Sample RSS feed content."""
        return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
        <title>Article 1</title>
        <link>https://example.com/article1</link>
        <description>Description 1</description>
        <pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>
    </item>
    <item>
        <title>Article 2</title>
        <link>https://example.com/article2</link>
        <description>Description 2</description>
        <pubDate>Tue, 02 Jan 2024 12:00:00 +0000</pubDate>
    </item>
</channel>
</rss>"""

    @pytest.mark.asyncio
    async def test_parse_basic(self, parser, mock_fetcher, sample_config, sample_rss_content):
        """Test basic RSS parsing."""
        mock_fetcher.fetch = AsyncMock(return_value=(200, sample_rss_content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 2
        assert items[0].title == "Article 1"
        assert items[0].url == "https://example.com/article1"
        assert items[0].source == "test_source"
        assert items[0].source_host == "example.com"

    @pytest.mark.asyncio
    async def test_parse_with_etag(self, parser, mock_fetcher, sample_config, sample_rss_content):
        """Test parsing with ETag header."""
        sample_config.etag = "test-etag"
        mock_fetcher.fetch = AsyncMock(return_value=(200, sample_rss_content, {"ETag": "new-etag"}))

        items = await parser.parse(sample_config)

        call_args = mock_fetcher.fetch.call_args
        assert "If-None-Match" in call_args[1]["headers"]
        assert sample_config.etag == "new-etag"

    @pytest.mark.asyncio
    async def test_parse_with_last_modified(
        self, parser, mock_fetcher, sample_config, sample_rss_content
    ):
        """Test parsing with Last-Modified header."""
        sample_config.last_modified = "Mon, 01 Jan 2024 00:00:00 GMT"
        mock_fetcher.fetch = AsyncMock(
            return_value=(
                200,
                sample_rss_content,
                {"Last-Modified": "Tue, 02 Jan 2024 00:00:00 GMT"},
            )
        )

        items = await parser.parse(sample_config)

        call_args = mock_fetcher.fetch.call_args
        assert "If-Modified-Since" in call_args[1]["headers"]
        assert sample_config.last_modified == "Tue, 02 Jan 2024 00:00:00 GMT"

    @pytest.mark.asyncio
    async def test_parse_not_modified_304(self, parser, mock_fetcher, sample_config):
        """Test handling 304 Not Modified response."""
        mock_fetcher.fetch = AsyncMock(return_value=(304, "", {}))

        items = await parser.parse(sample_config)

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_parse_unexpected_status(self, parser, mock_fetcher, sample_config):
        """Test handling unexpected status code."""
        mock_fetcher.fetch = AsyncMock(return_value=(500, "Server Error", {}))

        items = await parser.parse(sample_config)

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_parse_fetch_error(self, parser, mock_fetcher, sample_config):
        """Test handling fetch error."""
        mock_fetcher.fetch = AsyncMock(side_effect=Exception("Network error"))

        items = await parser.parse(sample_config)

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_parse_filter_by_last_crawl_time(
        self, parser, mock_fetcher, sample_config, sample_rss_content
    ):
        """Test filtering items by last_crawl_time."""
        sample_config.last_crawl_time = datetime(2024, 1, 3, 0, 0, 0, tzinfo=UTC)
        mock_fetcher.fetch = AsyncMock(return_value=(200, sample_rss_content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_parse_item_without_link(self, parser, mock_fetcher, sample_config):
        """Test handling item without link."""
        rss_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Test Feed</title>
    <item>
        <title>Article without link</title>
        <description>Description</description>
    </item>
    <item>
        <title>Valid Article</title>
        <link>https://example.com/valid</link>
    </item>
</channel>
</rss>"""
        mock_fetcher.fetch = AsyncMock(return_value=(200, rss_content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 1
        assert items[0].title == "Valid Article"

    @pytest.mark.asyncio
    async def test_parse_item_with_summary(self, parser, mock_fetcher, sample_config):
        """Test parsing item with summary."""
        rss_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Test Feed</title>
    <item>
        <title>Article</title>
        <link>https://example.com/article</link>
        <summary>This is a summary</summary>
    </item>
</channel>
</rss>"""
        mock_fetcher.fetch = AsyncMock(return_value=(200, rss_content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 1
        assert items[0].description == "This is a summary"

    @pytest.mark.asyncio
    async def test_parse_atom_feed(self, parser, mock_fetcher, sample_config):
        """Test parsing Atom feed."""
        atom_content = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <title>Test Feed</title>
    <entry>
        <title>Atom Article</title>
        <link href="https://example.com/atom-article"/>
        <summary>Atom summary</summary>
        <updated>2024-01-01T12:00:00Z</updated>
    </entry>
</feed>"""
        mock_fetcher.fetch = AsyncMock(return_value=(200, atom_content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 1
        assert items[0].title == "Atom Article"


class TestRSSParserParseDate:
    """Test RSSParser._parse_date static method."""

    def test_parse_date_with_published_parsed(self):
        """Test parsing date from published_parsed."""
        from time import struct_time

        entry = {"published_parsed": struct_time((2024, 1, 15, 10, 30, 0, 0, 15, 0))}

        result = RSSParser._parse_date(entry)

        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_date_with_updated_parsed(self):
        """Test parsing date from updated_parsed."""
        from time import struct_time

        entry = {"updated_parsed": struct_time((2024, 2, 20, 14, 45, 0, 1, 51, 0))}

        result = RSSParser._parse_date(entry)

        assert result is not None
        assert result.year == 2024
        assert result.month == 2
        assert result.day == 20

    def test_parse_date_no_date(self):
        """Test parsing when no date available."""
        entry = {}

        result = RSSParser._parse_date(entry)

        assert result is None

    def test_parse_date_invalid_struct(self):
        """Test handling invalid struct_time."""
        from time import struct_time

        entry = {"published_parsed": struct_time((9999, 99, 99, 99, 99, 99, 0, 0, 0))}

        result = RSSParser._parse_date(entry)

        assert result is None


class TestRSSParserClose:
    """Test RSSParser close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        parser = RSSParser(MagicMock())

        await parser.close()
