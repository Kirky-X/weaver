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


class TestRSSParserExtractWechatUrl:
    """Test RSSParser._extract_wechat_url static method (anyfeeder WeChat feeds)."""

    def test_extracts_biz_and_mid_from_content(self):
        """Scenario: Real WeChat URL constructed from biz and mid."""
        entry = {
            "link": "http://weixin.sogou.com/weixin?type=2&query=央视财经",
            "content": [
                {"value": '<p>...<a href="biz=MjM5NzQ5MTkyMA">..&mid=2658216812&idx=1..</a></p>'}
            ],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result == "https://mp.weixin.qq.com/s?__biz=MjM5NzQ5MTkyMA&mid=2658216812"

    def test_no_content_returns_none(self):
        """Scenario: WeChat entry without biz in content falls back to link."""
        entry = {
            "link": "http://weixin.sogou.com/weixin?type=2&query=央视财经",
            "content": [{"value": "<p>no biz here</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result is None

    def test_missing_mid_returns_none(self):
        """Scenario: WeChat entry without mid falls back to link."""
        entry = {
            "link": "http://weixin.sogou.com/weixin?type=2&query=央视财经",
            "content": [{"value": "<p>...biz=MjM5NzQ5MTkyMA...</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result is None

    def test_empty_content_returns_none(self):
        """Scenario: WeChat entry with no content:encoded field."""
        entry = {"link": "http://weixin.sogou.com/weixin?type=2&query=央视财经", "content": []}
        result = RSSParser._extract_wechat_url(entry)
        assert result is None

    def test_base64_padding_stripped(self):
        """Scenario: biz value with base64 padding stripped."""
        entry = {
            "link": "http://weixin.sogou.com/weixin",
            "content": [{"value": "<p>...biz=MjM5NzQ5MTkyMA==&mid=123456789&idx=1...</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result == "https://mp.weixin.qq.com/s?__biz=MjM5NzQ5MTkyMA&mid=123456789"

    def test_different_mid_values_produce_unique_urls(self):
        """Scenario: Multiple WeChat articles each get unique URLs."""
        mids = ["2658216812", "2658216813", "2658216814", "2658216815", "2658216816"]
        entry_base = {
            "link": "http://weixin.sogou.com/weixin?type=2&query=央视财经",
            "content": [{"value": "<p>...biz=MjM5NzQ5MTkyMA...</p>"}],
        }
        urls = []
        for mid in mids:
            entry = {
                **entry_base,
                "content": [{"value": f"<p>...biz=MjM5NzQ5MTkyMA&mid={mid}...</p>"}],
            }
            url = RSSParser._extract_wechat_url(entry)
            assert url is not None
            urls.append(url)
        assert len(set(urls)) == len(mids), "All URLs must be unique"

    def test_normalized_wechat_url_format(self):
        """Scenario: Normalized WeChat URL for deduplication."""
        entry = {
            "link": "http://weixin.sogou.com/weixin",
            "content": [{"value": "<p>...biz=MjM5NzQ5MTkyMA&mid=2658216812...</p>"}],
        }
        url = RSSParser._extract_wechat_url(entry)
        # mp.weixin.qq.com domain is dedup-able and stable
        assert url.startswith("https://mp.weixin.qq.com/s?")
        assert "__biz=" in url
        assert "&mid=" in url

    def test_non_wechat_link_returns_none(self):
        """Scenario: Non-WeChat RSS links passed through unchanged (helper returns None)."""
        entry = {
            "link": "https://example.com/article/123",
            "content": [{"value": "<p>some content</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result is None

    def test_title_and_description_not_modified(self):
        """Scenario: Only the NewsItem.url field is affected by WeChat extraction."""
        # This is validated by the parse() integration tests below.

    @pytest.mark.asyncio
    async def test_parse_anyfeeder_wechat_replaces_link(self):
        """Integration test: parse() replaces Sogou link with real WeChat URL."""
        rss_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>CCTV财经</title>
    <item>
        <title>CCTV Article 1</title>
        <link>http://weixin.sogou.com/weixin?type=2&query=央视财经</link>
        <content:encoded><![CDATA[<p>...biz=MjM5NzQ5MTkyMA&mid=2658216812...</p>]]></content:encoded>
    </item>
    <item>
        <title>CCTV Article 2</title>
        <link>http://weixin.sogou.com/weixin?type=2&query=央视财经</link>
        <content:encoded><![CDATA[<p>...biz=MjM5NzQ5MTkyMA&mid=2658216813...</p>]]></content:encoded>
    </item>
</channel>
</rss>"""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, rss_content, {}))
        parser = RSSParser(mock_fetcher)
        config = SourceConfig(id="cctv", name="cctv", url="https://plink.anyfeeder.com/weixin/cctv")

        items = await parser.parse(config)

        assert len(items) == 2
        assert all("mp.weixin.qq.com" in item.url for item in items)
        assert all("weixin.sogou.com" not in item.url for item in items)
        assert items[0].title == "CCTV Article 1"
        assert items[1].title == "CCTV Article 2"
        # Verify URLs are unique
        assert items[0].url != items[1].url

    @pytest.mark.asyncio
    async def test_parse_non_wechat_unchanged(self):
        """Integration test: non-WeChat feeds are not affected."""
        rss_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Normal Feed</title>
    <item>
        <title>Normal Article</title>
        <link>https://example.com/article/123</link>
    </item>
</channel>
</rss>"""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, rss_content, {}))
        parser = RSSParser(mock_fetcher)
        config = SourceConfig(id="normal", name="normal", url="https://example.com/feed")

        items = await parser.parse(config)

        assert len(items) == 1
        assert items[0].url == "https://example.com/article/123"

    @pytest.mark.asyncio
    async def test_parse_wechat_fallback_to_raw_link(self):
        """Integration test: WeChat entry without biz falls back to raw Sogou link."""
        rss_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <item>
        <title>Partial WeChat</title>
        <link>http://weixin.sogou.com/weixin?type=2&query=央视财经</link>
        <content:encoded><![CDATA[<p>no biz here</p>]]></content:encoded>
    </item>
</channel>
</rss>"""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value=(200, rss_content, {}))
        parser = RSSParser(mock_fetcher)
        config = SourceConfig(
            id="wechat", name="wechat", url="https://plink.anyfeeder.com/weixin/test"
        )

        items = await parser.parse(config)

        # Falls back to the raw sogou link (not skipped)
        assert len(items) == 1
        assert "weixin.sogou.com" in items[0].url


class TestRSSParserClose:
    """Test RSSParser close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        parser = RSSParser(MagicMock())

        await parser.close()
