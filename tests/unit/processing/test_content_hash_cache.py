# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for content hash cache layer in Pipeline.

Covers:
- Content hash hit -> skip processing
- Cache miss -> execute full pipeline
- Processing complete -> write to cache
- Cache TTL correctly set
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.processing.pipeline.graph import Pipeline
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
    """Compute content hash matching pipeline logic."""
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

        # Create pipeline with mock cache
        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        # Call the method under test
        result = await Pipeline._check_content_hash_cache(pipeline, [article])

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

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        result = await Pipeline._check_content_hash_cache(pipeline, articles)

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

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        result = await Pipeline._check_content_hash_cache(pipeline, [article])

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

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        result = await Pipeline._check_content_hash_cache(pipeline, articles)

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

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        state = PipelineState(raw=article)
        state["category"] = "politics"
        state["quality_score"] = 0.85

        await Pipeline._write_content_hash_cache(pipeline, state)

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

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        states = []
        for article in articles:
            state = PipelineState(raw=article)
            state["category"] = "politics"
            states.append(state)

        # Call _write_content_hash_cache for each state
        for state in states:
            await Pipeline._write_content_hash_cache(pipeline, state)

        # Verify cache was written for each article
        assert cache_client.set.call_count == 2


class TestContentHashCacheDisabled:
    """Test behavior when cache is disabled."""

    @pytest.mark.asyncio
    async def test_no_cache_client_returns_none(self):
        """When cache_client is None, return None for all articles."""
        article = _make_raw_article()

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = None
        pipeline._settings = MagicMock()

        result = await Pipeline._check_content_hash_cache(pipeline, [article])

        assert result[0] is None

    @pytest.mark.asyncio
    async def test_no_write_when_cache_disabled(self):
        """When cache_client is None, don't attempt to write."""
        article = _make_raw_article()

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = None
        pipeline._settings = MagicMock()

        state = PipelineState(raw=article)
        state["category"] = "politics"

        # Should not raise
        await Pipeline._write_content_hash_cache(pipeline, state)


class TestContentHashCacheMetrics:
    """Test Prometheus metrics for content hash cache."""

    @pytest.mark.asyncio
    async def test_cache_hit_increments_metric(self):
        """Cache hit should increment content_hash_cache_hit_total counter."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        cache_client.mget.return_value = ['{"title": "Test"}']

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        with patch("modules.processing.pipeline.graph.MetricsCollector") as mock_metrics:
            mock_counter = MagicMock()
            mock_metrics.content_hash_cache_hit_total.labels.return_value = mock_counter
            await Pipeline._check_content_hash_cache(pipeline, [article])
            mock_metrics.content_hash_cache_hit_total.labels.assert_called_with(hit="hit")

    @pytest.mark.asyncio
    async def test_cache_miss_increments_metric(self):
        """Cache miss should increment content_hash_cache_hit_total counter with miss label."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        cache_client.mget.return_value = [None]

        pipeline = MagicMock(spec=Pipeline)
        pipeline._cache_client = cache_client
        pipeline._settings = MagicMock()

        with patch("modules.processing.pipeline.graph.MetricsCollector") as mock_metrics:
            mock_counter = MagicMock()
            mock_metrics.content_hash_cache_hit_total.labels.return_value = mock_counter
            await Pipeline._check_content_hash_cache(pipeline, [article])
            mock_metrics.content_hash_cache_hit_total.labels.assert_called_with(hit="miss")
