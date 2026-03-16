"""NewsNow API parser for fetching news from newsnow.net.cn."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from modules.fetcher.base import BaseFetcher
from modules.source.base import BaseSourceParser
from modules.source.models import NewsItem, SourceConfig
from core.observability.logging import get_logger

log = get_logger("newsnow_parser")


class NewsNowParser(BaseSourceParser):
    """Parses NewsNow API responses.

    Supports multiple news sources like 36kr, baidu, etc.
    API format: https://www.newsnow.net.cn/api/s?id={source_id}

    Args:
        fetcher: BaseFetcher instance for API fetching.
    """

    API_BASE_URL = "https://www.newsnow.net.cn/api/s"

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

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            log.warning("newsnow_json_parse_failed", url=config.url, error=str(exc))
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
                    pubDate=pub_date,
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
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, ValueError, OSError):
            return None

        return None

    async def close(self) -> None:
        """Close resources."""
        pass
