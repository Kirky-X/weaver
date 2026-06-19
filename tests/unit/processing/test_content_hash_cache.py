# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for content hash cache layer (ContentHashCacheService).

Covers:
- Content hash hit -> skip processing
- Cache miss -> execute full pipeline
- Processing complete -> write to cache
- Cache TTL correctly set

The cache logic was extracted from Pipeline into ContentHashCacheService;
these tests target the service directly.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.pipeline.content_hash_cache import ContentHashCacheService
from modules.processing.pipeline.state import PipelineState


def _make_raw_article(title: str = "Test Title", body: str = "Test body content.") -> RawArticle:
    """Create a test RawArticle."""
    return RawArticle(
        url="https://example.com/test",
        title=title,
        body=body,
        source="test_source",
    )


def _compute_content_hash(title: str, body: str) -> str:
    """Compute content hash matching service logic."""
    content = f"{title}{body}"
    return hashlib.sha256(content.encode()).hexdigest()


class TestContentHashCacheHit:
    """Test cache hit behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_processing(self):
        """When content hash is in cache, skip full pipeline processing."""
        article = _make_raw_article()
        content_hash = _compute_content_hash(article.title, article.body)

        # Mock cache client with cached result
        cache_client = AsyncMock()
        cached_result = json.dumps(
            {
                "title": article.title,
                "body": article.body,
                "category": "politics",
                "quality_score": 0.85,
            }
        )
        cache_client.mget.return_value = [cached_result]

        service = ContentHashCacheService(cache_client=cache_client)

        # Call the method under test
        result = await service.check([article])

        # Verify cache was checked
        cache_client.mget.assert_called_once()
        called_keys = cache_client.mget.call_args[0][0]
        assert len(called_keys) == 1
        assert called_keys[0] == f"content_hash:{content_hash}"

        # Verify result is from cache
        assert result[0] is not None
        assert result[0]["category"] == "politics"

    @pytest.mark.asyncio
    async def test_cache_hit_batch(self):
        """Batch of articles with all cache hits."""
        articles = [
            _make_raw_article("Title 1", "Body 1"),
            _make_raw_article("Title 2", "Body 2"),
        ]

        cache_client = AsyncMock()
        cached_results = [
            json.dumps({"title": "Title 1", "category": "politics"}),
            json.dumps({"title": "Title 2", "category": "economy"}),
        ]
        cache_client.mget.return_value = cached_results

        service = ContentHashCacheService(cache_client=cache_client)

        result = await service.check(articles)

        assert len(result) == 2
        assert result[0]["category"] == "politics"
        assert result[1]["category"] == "economy"


class TestContentHashCacheMiss:
    """Test cache miss behavior."""

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        """When content hash is not in cache, return None for each article."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        cache_client.mget.return_value = [None]

        service = ContentHashCacheService(cache_client=cache_client)

        result = await service.check([article])

        assert result[0] is None

    @pytest.mark.asyncio
    async def test_cache_miss_batch(self):
        """Batch of articles with all cache misses."""
        articles = [
            _make_raw_article("Title 1", "Body 1"),
            _make_raw_article("Title 2", "Body 2"),
        ]

        cache_client = AsyncMock()
        cache_client.mget.return_value = [None, None]

        service = ContentHashCacheService(cache_client=cache_client)

        result = await service.check(articles)

        assert len(result) == 2
        assert result[0] is None
        assert result[1] is None


class TestContentHashCacheWrite:
    """Test cache write after processing."""

    @pytest.mark.asyncio
    async def test_write_to_cache_after_processing(self):
        """After processing, write result to cache with correct TTL."""
        article = _make_raw_article()
        content_hash = _compute_content_hash(article.title, article.body)

        cache_client = AsyncMock()
        cache_client.set.return_value = None

        service = ContentHashCacheService(cache_client=cache_client)

        state = PipelineState(raw=article)
        state["category"] = "politics"
        state["quality_score"] = 0.85

        await service.write(state)

        # Verify cache was written
        cache_client.set.assert_called_once()
        call_args = cache_client.set.call_args
        key = call_args[0][0]
        value = call_args[0][1]
        ttl = call_args[1]["ex"]

        assert key == f"content_hash:{content_hash}"
        assert "politics" in value
        assert ttl == 604800  # 7 days

    @pytest.mark.asyncio
    async def test_write_batch_to_cache(self):
        """Batch write to cache after processing."""
        articles = [
            _make_raw_article("Title 1", "Body 1"),
            _make_raw_article("Title 2", "Body 2"),
        ]

        cache_client = AsyncMock()
        cache_client.set.return_value = None

        service = ContentHashCacheService(cache_client=cache_client)

        states = []
        for article in articles:
            state = PipelineState(raw=article)
            state["category"] = "politics"
            states.append(state)

        await service.write_batch(states)

        # Verify cache was written for each article
        assert cache_client.set.call_count == 2


class TestContentHashCacheDisabled:
    """Test behavior when cache is disabled."""

    @pytest.mark.asyncio
    async def test_no_cache_client_returns_none(self):
        """When cache_client is None, return None for all articles."""
        article = _make_raw_article()

        service = ContentHashCacheService(cache_client=None)

        result = await service.check([article])

        assert result[0] is None

    @pytest.mark.asyncio
    async def test_no_write_when_cache_disabled(self):
        """When cache_client is None, don't attempt to write."""
        article = _make_raw_article()

        service = ContentHashCacheService(cache_client=None)

        state = PipelineState(raw=article)
        state["category"] = "politics"

        # Should not raise
        await service.write(state)


class TestContentHashCacheMetrics:
    """Test Prometheus metrics for content hash cache."""

    @pytest.mark.asyncio
    async def test_cache_hit_increments_metric(self):
        """Cache hit should increment content_hash_cache_hit_total counter."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        cache_client.mget.return_value = ['{"title": "Test"}']

        service = ContentHashCacheService(cache_client=cache_client)

        with patch(
            "modules.processing.pipeline.content_hash_cache.MetricsCollector"
        ) as mock_metrics:
            mock_counter = MagicMock()
            mock_metrics.content_hash_cache_hit_total.labels.return_value = mock_counter
            await service.check([article])
            mock_metrics.content_hash_cache_hit_total.labels.assert_called_with(hit="hit")

    @pytest.mark.asyncio
    async def test_cache_miss_increments_metric(self):
        """Cache miss should increment content_hash_cache_hit_total counter with miss label."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        cache_client.mget.return_value = [None]

        service = ContentHashCacheService(cache_client=cache_client)

        with patch(
            "modules.processing.pipeline.content_hash_cache.MetricsCollector"
        ) as mock_metrics:
            mock_counter = MagicMock()
            mock_metrics.content_hash_cache_hit_total.labels.return_value = mock_counter
            await service.check([article])
            mock_metrics.content_hash_cache_hit_total.labels.assert_called_with(hit="miss")
