# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Content hash cache collaborator.

Caches processing results keyed by SHA-256 of article title+body so that
re-ingested duplicate content can short-circuit the pipeline.

Extracted from ``Pipeline`` to keep the orchestrator focused on flow control.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from core.observability.metrics import MetricsCollector
from core.types.ingestion_models import RawArticle
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger(__name__)

# Bump when the cached snapshot schema changes: entries written by older
# versions are treated as misses instead of being merged into new states.
_CACHE_SCHEMA_VERSION = 2

# Keys never cached: per-article identity and non-serializable objects.
# ``_cache_hit`` (and any future private marker) is excluded via the
# leading-underscore rule below.
_UNCACHEABLE_KEYS = frozenset({"raw", "article_id", "task_id"})

# Cached snapshots expire after 7 days
_CACHE_TTL_SECONDS = 604800


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
            List of cached result snapshots (None for cache misses). A valid
            snapshot carries the full processed state (``cleaned``, analysis
            results, ``vectors``); entries from an older schema version are
            reported as misses so they never pollute fresh pipeline states.
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
                        parsed = json.loads(cached)
                    except (json.JSONDecodeError, TypeError):
                        parsed = None
                    if (
                        isinstance(parsed, dict)
                        and parsed.get("_schema_version") == _CACHE_SCHEMA_VERSION
                        and "cleaned" in parsed
                    ):
                        results.append(parsed)
                        MetricsCollector.content_hash_cache_hit_total.labels(hit="hit").inc()
                    else:
                        # Corrupt entry or stale schema — treat as a miss.
                        results.append(None)
                        MetricsCollector.content_hash_cache_hit_total.labels(hit="miss").inc()
                else:
                    results.append(None)
                    MetricsCollector.content_hash_cache_hit_total.labels(hit="miss").inc()
            return results
        except Exception as exc:
            log.warning("content_hash_cache_check_failed", error=str(exc))
            return [None] * len(articles)

    def _snapshot_pair(self, state: PipelineState) -> tuple[str, dict[str, Any]] | None:
        """Build (cache_key, snapshot_dict) for a state; None when unwritable."""
        raw = state.get("raw")
        if not raw:
            return None

        content = f"{raw.title}{raw.body}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        cache_key = f"content_hash:{content_hash}"

        snapshot: dict[str, Any] = {"_schema_version": _CACHE_SCHEMA_VERSION}
        for key, value in state.items():
            if key in _UNCACHEABLE_KEYS or key.startswith("_"):
                continue
            if key == "entities" and isinstance(value, list):
                # Strip per-entity embeddings: they dominate the snapshot size
                # (1024 floats each → hundreds of KB per article) and would
                # blow Redis capacity under the 7-day TTL. Entity vectors live
                # in entity_vectors (persisted on first encounter of the
                # entity) — a cache hit skips Phase 3 entirely so they are
                # never recomputed from the snapshot anyway.
                value = [
                    {k: v for k, v in entity.items() if k != "embedding"}
                    if isinstance(entity, dict)
                    else entity
                    for entity in value
                ]
            snapshot[key] = value
        return cache_key, snapshot

    async def write(self, state: PipelineState) -> None:
        """Write the processed state snapshot to the content hash cache.

        The snapshot must match what the pipeline mappers consume
        (``cleaned``, ``sentiment``, ``credibility``, ``summary_info``,
        ``vectors``, ...) so a cache hit can short-circuit Phase 1/Phase 3
        without losing analysis results or embeddings.

        Args:
            state: Completed pipeline state to cache.
        """
        if not self._cache_client:
            return

        pair = self._snapshot_pair(state)
        if pair is None:
            return
        cache_key, snapshot = pair

        try:
            payload = await asyncio.to_thread(json.dumps, snapshot, ensure_ascii=False, default=str)
            await self._cache_client.set(
                cache_key,
                payload,
                ex=_CACHE_TTL_SECONDS,
            )
        except Exception as exc:
            log.warning("content_hash_cache_write_failed", error=str(exc))

    async def write_batch(self, states: list[PipelineState]) -> None:
        """Write multiple processing results to content hash cache.

        Serialization runs in a worker thread (large snapshots with vectors)
        and all keys are flushed in a single pipeline round trip.

        Args:
            states: List of completed pipeline states to cache.
        """
        if not self._cache_client or not states:
            return

        pairs = [pair for pair in (self._snapshot_pair(s) for s in states) if pair]
        if not pairs:
            return

        try:
            serialized = await asyncio.to_thread(
                lambda: [
                    (key, json.dumps(snapshot, ensure_ascii=False, default=str))
                    for key, snapshot in pairs
                ]
            )
            async with self._cache_client.pipeline() as pipe:
                for key, payload in serialized:
                    pipe.set(key, payload, ex=_CACHE_TTL_SECONDS)
                await pipe.execute()
        except Exception as exc:
            log.warning("content_hash_cache_write_failed", error=str(exc))
