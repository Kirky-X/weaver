"""Two-level deduplication: Redis Hash + DB UNIQUE constraint."""

from __future__ import annotations

import hashlib
import time

from core.cache.redis import RedisClient
from core.observability.logging import get_logger

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

        pipe = self._redis.pipeline()
        url_hashes = [self._hash(item.url) for item in items]
        for h in url_hashes:
            pipe.hexists(self.DEDUP_KEY, h)
        exists = await pipe.execute()

        candidates = [item for item, ex in zip(items, exists) if not ex]

        if not candidates:
            log.debug("dedup_all_filtered_by_redis", original=len(items))
            return []

        urls = [item.url for item in candidates]
        if hasattr(self._repo, "get_existing_urls"):
            db_existing = await self._repo.get_existing_urls(urls)
            new_items = [item for item in candidates if item.url not in db_existing]
        else:
            new_items = candidates

        if new_items:
            pipe = self._redis.pipeline()
            now = str(int(time.time()))
            for item in new_items:
                pipe.hset(self.DEDUP_KEY, self._hash(item.url), now)
            await pipe.execute()

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
            log.info("dedup_cleanup", removed=len(expired_keys), remaining=len(all_entries) - len(expired_keys))

        return len(expired_keys)

    @staticmethod
    def _hash(url: str) -> str:
        """Generate a short hash for a URL."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]
