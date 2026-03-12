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
    """

    DEDUP_KEY = "crawl:dedup"

    def __init__(self, redis: RedisClient, article_repo: object) -> None:
        self._redis = redis
        self._repo = article_repo

    async def dedup(self, items: list) -> list:
        """Deduplicate a list of items by URL.

        Args:
            items: List of items with `.url` attribute.

        Returns:
            Filtered list of items not seen before.
        """
        if not items:
            return []

        # Level 1: Redis Hash fast filter
        pipe = self._redis.pipeline()
        url_hashes = [self._hash(item.url) for item in items]
        for h in url_hashes:
            pipe.hexists(self.DEDUP_KEY, h)
        exists = await pipe.execute()

        candidates = [item for item, ex in zip(items, exists) if not ex]

        if not candidates:
            log.debug("dedup_all_filtered_by_redis", original=len(items))
            return []

        # Level 2: DB precise check via UNIQUE index
        urls = [item.url for item in candidates]
        if hasattr(self._repo, "get_existing_urls"):
            db_existing = await self._repo.get_existing_urls(urls)
            new_items = [item for item in candidates if item.url not in db_existing]
        else:
            new_items = candidates

        # Record new URLs in Redis
        if new_items:
            pipe = self._redis.pipeline()
            for item in new_items:
                pipe.hset(self.DEDUP_KEY, self._hash(item.url), str(int(time.time())))
            await pipe.execute()

        log.info(
            "dedup_complete",
            original=len(items),
            after_redis=len(candidates),
            after_db=len(new_items),
        )
        return new_items

    @staticmethod
    def _hash(url: str) -> str:
        """Generate a short hash for a URL."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]
