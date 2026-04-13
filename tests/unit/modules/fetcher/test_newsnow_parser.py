# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for NewsNow Parser."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import SourceConfig
from modules.ingestion.parsing.newsnow_parser import NewsNowParser


class TestNewsNowParserInit:
    """Test NewsNowParser initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_fetcher = MagicMock()
        parser = NewsNowParser(mock_fetcher)

        assert parser._fetcher == mock_fetcher
        assert parser.API_BASE_URL == "https://www.newsnow.world/api/s?id="


class TestNewsNowParserParse:
    """Test NewsNowParser parse method."""

    @pytest.fixture
    def mock_fetcher(self):
        """Create mock fetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock()
        return fetcher

    @pytest.fixture
    def parser(self, mock_fetcher):
        """Create NewsNowParser instance."""
        return NewsNowParser(mock_fetcher)

    @pytest.fixture
    def sample_config(self):
        """Create sample SourceConfig."""
        return SourceConfig(
            id="newsnow-36kr",
            name="36氪",
            url="https://www.newsnow.world/api/s?id=36kr",
            source_type="newsnow",
        )

    @pytest.fixture
    def sample_api_response(self):
        """Sample NewsNow API response."""
        return {
            "status": "success",
            "id": "36kr",
            "updatedTime": 1773685030059,
            "items": [
                {
                    "url": "https://www.36kr.com/newsflashes/3725628913449344",
                    "title": "何小鹏：中美自动驾驶同处第一梯队",
                    "id": "/newsflashes/3725628913449344",
                    "extra": {"date": 1773667031908},
                },
                {
                    "url": "https://www.36kr.com/newsflashes/3725621545892483",
                    "title": "热门中概股美股盘前集体走强，阿里巴巴涨近3%",
                    "id": "/newsflashes/3725621545892483",
                    "extra": {"date": 1773667031908},
                },
            ],
        }

    @pytest.mark.asyncio
    async def test_parse_basic(self, parser, mock_fetcher, sample_config, sample_api_response):
        """Test basic NewsNow API parsing."""
        content = json.dumps(sample_api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 2
        assert items[0].title == "何小鹏：中美自动驾驶同处第一梯队"
        assert items[0].url == "https://www.36kr.com/newsflashes/3725628913449344"
        assert items[0].source == "36氪"
        assert items[0].source_host == "www.36kr.com"

    @pytest.mark.asyncio
    async def test_parse_baidu_source(self, parser, mock_fetcher):
        """Test parsing baidu source."""
        config = SourceConfig(
            id="newsnow-baidu",
            name="百度热搜",
            url="https://www.newsnow.world/api/s?id=baidu",
            source_type="newsnow",
        )
        api_response = {
            "status": "success",
            "id": "baidu",
            "items": [
                {
                    "url": "https://www.baidu.com/link?url=test123",
                    "title": "测试新闻标题",
                    "extra": {"date": 1704067200000},
                },
            ],
        }
        content = json.dumps(api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(config)

        assert len(items) == 1
        assert items[0].title == "测试新闻标题"
        assert items[0].source == "百度热搜"

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
    async def test_parse_invalid_json(self, parser, mock_fetcher, sample_config):
        """Test handling invalid JSON response."""
        mock_fetcher.fetch = AsyncMock(return_value=(200, "not valid json", {}))

        items = await parser.parse(sample_config)

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_parse_api_error_status(self, parser, mock_fetcher, sample_config):
        """Test handling API error status."""
        api_response = {"status": "error", "message": "Source not found"}
        content = json.dumps(api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_parse_cache_status(
        self, parser, mock_fetcher, sample_config, sample_api_response
    ):
        """Test handling cache status (should work like success)."""
        sample_api_response["status"] = "cache"
        content = json.dumps(sample_api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_parse_empty_items(self, parser, mock_fetcher, sample_config):
        """Test handling empty items list."""
        api_response = {"status": "success", "items": []}
        content = json.dumps(api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_parse_item_without_url(self, parser, mock_fetcher, sample_config):
        """Test handling item without URL."""
        api_response = {
            "status": "success",
            "items": [
                {"title": "Article without URL", "extra": {"date": 1704067200000}},
                {
                    "url": "https://example.com/valid",
                    "title": "Valid Article",
                    "extra": {"date": 1704067200000},
                },
            ],
        }
        content = json.dumps(api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 1
        assert items[0].title == "Valid Article"

    @pytest.mark.asyncio
    async def test_parse_item_without_title(self, parser, mock_fetcher, sample_config):
        """Test handling item without title."""
        api_response = {
            "status": "success",
            "items": [
                {"url": "https://example.com/no-title", "extra": {"date": 1704067200000}},
                {
                    "url": "https://example.com/valid",
                    "title": "Valid Article",
                    "extra": {"date": 1704067200000},
                },
            ],
        }
        content = json.dumps(api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 1
        assert items[0].title == "Valid Article"

    @pytest.mark.asyncio
    async def test_parse_filter_by_last_crawl_time(
        self, parser, mock_fetcher, sample_config, sample_api_response
    ):
        """Test filtering items by last_crawl_time."""
        sample_config.last_crawl_time = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
        content = json.dumps(sample_api_response)
        mock_fetcher.fetch = AsyncMock(return_value=(200, content, {}))

        items = await parser.parse(sample_config)

        assert len(items) == 0


class TestNewsNowParserParseDate:
    """Test NewsNowParser._parse_date static method."""

    def test_parse_date_with_milliseconds(self):
        """Test parsing date with milliseconds timestamp."""
        entry = {"extra": {"date": 1773667031908}}

        result = NewsNowParser._parse_date(entry)

        assert result is not None
        assert result.year == 2026

    def test_parse_date_with_seconds(self):
        """Test parsing date with seconds timestamp."""
        entry = {"extra": {"date": 1704067200}}

        result = NewsNowParser._parse_date(entry)

        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1

    def test_parse_date_no_extra(self):
        """Test parsing when no extra field."""
        entry = {}

        result = NewsNowParser._parse_date(entry)

        assert result is None

    def test_parse_date_no_date_in_extra(self):
        """Test parsing when no date in extra."""
        entry = {"extra": {}}

        result = NewsNowParser._parse_date(entry)

        assert result is None

    def test_parse_date_invalid_timestamp(self):
        """Test handling invalid timestamp."""
        entry = {"extra": {"date": "invalid"}}

        result = NewsNowParser._parse_date(entry)

        assert result is None


class TestNewsNowParserClose:
    """Test NewsNowParser close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        parser = NewsNowParser(MagicMock())

        await parser.close()
