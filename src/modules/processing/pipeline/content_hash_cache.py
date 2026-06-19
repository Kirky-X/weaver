# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Content hash cache collaborator.

Caches processing results keyed by SHA-256 of article title+body so that
re-ingested duplicate content can short-circuit the pipeline.

Extracted from ``Pipeline`` to keep the orchestrator focused on flow control.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from core.observability.metrics import MetricsCollector
from modules.ingestion.domain.models import RawArticle
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger(__name__)


class ContentHashCacheService:
    """Content-hash based cache for pipeline processing results.

    Single responsibility: check whether an article's content hash has a
    cached processing result, and write results back to the cache after
    successful processing.

    Args:
        cache_client: Cache pool (Redis). May be None when caching is disabled.
    """

    def __init__(self, *, cache_client: CachePool | None) -> None:
        self._cache_client = cache_client

    async def check(self, articles: list[RawArticle]) -> list[dict[str, Any] | None]:
        """Check content hash cache for a batch of articles.

        Args:
            articles: List of raw articles to check.

        Returns:
            List of cached results (None for cache misses).
        """
        if not self._cache_client:
            return [None] * len(articles)

        # Compute content hashes
        cache_keys = []
        for article in articles:
            content = f"{article.title}{article.body}"
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            cache_keys.append(f"content_hash:{content_hash}")

        try:
            cached_values = await self._cache_client.mget(cache_keys)
            results: list[dict[str, Any] | None] = []
            for cached in cached_values:
                if cached:
                    try:
                        results.append(json.loads(cached))
                        MetricsCollector.content_hash_cache_hit_total.labels(hit="hit").inc()
                    except (json.JSONDecodeError, TypeError):
                        results.append(None)
                        MetricsCollector.content_hash_cache_hit_total.labels(hit="miss").inc()
                else:
                    results.append(None)
                    MetricsCollector.content_hash_cache_hit_total.labels(hit="miss").inc()
            return results
        except Exception as exc:
            log.warning("content_hash_cache_check_failed", error=str(exc))
            return [None] * len(articles)

    async def write(self, state: PipelineState) -> None:
        """Write processing result to content hash cache.

        Args:
            state: Completed pipeline state to cache.
        """
        if not self._cache_client:
            return

        raw = state.get("raw")
        if not raw:
            return

        content = f"{raw.title}{raw.body}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        cache_key = f"content_hash:{content_hash}"

        # Cache essential fields
        cache_data = {
            "title": state.get("title", raw.title),
            "body": state.get("body", raw.body),
            "category": state.get("category"),
            "quality_score": state.get("quality_score"),
            "credibility_score": state.get("credibility_score"),
            "sentiment_score": state.get("sentiment_score"),
        }

        try:
            await self._cache_client.set(
                cache_key,
                json.dumps(cache_data, ensure_ascii=False),
                ex=604800,  # 7 days TTL
            )
        except Exception as exc:
            log.warning("content_hash_cache_write_failed", error=str(exc))

    async def write_batch(self, states: list[PipelineState]) -> None:
        """Write multiple processing results to content hash cache.

        Args:
            states: List of completed pipeline states to cache.
        """
        for state in states:
            await self.write(state)
