# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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


def _make_snapshot(**overrides):
    """Build a valid v2 cache snapshot (matches pipeline state schema)."""
    snapshot = {
        "_schema_version": 2,
        "cleaned": {"title": "Cleaned", "body": "Cleaned body"},
        "category": "politics",
        "quality_score": 0.85,
    }
    snapshot.update(overrides)
    return snapshot


def _compute_content_hash(title: str, body: str) -> str:
    """Compute content hash matching service logic."""
    content = f"{title}{body}"
    return hashlib.sha256(content.encode()).hexdigest()


class TestContentHashCacheHit:
    """Test cache hit behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_full_snapshot(self):
        """A valid v2 snapshot is returned so Phase 1/3 can be skipped."""
        article = _make_raw_article()
        content_hash = _compute_content_hash(article.title, article.body)

        cache_client = AsyncMock()
        cache_client.mget.return_value = [json.dumps(_make_snapshot())]

        service = ContentHashCacheService(cache_client=cache_client)

        result = await service.check([article])

        cache_client.mget.assert_called_once()
        called_keys = cache_client.mget.call_args[0][0]
        assert called_keys[0] == f"content_hash:{content_hash}"

        assert result[0] is not None
        assert result[0]["category"] == "politics"
        assert result[0]["cleaned"]["title"] == "Cleaned"

    @pytest.mark.asyncio
    async def test_cache_hit_batch(self):
        """Batch of articles with all cache hits."""
        articles = [
            _make_raw_article("Title 1", "Body 1"),
            _make_raw_article("Title 2", "Body 2"),
        ]

        cache_client = AsyncMock()
        cache_client.mget.return_value = [
            json.dumps(_make_snapshot(category="politics")),
            json.dumps(_make_snapshot(category="economy")),
        ]

        service = ContentHashCacheService(cache_client=cache_client)

        result = await service.check(articles)

        assert len(result) == 2
        assert result[0]["category"] == "politics"
        assert result[1]["category"] == "economy"

    @pytest.mark.asyncio
    async def test_legacy_schema_entry_is_a_miss(self):
        """Entries written by the old flat-key schema must not be trusted."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        # Old v1 snapshot: flat keys, no _schema_version, no "cleaned".
        cache_client.mget.return_value = [
            json.dumps({"title": "T", "body": "B", "category": "politics"})
        ]

        service = ContentHashCacheService(cache_client=cache_client)

        result = await service.check([article])

        assert result[0] is None

    @pytest.mark.asyncio
    async def test_future_schema_version_is_a_miss(self):
        """Snapshots from a newer schema version are treated as misses."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        cache_client.mget.return_value = [json.dumps(_make_snapshot(_schema_version=99))]

        service = ContentHashCacheService(cache_client=cache_client)

        result = await service.check([article])

        assert result[0] is None


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
    async def test_write_full_snapshot_to_cache(self):
        """Processing results are cached as a full snapshot with correct TTL."""
        article = _make_raw_article()
        content_hash = _compute_content_hash(article.title, article.body)

        cache_client = AsyncMock()

        service = ContentHashCacheService(cache_client=cache_client)

        state = PipelineState(raw=article)
        state["cleaned"] = {"title": "Cleaned", "body": "Cleaned body"}
        state["category"] = "politics"
        state["quality_score"] = 0.85
        state["sentiment"] = {"sentiment_score": 0.5, "sentiment": "neutral"}
        state["credibility"] = {"score": 0.9}
        state["vectors"] = {"title": [0.1], "content": [0.2], "model_id": "m1"}
        state["article_id"] = "should-not-be-cached"
        state["task_id"] = "also-not-cached"
        state["_cache_hit"] = False

        await service.write(state)

        cache_client.set.assert_called_once()
        call_args = cache_client.set.call_args
        key = call_args[0][0]
        value = json.loads(call_args[0][1])
        ttl = call_args[1]["ex"]

        assert key == f"content_hash:{content_hash}"
        assert ttl == 604800  # 7 days

        # Snapshot mirrors the mapper-consumed schema
        assert value["_schema_version"] == 2
        assert value["cleaned"]["title"] == "Cleaned"
        assert value["category"] == "politics"
        assert value["sentiment"]["sentiment_score"] == 0.5
        assert value["credibility"]["score"] == 0.9
        assert value["vectors"]["model_id"] == "m1"
        # Per-article identity and private markers are never cached
        assert "raw" not in value
        assert "article_id" not in value
        assert "task_id" not in value
        assert "_cache_hit" not in value

    @pytest.mark.asyncio
    async def test_written_snapshot_round_trips_through_check(self):
        """A snapshot written by write() is accepted by check() (v2)."""
        article = _make_raw_article()

        cache_client = AsyncMock()
        service = ContentHashCacheService(cache_client=cache_client)

        state = PipelineState(raw=article)
        state["cleaned"] = {"title": "Cleaned", "body": "Body"}
        state["category"] = "tech"
        await service.write(state)

        # Feed the written payload back through check()
        cached_payload = cache_client.set.call_args[0][1]
        cache_client.mget.return_value = [cached_payload]
        result = await service.check([article])

        assert result[0] is not None
        assert result[0]["category"] == "tech"

    @pytest.mark.asyncio
    async def test_write_batch_to_cache(self):
        """Batch write to cache after processing."""
        articles = [
            _make_raw_article("Title 1", "Body 1"),
            _make_raw_article("Title 2", "Body 2"),
        ]

        cache_client = MagicMock()
        pipe = MagicMock()
        pipe.set = MagicMock(return_value=None)
        pipe.execute = AsyncMock(return_value=[])
        pipeline_cm = MagicMock()
        pipeline_cm.__aenter__ = AsyncMock(return_value=pipe)
        pipeline_cm.__aexit__ = AsyncMock(return_value=False)
        cache_client.pipeline = MagicMock(return_value=pipeline_cm)

        service = ContentHashCacheService(cache_client=cache_client)

        states = []
        for article in articles:
            state = PipelineState(raw=article)
            state["category"] = "politics"
            states.append(state)

        await service.write_batch(states)

        # T009: batch writes go through one pipeline round trip
        assert pipe.set.call_count == 2
        pipe.execute.assert_awaited_once()
        assert cache_client.set.call_count == 0


class TestContentHashCacheBatchPipeline:
    """T009: write_batch serializes off-loop and writes via a single pipeline."""

    @staticmethod
    def _make_states(count: int) -> list[PipelineState]:
        return [
            PipelineState(raw=_make_raw_article(f"Title {i}", f"Body {i}"))
            for i in range(count)
        ]

    @staticmethod
    def _pipeline_client():
        cache_client = MagicMock()
        pipe = MagicMock()
        pipe.set = MagicMock(return_value=None)
        pipe.execute = AsyncMock(return_value=[])
        pipeline_cm = MagicMock()
        pipeline_cm.__aenter__ = AsyncMock(return_value=pipe)
        pipeline_cm.__aexit__ = AsyncMock(return_value=False)
        cache_client.pipeline = MagicMock(return_value=pipeline_cm)
        return cache_client, pipe

    @pytest.mark.asyncio
    async def test_write_batch_single_pipeline_round_trip(self):
        cache_client, pipe = self._pipeline_client()
        service = ContentHashCacheService(cache_client=cache_client)

        await service.write_batch(self._make_states(3))

        assert pipe.set.call_count == 3
        pipe.execute.assert_awaited_once()
        assert cache_client.set.call_count == 0

    @pytest.mark.asyncio
    async def test_write_batch_ttl_applied_per_key(self):
        cache_client, pipe = self._pipeline_client()
        service = ContentHashCacheService(cache_client=cache_client)

        await service.write_batch(self._make_states(2))

        for call in pipe.set.call_args_list:
            assert call.kwargs.get("ex") == 604800

    @pytest.mark.asyncio
    async def test_write_batch_serializes_off_event_loop(self):
        import threading

        cache_client, _pipe = self._pipeline_client()
        service = ContentHashCacheService(cache_client=cache_client)
        states = self._make_states(2)

        threads_used: list[str] = []
        real_dumps = json.dumps

        def spy_dumps(*args, **kwargs):
            threads_used.append(threading.current_thread().name)
            return real_dumps(*args, **kwargs)

        with patch(
            "modules.processing.pipeline.content_hash_cache.json.dumps",
            side_effect=spy_dumps,
        ):
            await service.write_batch(states)

        main_thread = threading.main_thread().name
        assert threads_used, "snapshot serialization did not run"
        assert all(name != main_thread for name in threads_used)

    @pytest.mark.asyncio
    async def test_write_batch_pipeline_failure_is_swallowed_with_warning(self):
        cache_client, pipe = self._pipeline_client()
        pipe.execute = AsyncMock(side_effect=RuntimeError("redis down"))
        service = ContentHashCacheService(cache_client=cache_client)

        # Must not raise (cache is best-effort)
        await service.write_batch(self._make_states(1))


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
        cache_client.mget.return_value = [json.dumps(_make_snapshot())]

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
