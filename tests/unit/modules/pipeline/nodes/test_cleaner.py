# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CleanerNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import CleanerContent, CleanerEntity, CleanerOutput
from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.cleaner import CleanerNode
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return ArticleRaw(
        url="https://example.com/test-article",
        title="Original Title",
        body="Original body content with some noise.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_budget():
    budget = MagicMock()
    budget.truncate = MagicMock(
        side_effect=lambda text, cp: text[:2000] if len(text) > 2000 else text
    )
    return budget


@pytest.fixture
def mock_prompt_loader():
    loader = MagicMock()
    loader.get_version = MagicMock(return_value="2.0.0")
    return loader


@pytest.fixture
def sample_cleaner_output():
    return CleanerOutput(
        content=CleanerContent(
            title="Cleaned Title",
            subtitle="Subtitle",
            summary="Article summary",
            body="Cleaned body content",
        ),
        tags=["tech", "ai"],
        entities=[
            CleanerEntity(name="Company X", type="ORG", description="Tech company"),
            CleanerEntity(name="Person Y", type="PERSON", description="CEO"),
        ],
        publish_time="2026-01-15",
        author="John Doe",
    )


class TestCleanerNodeBasic:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_successful_execution(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should clean content and update state."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "cleaned" in result
        assert result["cleaned"]["title"] == "Cleaned Title"
        assert result["cleaned"]["body"] == "Cleaned body content"
        assert result["tags"] == ["tech", "ai"]

    @pytest.mark.asyncio
    async def test_sets_prompt_version(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should record prompt version in state."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["cleaner"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_truncates_long_body(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should truncate long body text."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["raw"].body = "A" * 5000  # Long body

        await node.execute(state)

        mock_budget.truncate.assert_called()

    @pytest.mark.asyncio
    async def test_processes_entities(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should process entities from cleaner output."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "cleaner_entities" in result
        assert len(result["cleaner_entities"]) == 2
        assert result["cleaner_entities"][0]["name"] == "Company X"

    @pytest.mark.asyncio
    async def test_includes_llm_publish_time(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should include LLM-parsed publish_time if available."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "llm_publish_time" in result["cleaned"]
        assert result["cleaned"]["llm_publish_time"] == "2026-01-15"

    @pytest.mark.asyncio
    async def test_includes_author(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should include author if available."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "author" in result["cleaned"]
        assert result["cleaned"]["author"] == "John Doe"


class TestCleanerNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should skip processing if terminal flag is set."""
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True

        result = await node.execute(state)

        mock_llm.call_at.assert_not_called()
        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_handles_empty_tags(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should handle empty tags list."""
        output = CleanerOutput(
            content=CleanerContent(
                title="Title",
                subtitle="",
                summary="",
                body="Body",
            ),
            tags=[],
            entities=[],
        )
        mock_llm.call_at = AsyncMock(return_value=output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["tags"] == []

    @pytest.mark.asyncio
    async def test_handles_no_publish_time(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should not set llm_publish_time if not in output."""
        output = CleanerOutput(
            content=CleanerContent(
                title="Title",
                subtitle="",
                summary="",
                body="Body",
            ),
            tags=["tech"],
            entities=[],
            publish_time=None,
        )
        mock_llm.call_at = AsyncMock(return_value=output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "llm_publish_time" not in result["cleaned"]

    @pytest.mark.asyncio
    async def test_handles_no_author(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should not set author if not in output."""
        output = CleanerOutput(
            content=CleanerContent(
                title="Title",
                subtitle="",
                summary="",
                body="Body",
            ),
            tags=["tech"],
            entities=[],
            author=None,
        )
        mock_llm.call_at = AsyncMock(return_value=output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "author" not in result["cleaned"]

    @pytest.mark.asyncio
    async def test_preserves_source_host(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should preserve source_host in cleaned output."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["cleaned"]["source_host"] == "example.com"


class TestCleanerNodeErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should use original content on LLM failure."""
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "cleaned" in result
        assert result["cleaned"]["title"] == "Original Title"
        assert result["cleaned"]["body"] == "Original body content with some noise."
        assert result["tags"] == []
        assert result["cleaner_entities"] == []

    @pytest.mark.asyncio
    async def test_handles_timeout(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should handle timeout errors."""
        mock_llm.call_at = AsyncMock(side_effect=TimeoutError("Request timeout"))
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "cleaned" in result
        assert result["tags"] == []

    @pytest.mark.asyncio
    async def test_handles_invalid_response(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should handle invalid response format."""
        mock_llm.call_at = AsyncMock(side_effect=ValueError("Invalid format"))
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "cleaned" in result

    @pytest.mark.asyncio
    async def test_preserves_publish_time_on_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should preserve original publish_time on error."""
        mock_llm.call_at = AsyncMock(side_effect=Exception("Error"))
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["cleaned"]["publish_time"] == sample_raw.publish_time


class TestCleanerNodeIntegration:
    """Integration-like tests."""

    @pytest.mark.asyncio
    async def test_preserves_existing_state(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should preserve existing state fields."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["is_news"] = True
        state["article_id"] = "test-123"

        result = await node.execute(state)

        assert result["is_news"] is True
        assert result["article_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_passes_article_id_to_llm(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw, sample_cleaner_output
    ):
        """Should pass article_id to LLM call."""
        mock_llm.call_at = AsyncMock(return_value=sample_cleaner_output)
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["article_id"] = "article-456"
        state["task_id"] = "task-789"

        await node.execute(state)

        call_args = mock_llm.call_at.call_args
        input_data = call_args[0][1]
        assert input_data["article_id"] == "article-456"
        assert input_data["task_id"] == "task-789"
