# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Two-level deduplication: Cache Hash + DB UNIQUE constraint."""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlparse, urlunparse

from core.observability.logging import get_logger
from core.observability.metrics import metrics

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger("deduplicator")


class Deduplicator:
    """Two-level URL deduplication.

    Level 1: Cache Hash for fast in-memory filtering.
    Level 2: Database UNIQUE constraint for precise dedup.

    Includes health tracking for cache with automatic fallback to DB
    when cache is unavailable.

    Implements: DeduplicationStrategy

    Args:
        cache: Cache pool instance.
        article_repo: Article repository for DB-level checking.
        ttl_seconds: TTL for cache entries (default 7 days).
    """

    DEDUP_KEY = "crawl:dedup"
    DEFAULT_TTL = 7 * 24 * 60 * 60
    HEALTH_CHECK_INTERVAL = 60  # seconds

    def __init__(
        self,
        cache: CachePool,
        article_repo: object,
        ttl_seconds: int | None = None,
    ) -> None:
        self._cache = cache
        self._repo = article_repo
        self._ttl = ttl_seconds or self.DEFAULT_TTL
        self._cache_healthy = True
        self._last_health_check: float = 0.0
        self._fallback_count = 0

    async def _check_cache_health(self) -> bool:
        """Check cache health with periodic probing.

        Returns:
            True if cache is healthy, False otherwise.
        """
        now = time.monotonic()
        if now - self._last_health_check < self.HEALTH_CHECK_INTERVAL:
            return self._cache_healthy

        self._last_health_check = now
        try:
            await self._cache.ping()
            if not self._cache_healthy:
                log.info("cache_health_restored")
            self._cache_healthy = True
        except Exception as e:
            if self._cache_healthy:
                log.warning("cache_health_degraded", error=str(e))
            self._cache_healthy = False

        return self._cache_healthy

    async def dedup(self, items: list) -> list:
        """Deduplicate a list of items by URL.

        Args:
            items: List of items with `.url` attribute.

        Returns:
            Filtered list of items not seen before.
        """
        if not items:
            return []

        start_time = time.perf_counter()
        original_count = len(items)

        # Check cache health
        cache_available = await self._check_cache_health()

        candidates = items
        cache_filtered = 0

        if cache_available:
            try:
                url_hashes = [self._hash(item.url) for item in items]
                exists = await self._cache.hexists_many(self.DEDUP_KEY, url_hashes)

                candidates = [item for item, ex in zip(items, exists) if not ex]
                cache_filtered = original_count - len(candidates)

                if not candidates:
                    log.debug("dedup_all_filtered_by_cache", original=len(items))
                    elapsed = time.perf_counter() - start_time
                    metrics.dedup_total.labels(stage="url").inc(cache_filtered)
                    metrics.dedup_processing_time.labels(stage="url").observe(elapsed)
                    metrics.articles_processed_total.inc(original_count)
                    metrics.articles_deduped_total.inc(cache_filtered)
                    return []

            except Exception as e:
                log.warning("dedup_cache_failed_using_db_fallback", error=str(e))
                self._cache_healthy = False
                self._fallback_count += 1
                metrics.dedup_redis_fallback_total.inc()
                candidates = items
                cache_filtered = 0
        else:
            # Cache is unhealthy, use DB-only dedup
            self._fallback_count += 1
            metrics.dedup_redis_fallback_total.inc()

        urls = [item.url for item in candidates]
        if hasattr(self._repo, "get_existing_urls"):
            db_existing = await self._repo.get_existing_urls(urls)
            new_items = [item for item in candidates if item.url not in db_existing]
        else:
            new_items = candidates

        db_filtered = len(candidates) - len(new_items)
        total_filtered = cache_filtered + db_filtered

        # Write new URLs to cache if healthy
        if new_items and self._cache_healthy:
            try:
                now_str = str(int(time.time()))
                for item in new_items:
                    await self._cache.hset(self.DEDUP_KEY, self._hash(item.url), now_str)
            except Exception as e:
                log.warning("dedup_cache_write_failed", error=str(e))
                self._cache_healthy = False

        elapsed = time.perf_counter() - start_time
        metrics.dedup_total.labels(stage="url").inc(total_filtered)
        metrics.dedup_processing_time.labels(stage="url").observe(elapsed)
        metrics.articles_processed_total.inc(original_count)
        metrics.articles_deduped_total.inc(total_filtered)

        if original_count > 0:
            ratio = total_filtered / original_count
            metrics.dedup_ratio.labels(stage="url").set(ratio)

        log.info(
            "dedup_complete",
            original=len(items),
            after_cache=len(candidates),
            after_db=len(new_items),
            cache_healthy=self._cache_healthy,
        )
        return new_items

    async def dedup_urls(self, urls: list[str]) -> list[str]:
        """Deduplicate a list of URLs (without full item objects)."""
        if not urls:
            return []

        url_hashes = [self._hash(url) for url in urls]
        exists = await self._cache.hexists_many(self.DEDUP_KEY, url_hashes)

        candidates = [url for url, ex in zip(urls, exists) if not ex]

        if not candidates:
            log.debug("dedup_urls_all_filtered_by_cache", original=len(urls))
            return []

        if hasattr(self._repo, "get_existing_urls"):
            db_existing = await self._repo.get_existing_urls(candidates)
            new_urls = [url for url in candidates if url not in db_existing]
        else:
            new_urls = candidates

        if new_urls:
            now = str(int(time.time()))
            for url in new_urls:
                await self._cache.hset(self.DEDUP_KEY, self._hash(url), now)

        log.info(
            "dedup_urls_complete",
            original=len(urls),
            after_cache=len(candidates),
            after_db=len(new_urls),
        )
        return new_urls

    async def cleanup_expired(self, max_age_seconds: int | None = None) -> int:
        """Clean up expired entries from cache Hash."""
        max_age = max_age_seconds or self._ttl
        cutoff = int(time.time()) - max_age

        all_entries = await self._cache.hgetall(self.DEDUP_KEY)
        if not all_entries:
            return 0

        expired_keys = []
        for key, timestamp in all_entries.items():
            try:
                if int(timestamp) < cutoff:
                    expired_keys.append(key)
            except (ValueError, TypeError):
                expired_keys.append(key)

        if expired_keys:
            await self._cache.hdel(self.DEDUP_KEY, *expired_keys)
            log.info(
                "dedup_cleanup",
                removed=len(expired_keys),
                remaining=len(all_entries) - len(expired_keys),
            )

        return len(expired_keys)

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize a URL for consistent deduplication using urllib.parse.

        Normalization rules:
        1. Protocol-relative URLs → HTTPS (//example.com → https://example.com)
        2. HTTP → HTTPS upgrade
        3. Domain lowercase
        4. Remove www. prefix
        5. Remove default ports (80 for HTTP, 443 for HTTPS)
        6. Decode percent-encoded characters, then re-encode consistently
        7. Normalize path (resolve . and ..)
        8. Remove query string
        9. Remove fragment
        10. Remove trailing slash (except for root which becomes no slash)

        Args:
            url: The URL to normalize.

        Returns:
            Normalized URL string.
        """
        import posixpath

        # Handle protocol-relative URLs
        if url.startswith("//"):
            url = "https:" + url

        # Parse the URL
        parsed = urlparse(url)

        # 1. Normalize scheme: HTTP → HTTPS
        scheme = parsed.scheme.lower()
        original_scheme = scheme
        if scheme == "http":
            scheme = "https"

        # 2. Normalize netloc: lowercase, remove www., remove default ports
        netloc = parsed.netloc.lower()

        # Remove www. prefix
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Remove default ports based on ORIGINAL scheme before upgrade
        # For HTTP URLs (upgraded to HTTPS), port 80 should be removed
        # For HTTPS URLs, port 443 should be removed
        if original_scheme == "http" and netloc.endswith(":80"):
            netloc = netloc[:-3]
        elif netloc.endswith(":443"):
            netloc = netloc[:-4]

        # 3. Normalize path
        path = parsed.path

        # Decode percent-encoded characters
        path = unquote(path)

        # Normalize path (resolve . and ..)
        path = posixpath.normpath(path)

        # Ensure path starts with /
        if not path.startswith("/"):
            path = "/" + path

        # Remove trailing slash (including root path)
        if path.endswith("/"):
            path = path.rstrip("/")

        # Re-encode path (preserve non-ASCII characters for readability)
        path = quote(path, safe="/", encoding="utf-8")

        # Handle empty path
        if not path:
            path = ""

        # 4. Remove query string and fragment
        # Special case: WeChat articles are uniquely identified by __biz + mid
        # in the query string, so these must be preserved.
        if netloc == "mp.weixin.qq.com":
            query_params = parsed.query.split("&") if parsed.query else []
            kept = []
            dropped = []
            for param in query_params:
                if param.startswith(("__biz=", "mid=")):
                    kept.append(param)
                else:
                    dropped.append(param)
            if dropped:
                log.debug("wechat_query_params_dropped", count=len(dropped))
            query = "&".join(kept) if kept else ""
        else:
            query = ""

        return urlunparse((scheme, netloc, path, "", query, ""))

    @staticmethod
    def _hash(url: str) -> str:
        """Generate a short hash for a URL."""
        return hashlib.sha256(Deduplicator.normalize_url(url).encode()).hexdigest()[:16]
