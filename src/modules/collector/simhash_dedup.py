# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Title SimHash deduplication for fast pre-filtering of similar articles."""

from __future__ import annotations

import time
from dataclasses import dataclass

from simhash import Simhash

from core.cache.redis import RedisClient
from core.observability.logging import get_logger
from core.observability.metrics import metrics

log = get_logger("simhash_dedup")


@dataclass
class TitleItem:
    """Item with title for SimHash deduplication."""

    url: str
    title: str


class SimHashDeduplicator:
    """Title-based SimHash deduplication.

    Uses 64-bit SimHash fingerprints to quickly identify similar titles.
    Articles with Hamming distance ≤ threshold are considered duplicates.

    Args:
        redis: Redis client for fingerprint storage.
        threshold: Maximum Hamming distance for similarity (default: 3).
        ttl_seconds: TTL for Redis entries (default 7 days).
    """

    SIMHASH_KEY = "crawl:simhash:title"
    DEFAULT_THRESHOLD = 3
    DEFAULT_TTL = 7 * 24 * 60 * 60  # 7 days

    def __init__(
        self,
        redis: RedisClient,
        threshold: int | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self._redis = redis
        self._threshold = threshold or self.DEFAULT_THRESHOLD
        self._ttl = ttl_seconds or self.DEFAULT_TTL

    @staticmethod
    def generate_fingerprint(title: str) -> int:
        """Generate a 64-bit SimHash fingerprint from title.

        Args:
            title: Article title text.

        Returns:
            64-bit SimHash fingerprint as integer.
        """
        # Simhash uses character-level features by default
        # For better Chinese support, we can use word-level features
        # But for simplicity, we use default character-level
        sh = Simhash(title, f=64)
        return sh.value

    @staticmethod
    def hamming_distance(fp1: int, fp2: int) -> int:
        """Calculate Hamming distance between two fingerprints.

        Args:
            fp1: First fingerprint.
            fp2: Second fingerprint.

        Returns:
            Number of differing bits.
        """
        # XOR the two fingerprints and count 1 bits
        xor = fp1 ^ fp2
        return bin(xor).count("1")

    async def dedup_titles(self, items: list[TitleItem]) -> list[TitleItem]:
        """Deduplicate items by title similarity.

        Args:
            items: List of items with title attribute.

        Returns:
            Filtered list of items with unique titles.
        """
        if not items:
            return []

        # Get existing fingerprints from Redis
        existing_fps = await self._redis.hgetall(self.SIMHASH_KEY)

        # Generate fingerprints for new items
        new_items: list[TitleItem] = []
        new_fps: list[tuple[str, int, str]] = []  # (hash_key, fingerprint, url)

        for item in items:
            fp = self.generate_fingerprint(item.title)
            fp_str = str(fp)

            # Check against existing fingerprints
            is_duplicate = False
            for existing_fp_str, existing_url in existing_fps.items():
                try:
                    existing_fp = int(existing_fp_str)
                    distance = self.hamming_distance(fp, existing_fp)
                    if distance <= self._threshold:
                        log.debug(
                            "simhash_duplicate_found",
                            title=item.title[:50],
                            distance=distance,
                            existing_url=existing_url,
                        )
                        is_duplicate = True
                        break
                except (ValueError, TypeError):
                    continue

            # Also check against already-accepted new items
            if not is_duplicate:
                for _, new_fp, _ in new_fps:
                    distance = self.hamming_distance(fp, new_fp)
                    if distance <= self._threshold:
                        log.debug(
                            "simhash_duplicate_in_batch",
                            title=item.title[:50],
                            distance=distance,
                        )
                        is_duplicate = True
                        break

            if not is_duplicate:
                new_items.append(item)
                new_fps.append((fp_str, fp, item.url))

        # Store new fingerprints in Redis
        if new_fps:
            pipe = self._redis.pipeline()
            now = str(int(time.time()))
            for fp_str, _, url in new_fps:
                pipe.hset(self.SIMHASH_KEY, fp_str, f"{url}|{now}")
            await pipe.execute()

        log.info(
            "simhash_dedup_complete",
            original=len(items),
            unique=len(new_items),
            filtered=len(items) - len(new_items),
        )

        return new_items

    async def dedup_titles_with_metrics(
        self, items: list[TitleItem]
    ) -> tuple[list[TitleItem], int]:
        """Deduplicate items and return metrics.

        Args:
            items: List of items with title attribute.

        Returns:
            Tuple of (filtered items, count of filtered duplicates).
        """
        start_time = time.perf_counter()
        original_count = len(items)

        unique_items = await self.dedup_titles(items)
        filtered_count = original_count - len(unique_items)

        # Record metrics
        elapsed = time.perf_counter() - start_time
        metrics.dedup_total.labels(stage="title").inc(filtered_count)
        metrics.dedup_processing_time.labels(stage="title").observe(elapsed)

        # Update ratio gauge
        if original_count > 0:
            ratio = filtered_count / original_count
            metrics.dedup_ratio.labels(stage="title").set(ratio)

        return unique_items, filtered_count

    async def cleanup_expired(self, max_age_seconds: int | None = None) -> int:
        """Clean up expired entries from Redis Hash.

        Args:
            max_age_seconds: Maximum age in seconds (default: use TTL).

        Returns:
            Number of entries removed.
        """
        max_age = max_age_seconds or self._ttl
        cutoff = int(time.time()) - max_age

        all_entries = await self._redis.hgetall(self.SIMHASH_KEY)
        if not all_entries:
            return 0

        expired_keys = []
        for key, value in all_entries.items():
            try:
                # Value format: "url|timestamp"
                if "|" in str(value):
                    _, timestamp = str(value).rsplit("|", 1)
                    if int(timestamp) < cutoff:
                        expired_keys.append(key)
                else:
                    # Old format without timestamp, consider expired
                    expired_keys.append(key)
            except (ValueError, TypeError):
                expired_keys.append(key)

        if expired_keys:
            await self._redis.hdel(self.SIMHASH_KEY, *expired_keys)
            log.info(
                "simhash_cleanup",
                removed=len(expired_keys),
                remaining=len(all_entries) - len(expired_keys),
            )

        return len(expired_keys)

    async def get_stats(self) -> dict:
        """Get SimHash deduplication statistics.

        Returns:
            Dictionary with statistics.
        """
        all_entries = await self._redis.hgetall(self.SIMHASH_KEY)
        return {
            "total_fingerprints": len(all_entries),
            "redis_key": self.SIMHASH_KEY,
            "threshold": self._threshold,
            "ttl_seconds": self._ttl,
        }
