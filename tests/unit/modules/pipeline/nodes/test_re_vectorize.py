# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ReVectorizeNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from modules.ingestion.domain.models import ArticleRaw
from modules.pipeline.nodes.re_vectorize import ReVectorizeNode
from modules.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return ArticleRaw(
        url="https://example.com/test-article",
        title="Test Article Title",
        body="Test article body content for embedding.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


class TestReVectorizeNodeBasic:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_successful_execution(self, mock_llm, sample_raw):
        """Should generate vectors and update state."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm, model_id="text-embedding-3-large")
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert "vectors" in result
        assert "title" in result["vectors"]
        assert "content" in result["vectors"]
        assert result["vectors"]["model_id"] == "text-embedding-3-large"

    @pytest.mark.asyncio
    async def test_calls_embed_with_correct_texts(self, mock_llm, sample_raw):
        """Should call embed with title and content."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Test Title", "body": "Test body content"}

        await node.execute(state)

        call_args = mock_llm.embed.call_args
        texts = call_args[0][1]
        assert texts[0] == "Test Title"
        assert texts[1] == "Test Title\nTest body content"[:2000]

    @pytest.mark.asyncio
    async def test_custom_model_id(self, mock_llm, sample_raw):
        """Should use custom model_id."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm, model_id="qwen3-embedding:0.6b")
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["vectors"]["model_id"] == "qwen3-embedding:0.6b"


class TestReVectorizeNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, mock_llm, sample_raw):
        """Should skip processing if terminal flag is set."""
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        mock_llm.embed.assert_not_called()
        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_skips_merged_articles(self, mock_llm, sample_raw):
        """Should skip processing for merged articles."""
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        mock_llm.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_truncates_long_body(self, mock_llm, sample_raw):
        """Should truncate body for content embedding."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "A" * 5000}

        await node.execute(state)

        call_args = mock_llm.embed.call_args
        texts = call_args[0][1]
        # Content text = title + body[:2000]
        assert len(texts[1]) <= len("Title") + 2000 + 1  # title + \n + truncated body

    @pytest.mark.asyncio
    async def test_handles_empty_title(self, mock_llm, sample_raw):
        """Should handle empty title."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "", "body": "Body content"}

        await node.execute(state)

        mock_llm.embed.assert_called()


class TestReVectorizeNodeErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_propagates_embed_error(self, mock_llm, sample_raw):
        """Should propagate embedding errors."""
        mock_llm.embed = AsyncMock(side_effect=Exception("Embedding failed"))
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        with pytest.raises(Exception, match="Embedding failed"):
            await node.execute(state)

    @pytest.mark.asyncio
    async def test_handles_timeout(self, mock_llm, sample_raw):
        """Should propagate timeout errors."""
        mock_llm.embed = AsyncMock(side_effect=TimeoutError("Timeout"))
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        with pytest.raises(TimeoutError):
            await node.execute(state)


class TestReVectorizeNodeIntegration:
    """Integration-like tests."""

    @pytest.mark.asyncio
    async def test_preserves_existing_state(self, mock_llm, sample_raw):
        """Should preserve existing state fields."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "tech"
        state["quality_score"] = 0.85

        result = await node.execute(state)

        assert result["category"] == "tech"
        assert result["quality_score"] == 0.85
        assert "vectors" in result

    @pytest.mark.asyncio
    async def test_overwrites_existing_vectors(self, mock_llm, sample_raw):
        """Should overwrite existing vectors."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["vectors"] = {"title": [0.5] * 512, "content": [0.6] * 512, "model_id": "old"}

        result = await node.execute(state)

        assert result["vectors"]["model_id"] == "text-embedding-3-large"
        assert result["vectors"]["title"] == [0.1] * 1024

    @pytest.mark.asyncio
    async def test_vector_dimensions(self, mock_llm, sample_raw):
        """Should return correct vector dimensions."""
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
        node = ReVectorizeNode(mock_llm)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert len(result["vectors"]["title"]) == 1024
        assert len(result["vectors"]["content"]) == 1024
