# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for RSS Parser (ingestion module)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import SourceConfig
from modules.ingestion.parsing.rss_parser import RSSParser


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


class TestRSSParserStripHtmlTags:
    """Test RSSParser._strip_html_tags() static method."""

    def test_strips_all_html_tags(self):
        """Removes all HTML/XML tags."""
        html = "<p>第一段</p>\n<div>第二段</div>\n<span>第三段</span>"
        result = RSSParser._strip_html_tags(html)
        assert result == "第一段 第二段 第三段"

    def test_decodes_common_html_entities(self):
        """Decodes common HTML entities."""
        html = "&nbsp;&amp;&lt;&gt;&quot;&#39;&apos;"
        result = RSSParser._strip_html_tags(html)
        assert result == "&<>\"''"

    def test_normalizes_whitespace(self):
        """Collapses multiple whitespace into single space."""
        html = "<p>第一段    </p>\n\n   <div>第二段</div>"
        result = RSSParser._strip_html_tags(html)
        assert "  " not in result
        assert "第一段" in result
        assert "第二段" in result

    def test_empty_string(self):
        """Returns empty string for empty input."""
        assert RSSParser._strip_html_tags("") == ""

    def test_strips_wechat_bare_fragment(self):
        """Strips bare WeChat HTML fragment."""
        html = (
            "<div><div><div class='rich_media_content' id='js_content'>"
            "<p style='line-height:1.75em;'>伊朗伊斯兰革命卫队发动密集攻势。"
            "伊朗使用重型弹道导弹和大规模无人机群打击科威特美军基地。</p>"
            "<section></section>"
            "<p>数千名海军陆战队员将从圣迭戈出发。</p>"
            "</div></div></div>"
        )
        result = RSSParser._strip_html_tags(html)
        assert "伊朗伊斯兰革命卫队" in result
        assert "<div" not in result
        assert "<p" not in result


class TestRSSParserStripWechatNoise:
    """Test RSSParser._strip_wechat_noise() static method."""

    def test_removes_recommendation_section(self):
        """Removes WeChat recommendation section."""
        text = "正文内容\n近期热门视频你会关注\n推荐文章1\n推荐文章2"
        result = RSSParser._strip_wechat_noise(text)
        assert "正文内容" in result
        assert "近期热门视频" not in result
        assert "推荐文章" not in result

    def test_removes_footer_noise(self):
        """Removes WeChat article footer."""
        text = "正文内容\n来源：公众号\n文章原文\n"
        result = RSSParser._strip_wechat_noise(text)
        assert "正文内容" in result
        assert "来源：" not in result
        assert "文章原文" not in result

    def test_empty_string(self):
        """Returns empty string for empty input."""
        assert RSSParser._strip_wechat_noise("") == ""


class TestRSSParserExtractBody:
    """Test RSSParser._extract_body() static method."""

    def test_extracts_from_content_encoded_html(self):
        """Strips HTML tags from content:encoded."""
        html = (
            "<p>国际黄金和白银期价在经历前一个交易日的暴跌后反弹。</p>"
            "<p>截至北京时间20日15点50分，纽约商品交易所黄金主力合约期价报每盎司4698.50美元。</p>"
        )
        entry = {"content": [{"value": html}]}
        result = RSSParser._extract_body(entry)
        assert "国际黄金和白银期价" in result
        assert "<p>" not in result

    def test_extracts_from_summary_when_no_content(self):
        """Falls back to summary when content:encoded is absent."""
        entry = {
            "summary": "<p>黄金市场近期出现显著回调，金价跌幅超过16%。</p>",
        }
        result = RSSParser._extract_body(entry)
        assert "黄金市场" in result
        assert "16%" in result

    def test_plain_text_summary(self):
        """Plain text summary passes through."""
        entry = {
            "summary": "这是一段中文摘要文本。",
        }
        result = RSSParser._extract_body(entry)
        assert result == "这是一段中文摘要文本。"

    def test_returns_empty_string_when_no_content_or_summary(self):
        """Returns empty string when entry has no content or summary."""
        entry = {}
        result = RSSParser._extract_body(entry)
        assert result == ""

    def test_prefers_content_over_summary(self):
        """content:encoded takes priority over summary."""
        html = "<p>来自content:encoded的完整正文。</p>"
        entry = {
            "content": [{"value": html}],
            "summary": "<p>这只是摘要。</p>",
        }
        result = RSSParser._extract_body(entry)
        assert "完整正文" in result
        assert "只是摘要" not in result


class TestRSSParserExtractWechatUrl:
    """Test RSSParser._extract_wechat_url static method."""

    def test_extracts_biz_and_mid_from_content(self):
        """Extract real WeChat URL from biz and mid."""
        entry = {
            "link": "http://weixin.sogou.com/weixin?type=2&query=央视财经",
            "content": [
                {"value": '<p>...<a href="biz=MjM5NzQ5MTkyMA">..&mid=2658216812&idx=1..</a></p>'}
            ],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result == "https://mp.weixin.qq.com/s?__biz=MjM5NzQ5MTkyMA&mid=2658216812"

    def test_no_content_returns_none(self):
        """Returns None when no content."""
        entry = {
            "link": "http://weixin.sogou.com/weixin?type=2&query=央视财经",
            "content": [{"value": "<p>no biz here</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result is None

    def test_missing_mid_returns_none(self):
        """Returns None when mid is missing."""
        entry = {
            "link": "http://weixin.sogou.com/weixin?type=2&query=央视财经",
            "content": [{"value": "<p>...biz=MjM5NzQ5MTkyMA...</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result is None

    def test_empty_content_returns_none(self):
        """Returns None when content list is empty."""
        entry = {"link": "http://weixin.sogou.com/weixin", "content": []}
        result = RSSParser._extract_wechat_url(entry)
        assert result is None

    def test_base64_padding_stripped(self):
        """Strips base64 padding from biz value."""
        entry = {
            "link": "http://weixin.sogou.com/weixin",
            "content": [{"value": "<p>...biz=MjM5NzQ5MTkyMA==&mid=123456789&idx=1...</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result == "https://mp.weixin.qq.com/s?__biz=MjM5NzQ5MTkyMA&mid=123456789"

    def test_non_wechat_link_returns_none(self):
        """Returns None for non-WeChat links."""
        entry = {
            "link": "https://example.com/article/123",
            "content": [{"value": "<p>some content</p>"}],
        }
        result = RSSParser._extract_wechat_url(entry)
        assert result is None


class TestRSSParserClose:
    """Test RSSParser close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        parser = RSSParser(MagicMock())

        await parser.close()
