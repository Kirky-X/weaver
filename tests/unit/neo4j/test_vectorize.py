# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for VectorizeNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.collector.models import ArticleRaw
from modules.pipeline.nodes.vectorize import VectorizeNode
from modules.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return ArticleRaw(
        url="https://example.com/vectorize-test",
        title="Test Article for Vectorization",
        body="This is the body content for vectorization testing. "
        "It contains multiple sentences to test embedding generation.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


class TestVectorizeNodeBasic:
    """Basic functionality tests for VectorizeNode."""

    @pytest.mark.asyncio
    async def test_vectorize_successful(self, mock_llm, sample_raw):
        """Test successful vectorization."""
        mock_embedding = [0.1] * 1536
        mock_llm.embed = AsyncMock(return_value=[mock_embedding])

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify vectors are set
        assert "vectors" in result
        assert "content" in result["vectors"]
        assert result["vectors"]["content"] == mock_embedding

    @pytest.mark.asyncio
    async def test_vectorize_calls_embed_correctly(self, mock_llm, sample_raw):
        """Test that vectorize calls embed with correct text."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536])

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Test Title", "body": "Test Body"}

        await node.execute(state)

        # Verify embed was called
        mock_llm.embed.assert_called_once()
        call_args = mock_llm.embed.call_args

        # embed(label, [text]) — second positional arg is the text list
        text = call_args[0][1][0]
        assert "Test Title" in text
        assert "Test Body" in text

    @pytest.mark.asyncio
    async def test_vectorize_truncates_body(self, mock_llm):
        """Test that vectorize truncates body to 2000 chars."""
        long_body = "A" * 3000
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536])

        raw = ArticleRaw(
            url="https://example.com/long",
            title="Test",
            body=long_body,
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Test", "body": long_body}

        await node.execute(state)

        # Verify body was truncated
        call_args = mock_llm.embed.call_args
        text = call_args[0][1][0]
        # Title (4) + newline (1) + body[:2000] (2000) = 2005 chars max
        assert len(text) <= 2005


class TestVectorizeNodeEdgeCases:
    """Edge case tests for VectorizeNode."""

    @pytest.mark.asyncio
    async def test_vectorize_skips_terminal_state(self, mock_llm, sample_raw):
        """Test that vectorize skips terminal articles."""
        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should return state unchanged
        assert "vectors" not in result
        mock_llm.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_vectorize_with_short_content(self, mock_llm):
        """Test vectorization with very short content."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536])

        raw = ArticleRaw(
            url="https://example.com/short",
            title="Hi",
            body="OK",
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=raw)
        state["cleaned"] = {"title": "Hi", "body": "OK"}

        result = await node.execute(state)

        assert "vectors" in result
        assert result["vectors"]["content"] is not None

    @pytest.mark.asyncio
    async def test_vectorize_with_empty_body(self, mock_llm, sample_raw):
        """Test vectorization with empty body."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1536])

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": ""}

        result = await node.execute(state)

        # Should still work with title only
        assert "vectors" in result


class TestVectorizeNodeErrorHandling:
    """Error handling tests for VectorizeNode."""

    @pytest.mark.asyncio
    async def test_vectorize_handles_embedding_error(self, mock_llm, sample_raw):
        """Test that vectorize handles embedding errors."""
        mock_llm.embed = AsyncMock(side_effect=Exception("Embedding service unavailable"))

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        # Should raise the exception
        with pytest.raises(Exception, match="Embedding service unavailable"):
            await node.execute(state)

    @pytest.mark.asyncio
    async def test_vectorize_handles_timeout(self, mock_llm, sample_raw):
        """Test that vectorize handles timeout errors."""
        import asyncio

        mock_llm.embed = AsyncMock(side_effect=TimeoutError("Request timeout"))

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        # Should raise the timeout error
        with pytest.raises(asyncio.TimeoutError):
            await node.execute(state)

    @pytest.mark.asyncio
    async def test_vectorize_handles_empty_embedding_result(self, mock_llm, sample_raw):
        """Test that vectorize handles empty embedding result."""
        mock_llm.embed = AsyncMock(return_value=[])

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        # Should raise index error or handle gracefully
        with pytest.raises((IndexError, KeyError)):
            await node.execute(state)


class TestVectorizeNodeIntegration:
    """Integration tests for VectorizeNode."""

    @pytest.mark.asyncio
    async def test_vectorize_preserves_state(self, mock_llm, sample_raw):
        """Test that vectorize preserves existing state fields."""
        mock_llm.embed = AsyncMock(return_value=[[0.2] * 1536])

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        state["is_news"] = True
        state["existing_field"] = "preserved"

        result = await node.execute(state)

        # Verify existing fields are preserved
        assert result["is_news"] is True
        assert result["existing_field"] == "preserved"
        # And vectors are added
        assert "vectors" in result
        assert result["vectors"]["content"] == [0.2] * 1536

    @pytest.mark.asyncio
    async def test_vectorize_with_different_embedding_dimensions(self, mock_llm, sample_raw):
        """Test vectorization with different embedding dimensions."""
        # Test with smaller embedding
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 512])

        node = VectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert len(result["vectors"]["content"]) == 512

    @pytest.mark.asyncio
    async def test_vectorize_multiple_calls_consistency(self, mock_llm, sample_raw):
        """Test that multiple vectorization calls are consistent."""
        embedding1 = [0.1] * 1536
        embedding2 = [0.2] * 1536
        mock_llm.embed = AsyncMock(side_effect=[[embedding1], [embedding2]])

        node = VectorizeNode(mock_llm)

        # First call
        state1 = PipelineState(raw=sample_raw)
        state1["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result1 = await node.execute(state1)

        # Second call
        state2 = PipelineState(raw=sample_raw)
        state2["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result2 = await node.execute(state2)

        # Each call should produce consistent structure
        assert "vectors" in result1
        assert "vectors" in result2
        # But embeddings may differ (different mock values)
        assert result1["vectors"]["content"] == embedding1
        assert result2["vectors"]["content"] == embedding2
