# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Two-level deduplication: Redis Hash + DB UNIQUE constraint."""

from __future__ import annotations

import hashlib
import time

from core.cache.redis import RedisClient
from core.observability.logging import get_logger
from core.observability.metrics import metrics

log = get_logger("deduplicator")


class Deduplicator:
    """Two-level URL deduplication.

    Level 1: Redis Hash for fast in-memory filtering.
    Level 2: Database UNIQUE constraint for precise dedup.

    Args:
        redis: Redis client instance.
        article_repo: Article repository for DB-level checking.
        ttl_seconds: TTL for Redis entries (default 7 days).
    """

    DEDUP_KEY = "crawl:dedup"
    DEFAULT_TTL = 7 * 24 * 60 * 60

    def __init__(
        self,
        redis: RedisClient,
        article_repo: object,
        ttl_seconds: int | None = None,
    ) -> None:
        self._redis = redis
        self._repo = article_repo
        self._ttl = ttl_seconds or self.DEFAULT_TTL

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

        pipe = self._redis.pipeline()
        url_hashes = [self._hash(item.url) for item in items]
        for h in url_hashes:
            pipe.hexists(self.DEDUP_KEY, h)
        exists = await pipe.execute()

        candidates = [item for item, ex in zip(items, exists) if not ex]
        redis_filtered = original_count - len(candidates)

        if not candidates:
            log.debug("dedup_all_filtered_by_redis", original=len(items))
            # Record metrics
            elapsed = time.perf_counter() - start_time
            metrics.dedup_total.labels(stage="url").inc(redis_filtered)
            metrics.dedup_processing_time.labels(stage="url").observe(elapsed)
            metrics.articles_processed_total.inc(original_count)
            metrics.articles_deduped_total.inc(redis_filtered)
            return []

        urls = [item.url for item in candidates]
        if hasattr(self._repo, "get_existing_urls"):
            db_existing = await self._repo.get_existing_urls(urls)
            new_items = [item for item in candidates if item.url not in db_existing]
        else:
            new_items = candidates

        db_filtered = len(candidates) - len(new_items)
        total_filtered = redis_filtered + db_filtered

        if new_items:
            pipe = self._redis.pipeline()
            now = str(int(time.time()))
            for item in new_items:
                pipe.hset(self.DEDUP_KEY, self._hash(item.url), now)
            await pipe.execute()

        # Record metrics
        elapsed = time.perf_counter() - start_time
        metrics.dedup_total.labels(stage="url").inc(total_filtered)
        metrics.dedup_processing_time.labels(stage="url").observe(elapsed)
        metrics.articles_processed_total.inc(original_count)
        metrics.articles_deduped_total.inc(total_filtered)

        # Update ratio gauge
        if original_count > 0:
            ratio = total_filtered / original_count
            metrics.dedup_ratio.labels(stage="url").set(ratio)

        log.info(
            "dedup_complete",
            original=len(items),
            after_redis=len(candidates),
            after_db=len(new_items),
        )
        return new_items

    async def dedup_urls(self, urls: list[str]) -> list[str]:
        """Deduplicate a list of URLs (without full item objects).

        Args:
            urls: List of URL strings.

        Returns:
            Filtered list of URLs not seen before.
        """
        if not urls:
            return []

        pipe = self._redis.pipeline()
        url_hashes = [self._hash(url) for url in urls]
        for h in url_hashes:
            pipe.hexists(self.DEDUP_KEY, h)
        exists = await pipe.execute()

        candidates = [url for url, ex in zip(urls, exists) if not ex]

        if not candidates:
            log.debug("dedup_urls_all_filtered_by_redis", original=len(urls))
            return []

        if hasattr(self._repo, "get_existing_urls"):
            db_existing = await self._repo.get_existing_urls(candidates)
            new_urls = [url for url in candidates if url not in db_existing]
        else:
            new_urls = candidates

        if new_urls:
            pipe = self._redis.pipeline()
            now = str(int(time.time()))
            for url in new_urls:
                pipe.hset(self.DEDUP_KEY, self._hash(url), now)
            await pipe.execute()

        log.info(
            "dedup_urls_complete",
            original=len(urls),
            after_redis=len(candidates),
            after_db=len(new_urls),
        )
        return new_urls

    async def cleanup_expired(self, max_age_seconds: int | None = None) -> int:
        """Clean up expired entries from Redis Hash.

        Args:
            max_age_seconds: Maximum age in seconds (default: use TTL).

        Returns:
            Number of entries removed.
        """
        max_age = max_age_seconds or self._ttl
        cutoff = int(time.time()) - max_age

        all_entries = await self._redis.hgetall(self.DEDUP_KEY)
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
            await self._redis.hdel(self.DEDUP_KEY, *expired_keys)
            log.info(
                "dedup_cleanup",
                removed=len(expired_keys),
                remaining=len(all_entries) - len(expired_keys),
            )

        return len(expired_keys)

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize a URL for consistent deduplication.

        Normalization rules (in order):
        1. Unify protocol to HTTPS (http:// → https://)
        2. Remove Fragment (#anchor)
        3. Convert domain to lowercase
        4. Remove trailing slash from path
        5. Remove www. prefix
        6. Remove query string

        Examples:
            http://www.36kr.com/p/123/?f=rss#comments  ->  https://36kr.com/p/123
            https://EXAMPLE.COM/Article/123/           ->  https://example.com/Article/123
            //www.36kr.com/p/123                       ->  https://36kr.com/p/123
        """
        # Handle protocol-relative URLs
        if url.startswith("//"):
            url = "https:" + url
        # Unify HTTP to HTTPS
        elif url.startswith("http://"):
            url = "https://" + url.removeprefix("http://")

        # Remove fragment (#anchor)
        if "#" in url:
            url = url.split("#", 1)[0]

        # Remove query string
        if "?" in url:
            url = url.split("?", 1)[0]

        # Parse URL for domain and path manipulation
        # Format: https://domain/path
        if "://" in url:
            proto, rest = url.split("://", 1)
            # Split domain and path
            if "/" in rest:
                domain, path = rest.split("/", 1)
                # Lowercase domain
                domain = domain.lower()
                # Remove www. prefix
                if domain.startswith("www."):
                    domain = domain.removeprefix("www.")
                # Reconstruct
                url = f"{proto}://{domain}/{path}"
            else:
                # No path, just domain
                domain = rest.lower()
                if domain.startswith("www."):
                    domain = domain.removeprefix("www.")
                url = f"{proto}://{domain}"

        # Remove trailing slash (but keep root path)
        if url.endswith("/") and not url.endswith("://"):
            url = url.rstrip("/")

        # Ensure root path has trailing slash for domain-only URLs
        # e.g., https://example.com -> https://example.com (no trailing slash)

        return url

    @staticmethod
    def _hash(url: str) -> str:
        """Generate a short hash for a URL."""
        return hashlib.sha256(Deduplicator.normalize_url(url).encode()).hexdigest()[:16]
