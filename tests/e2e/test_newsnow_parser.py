"""Tests for NewsNowParser list page filtering."""

from __future__ import annotations

import pytest

from modules.ingestion.parsing.newsnow_parser import NewsNowParser


@pytest.mark.e2e
class TestNewsNowParserListPageFilter:
    """Test NewsNowParser._is_list_page method."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            # Newsflash URLs should be skipped
            ("https://36kr.com/newsflashes/3762051664102145", True),
            ("https://36kr.com/newsflashes/123456", True),
            ("https://example.com/newsflash/789", True),
            # List/category pages should be skipped
            ("https://example.com/list/tech", True),
            ("https://example.com/category/news", True),
            ("https://example.com/tag/ai", True),
            ("https://example.com/archive/2024", True),
            # Article URLs should NOT be skipped
            ("https://36kr.com/p/123456", False),
            ("https://example.com/article/tech-news", False),
            ("https://example.com/news/some-article", False),
            ("https://techcrunch.com/2024/01/01/some-news", False),
        ],
    )
    def test_is_list_page(self, url: str, expected: bool):
        """Test list page detection."""
        assert NewsNowParser._is_list_page(url) == expected
