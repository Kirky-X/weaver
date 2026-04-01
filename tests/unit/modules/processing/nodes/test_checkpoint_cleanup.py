# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for processing CheckpointCleanupNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.checkpoint_cleanup import CheckpointCleanupNode
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return ArticleRaw(
        url="https://example.com/test-article",
        title="Test Article",
        body="Test article body content.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = MagicMock()
    redis.client = MagicMock()
    redis.client.delete = AsyncMock(return_value=1)
    return redis


class TestCheckpointCleanupNodeInit:
    """Tests for CheckpointCleanupNode initialization."""

    def test_init_with_redis(self, mock_redis):
        """Test initialization with Redis client."""
        node = CheckpointCleanupNode(redis_client=mock_redis)
        assert node._redis == mock_redis

    def test_init_without_redis(self):
        """Test initialization without Redis client."""
        node = CheckpointCleanupNode(redis_client=None)
        assert node._redis is None


class TestCheckpointCleanupNodeExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_execute_with_redis(self, mock_redis, sample_raw):
        """Test execute deletes checkpoint when Redis is available."""
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Should call delete on Redis
        mock_redis.client.delete.assert_called_once()
        # Should return state unchanged
        assert result == state

    @pytest.mark.asyncio
    async def test_execute_without_redis(self, sample_raw):
        """Test execute skips cleanup when Redis is not available."""
        node = CheckpointCleanupNode(redis_client=None)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Should return state unchanged
        assert result == state

    @pytest.mark.asyncio
    async def test_execute_skips_terminal_state(self, mock_redis, sample_raw):
        """Test execute skips terminal states."""
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True

        result = await node.execute(state)

        # Should not call delete
        mock_redis.client.delete.assert_not_called()
        # Should return state unchanged
        assert result == state

    @pytest.mark.asyncio
    async def test_execute_generates_correct_key(self, mock_redis, sample_raw):
        """Test that correct Redis key is generated."""
        import hashlib

        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)

        await node.execute(state)

        # Verify the key format
        url_hash = hashlib.sha256(sample_raw.url.encode()).hexdigest()[:16]
        expected_key = f"{CheckpointCleanupNode.CHECKPOINT_KEY_PREFIX}:{url_hash}"

        mock_redis.client.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_execute_handles_redis_error(self, mock_redis, sample_raw):
        """Test execute handles Redis errors gracefully."""
        mock_redis.client.delete = AsyncMock(side_effect=Exception("Redis connection failed"))

        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)

        # Should not raise exception
        result = await node.execute(state)

        # Should return state unchanged
        assert result == state


class TestCheckpointCleanupNodeKeyFormat:
    """Tests for Redis key format."""

    def test_checkpoint_key_prefix(self):
        """Test checkpoint key prefix constant."""
        assert CheckpointCleanupNode.CHECKPOINT_KEY_PREFIX == "langgraph:checkpoint"

    @pytest.mark.asyncio
    async def test_different_urls_generate_different_keys(self, mock_redis):
        """Test that different URLs generate different keys."""
        import hashlib

        node = CheckpointCleanupNode(redis_client=mock_redis)

        raw1 = ArticleRaw(
            url="https://example.com/article-1",
            title="Article 1",
            body="Body 1",
            source="test",
            source_host="example.com",
        )
        state1 = PipelineState(raw=raw1)
        await node.execute(state1)

        raw2 = ArticleRaw(
            url="https://example.com/article-2",
            title="Article 2",
            body="Body 2",
            source="test",
            source_host="example.com",
        )
        state2 = PipelineState(raw=raw2)
        await node.execute(state2)

        # Get the keys from the two delete calls
        calls = mock_redis.client.delete.call_args_list
        key1 = calls[0][0][0]
        key2 = calls[1][0][0]

        # Keys should be different
        assert key1 != key2


class TestCheckpointCleanupNodeIntegration:
    """Integration tests for CheckpointCleanupNode."""

    @pytest.mark.asyncio
    async def test_execute_preserves_state_fields(self, mock_redis, sample_raw):
        """Test that execute preserves all state fields."""
        node = CheckpointCleanupNode(redis_client=mock_redis)
        state = PipelineState(raw=sample_raw)
        state["is_news"] = True
        state["category"] = "科技"
        state["score"] = 0.85
        state["existing_field"] = "preserved_value"

        result = await node.execute(state)

        # All fields should be preserved
        assert result["is_news"] is True
        assert result["category"] == "科技"
        assert result["score"] == 0.85
        assert result["existing_field"] == "preserved_value"

    @pytest.mark.asyncio
    async def test_execute_with_various_url_formats(self, mock_redis):
        """Test execute handles various URL formats."""
        node = CheckpointCleanupNode(redis_client=mock_redis)

        test_urls = [
            "https://example.com/simple",
            "https://example.com/path/with/slashes/article",
            "https://example.com/article?query=param&other=value",
            "https://subdomain.example.com/path#fragment",
        ]

        for url in test_urls:
            raw = ArticleRaw(
                url=url,
                title="Test",
                body="Body",
                source="test",
                source_host="example.com",
            )
            state = PipelineState(raw=raw)
            result = await node.execute(state)
            assert result == state

        # All URLs should have triggered a delete call
        assert mock_redis.client.delete.call_count == len(test_urls)
