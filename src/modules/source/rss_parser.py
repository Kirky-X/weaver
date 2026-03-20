# Copyright (c) 2026 KirkyX. All Rights Reserved
"""RSS/Atom feed parser with incremental fetching."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import feedparser

from core.observability.logging import get_logger
from modules.fetcher.base import BaseFetcher
from modules.source.base import BaseSourceParser
from modules.source.models import NewsItem, SourceConfig

log = get_logger("rss_parser")

# Pattern to extract biz and mid from HTML content (e.g. content:encoded).
_WECHAT_BIZ_MID_RE = re.compile(r'(?:biz|__biz)=([^&"\'<>]+)', re.IGNORECASE)
_WECHAT_MID_RE = re.compile(r'\bmid=([^&"\'<>]+)', re.IGNORECASE)
_WECHAT_SOGOU_RE = re.compile(r"https?://(?:www\.)?weixin\.sogou\.com/", re.IGNORECASE)


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

            # anyfeeder WeChat feeds: extract real mp.weixin.qq.com URL from HTML.
            if _WECHAT_SOGOU_RE.match(url):
                maybe = self._extract_wechat_url(entry)
                if maybe:
                    url = maybe

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
    def _extract_wechat_url(entry: dict) -> str | None:
        """Extract real WeChat article URL from a Sogou-proxied RSS entry.

        anyfeeder WeChat feeds publish all articles under the same Sogou search-page
        link. The real article identifiers (``biz`` + ``mid``) live in the
        ``<content:encoded>`` HTML and can be used to construct a
        ``mp.weixin.qq.com`` URL.

        Falls back to ``None`` if either identifier is missing; callers should
        use the original ``<link>`` value in that case.
        """
        # content:encoded is available as entry.content[0].value in feedparser.
        # Use .get() (works for both FeedParserDict and plain dict) and check
        # for non-empty list before indexing.
        content_list = entry.get("content")
        if not isinstance(content_list, list) or len(content_list) == 0:
            return None
        html = content_list[0].get("value", "") if isinstance(content_list[0], dict) else None

        if not html:
            return None

        biz_match = _WECHAT_BIZ_MID_RE.search(html)
        mid_match = _WECHAT_MID_RE.search(html)

        if not biz_match or not mid_match:
            return None

        biz = biz_match.group(1).rstrip("=")
        mid = mid_match.group(1)
        return f"https://mp.weixin.qq.com/s?__biz={biz}&mid={mid}"

    @staticmethod
    def _parse_date(entry: dict) -> datetime | None:
        """Parse a feedparser entry's publication date."""
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            try:
                from time import mktime

                return datetime.fromtimestamp(mktime(published), tz=UTC)
            except (OverflowError, ValueError):
                return None
        return None

    async def close(self) -> None:
        """Close resources.

        Note: The fetcher is managed externally and should be closed by its owner.
        """
        pass
