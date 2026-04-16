# Copyright (c) 2026 KirkyX. All Rights Reserved
"""NewsNow API parser for fetching news from newsnow.world."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import json_repair

from core.observability.logging import get_logger
from modules.ingestion.domain.models import NewsItem, SourceConfig
from modules.ingestion.fetching.base import BaseFetcher
from modules.ingestion.parsing.base import BaseSourceParser

log = get_logger(__name__)


class NewsNowParser(BaseSourceParser):
    """Parses NewsNow API responses.

    Supports multiple news sources like 36kr, baidu, etc.
    API format: https://www.newsnow.world/api/s?id={source_id}

    Args:
        fetcher: BaseFetcher instance for API fetching.
    """

    API_BASE_URL = "https://www.newsnow.world/api/s?id="

    def __init__(self, fetcher: BaseFetcher) -> None:
        self._fetcher = fetcher

    async def parse(self, config: SourceConfig) -> list[NewsItem]:
        """Fetch and parse NewsNow API response.

        Args:
            config: Source configuration with API URL.

        Returns:
            List of new NewsItem objects.
        """
        try:
            status_code, content, _ = await self._fetcher.fetch(config.url)
        except Exception as exc:
            log.warning("newsnow_fetch_failed", url=config.url, error=str(exc))
            return []

        if status_code != 200:
            log.warning(
                "newsnow_unexpected_status",
                url=config.url,
                status=status_code,
            )
            return []

        data = json_repair.loads(content)
        # json_repair.loads returns '' for invalid JSON (instead of raising)
        if not isinstance(data, (dict, list)):
            log.warning(
                "newsnow_json_parse_failed",
                url=config.url,
                error="invalid JSON returned empty string",
            )
            return []

        status = data.get("status")
        if status not in ("success", "cache"):
            log.warning(
                "newsnow_api_error",
                url=config.url,
                status=status,
            )
            return []

        items_data = data.get("items", [])
        if not items_data:
            log.debug("newsnow_no_items", url=config.url)
            return []

        items: list[NewsItem] = []
        for entry in items_data:
            url = entry.get("url", "")
            if not url:
                continue

            # Skip newsflash/list pages that contain multiple articles
            # These are list pages, not individual article pages
            if self._is_list_page(url):
                log.debug("newsnow_skipping_list_page", url=url)
                continue

            title = entry.get("title", "")
            if not title:
                continue

            pub_date = self._parse_date(entry)

            if config.last_crawl_time and pub_date:
                if pub_date <= config.last_crawl_time:
                    continue

            host = urlparse(url).netloc
            items.append(
                NewsItem(
                    url=url,
                    title=title,
                    source=config.name,
                    source_host=host,
                    publish_time=pub_date,
                    description="",
                )
            )

        log.info("newsnow_parsed", url=config.url, items_found=len(items))
        return items

    @staticmethod
    def _parse_date(entry: dict) -> datetime | None:
        """Parse publication date from NewsNow API entry.

        Args:
            entry: NewsNow API item entry.

        Returns:
            Parsed datetime or None.
        """
        extra = entry.get("extra", {})
        timestamp = extra.get("date")

        if timestamp is None:
            return None

        try:
            if isinstance(timestamp, (int, float)):
                if timestamp > 1e12:
                    timestamp = timestamp / 1000
                return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, ValueError, OSError):
            return None

        return None

    @staticmethod
    def _is_list_page(url: str) -> bool:
        """Check if URL is a list page (newsflash, category, etc.) rather than an article.

        List pages contain multiple articles and should not be crawled as single articles.
        Distinguishes between true list pages and individual items with numeric IDs.

        Args:
            url: URL to check.

        Returns:
            True if this is a list page that should be skipped.
        """
        # Patterns where numeric IDs are individual articles (not list pages)
        # e.g., /newsflashes/3765005718012416 is a single flash article
        numeric_article_patterns = [
            "/newsflashes",
            "/newsflash",
        ]

        # Patterns that are always list pages (even with numeric segments like years)
        # e.g., /archive/2024, /category/tech, /tag/ai are all list pages
        list_page_patterns = [
            "/list",
            "/category",
            "/tag",
            "/archive",
        ]

        url_lower = url.lower()
        # Remove query string for cleaner matching
        path = url_lower.split("?")[0]

        import re

        # Check numeric article patterns - these are individual articles with numeric IDs
        for pattern in numeric_article_patterns:
            # Exact match (list page): /newsflashes or /newsflashes/
            if path.endswith(pattern) or path.endswith(pattern + "/"):
                return True
            # Numeric ID (individual article): /newsflashes/3765005718012416
            match = re.search(rf"{pattern}/(\d+)$", path)
            if match:
                return False  # This is an individual article, not a list page
            # Non-numeric segment (list page): /newsflashes/something
            match = re.search(rf"{pattern}/([^/]+)", path)
            if match and not match.group(1).isdigit():
                return True  # Non-numeric segment means list page

        # Check list page patterns - these are always list pages
        for pattern in list_page_patterns:
            # Exact match or any segment after = list page
            if path.endswith(pattern) or path.endswith(pattern + "/"):
                return True
            match = re.search(rf"{pattern}/([^/]+)", path)
            if match:
                return True

        return False

    async def close(self) -> None:
        """Close resources."""
        pass
