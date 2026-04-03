# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CheckpointCleanupNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.checkpoint_cleanup import CheckpointCleanupNode
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return ArticleRaw(
        url="https://example.com/test-article",
        title="Test Article",
        body="Test body content.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = MagicMock()
    redis.client = MagicMock()
    redis.client.delete = AsyncMock()
    return redis


class TestCheckpointCleanupNodeBasic:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, sample_raw):
        """Should skip cleanup if terminal flag is set."""
        node = CheckpointCleanupNode()
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True

        result = await node.execute(state)

        assert result["terminal"] is True
        # State should be unchanged

    @pytest.mark.asyncio
    async def test_skips_without_redis(self, sample_raw):
        """Should skip cleanup if no Redis client."""
        node = CheckpointCleanupNode(redis_client=None)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "raw" in result
        # No error should occur

    @pytest.mark.asyncio
    async def test_cleans_checkpoint_with_redis(self, sample_raw, mock_redis):
        """Should delete checkpoint key when Redis is available."""
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        mock_redis.client.delete.assert_called_once()
        # Verify key format
        call_args = mock_redis.client.delete.call_args[0][0]
        assert call_args.startswith("langgraph:checkpoint:")

    @pytest.mark.asyncio
    async def test_returns_unchanged_state(self, sample_raw, mock_redis):
        """Should return state unchanged (cleanup is a side effect)."""
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)
        state["article_id"] = "test-123"
        state["cleaned"] = {"title": "Test"}

        result = await node.execute(state)

        assert result["article_id"] == "test-123"
        assert result["cleaned"] == {"title": "Test"}


class TestCheckpointCleanupNodeErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_handles_redis_delete_error(self, sample_raw, mock_redis):
        """Should handle Redis delete errors gracefully."""
        mock_redis.client.delete = AsyncMock(side_effect=Exception("Redis error"))
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Should not raise, state unchanged
        assert "raw" in result

    @pytest.mark.asyncio
    async def test_handles_missing_raw_in_state(self, mock_redis):
        """Should handle missing raw field gracefully."""
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState()

        result = await node.execute(state)

        # Should not raise
        assert result is not None

    @pytest.mark.asyncio
    async def test_handles_connection_error(self, sample_raw, mock_redis):
        """Should handle Redis connection errors."""
        mock_redis.client.delete = AsyncMock(side_effect=ConnectionError("Connection refused"))
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Should not raise
        assert "raw" in result


class TestCheckpointCleanupNodeKeyGeneration:
    """Tests for checkpoint key generation."""

    @pytest.mark.asyncio
    async def test_generates_consistent_key(self, sample_raw, mock_redis):
        """Should generate consistent key for same URL."""
        node = CheckpointCleanupNode(redis_client=mock_redis)

        # Execute twice with same URL
        state1 = PipelineState(raw=sample_raw)
        await node.execute(state1)
        key1 = mock_redis.client.delete.call_args[0][0]

        mock_redis.client.delete.reset_mock()

        state2 = PipelineState(raw=sample_raw)
        await node.execute(state2)
        key2 = mock_redis.client.delete.call_args[0][0]

        assert key1 == key2

    @pytest.mark.asyncio
    async def test_different_urls_generate_different_keys(self, mock_redis):
        """Should generate different keys for different URLs."""
        node = CheckpointCleanupNode(redis_client=mock_redis)

        raw1 = ArticleRaw(
            url="https://example.com/article1",
            title="Article 1",
            body="Body 1",
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        raw2 = ArticleRaw(
            url="https://example.com/article2",
            title="Article 2",
            body="Body 2",
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        state1 = PipelineState(raw=raw1)
        await node.execute(state1)
        key1 = mock_redis.client.delete.call_args[0][0]

        mock_redis.client.delete.reset_mock()

        state2 = PipelineState(raw=raw2)
        await node.execute(state2)
        key2 = mock_redis.client.delete.call_args[0][0]

        assert key1 != key2
