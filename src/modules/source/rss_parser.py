"""RSS/Atom feed parser with incremental fetching."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser

from modules.fetcher.base import BaseFetcher
from modules.source.base import BaseSourceParser
from modules.source.models import NewsItem, SourceConfig
from core.observability.logging import get_logger

log = get_logger("rss_parser")


class RSSParser(BaseSourceParser):
    """Parses RSS/Atom feeds using feedparser.

    Supports:
    - ETag / If-Modified-Since for incremental fetching.
    - pubDate filtering to avoid re-processing old items.

    Args:
        fetcher: BaseFetcher instance for feed fetching.
    """

    def __init__(self, fetcher: BaseFetcher) -> None:
        self._fetcher = fetcher

    async def parse(self, config: SourceConfig) -> list[NewsItem]:
        """Fetch and parse an RSS/Atom feed.

        Uses ETag/If-Modified-Since headers for conditional requests.
        Filters items by pubDate against last_crawl_time.

        Args:
            config: Source configuration with feed URL and state.

        Returns:
            List of new NewsItem objects.
        """
        headers: dict[str, str] = {}
        if config.etag:
            headers["If-None-Match"] = config.etag
        if config.last_modified:
            headers["If-Modified-Since"] = config.last_modified

        try:
            status_code, content, response_headers = await self._fetcher.fetch(
                config.url, headers=headers if headers else None
            )
        except Exception as exc:
            log.warning("rss_fetch_failed", url=config.url, error=str(exc))
            return []

        if status_code == 304:
            log.debug("rss_not_modified", url=config.url)
            return []

        if status_code != 200:
            log.warning(
                "rss_unexpected_status",
                url=config.url,
                status=status_code,
            )
            return []

        config.etag = response_headers.get("ETag")
        config.last_modified = response_headers.get("Last-Modified")

        feed = feedparser.parse(content)
        items: list[NewsItem] = []

        for entry in feed.entries:
            url = entry.get("link", "")
            if not url:
                continue

            pub_date = self._parse_date(entry)

            if config.last_crawl_time and pub_date:
                if pub_date <= config.last_crawl_time:
                    continue

            host = urlparse(url).netloc
            items.append(
                NewsItem(
                    url=url,
                    title=entry.get("title", ""),
                    source=config.name,
                    source_host=host,
                    pubDate=pub_date,
                    description=entry.get("summary", ""),
                )
            )

        log.info("rss_parsed", url=config.url, items_found=len(items))
        return items

    @staticmethod
    def _parse_date(entry: dict) -> datetime | None:
        """Parse a feedparser entry's publication date."""
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            try:
                from time import mktime
                return datetime.fromtimestamp(mktime(published), tz=timezone.utc)
            except (OverflowError, ValueError):
                return None
        return None

    async def close(self) -> None:
        """Close resources.

        Note: The fetcher is managed externally and should be closed by its owner.
        """
        pass
