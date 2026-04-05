# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for processing CleanerNode."""

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
        url="https://example.com/article",
        title="Test Title",
        body="Test body content with <b>HTML</b> tags and extra whitespace.",
        source="test",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_budget():
    budget = MagicMock()
    budget.truncate = MagicMock(return_value="truncated text")
    return budget


@pytest.fixture
def mock_prompt_loader():
    loader = MagicMock()
    loader.get_version = MagicMock(return_value="2.0.0")
    return loader


def _make_cleaner_output(
    title="Cleaned Title",
    subtitle="",
    summary="Summary text",
    body="Cleaned body content.",
    publish_time=None,
    author=None,
    tags=None,
    entities=None,
):
    """Helper to create CleanerOutput."""
    return CleanerOutput(
        content=CleanerContent(
            title=title,
            subtitle=subtitle,
            summary=summary,
            body=body,
        ),
        publish_time=publish_time,
        author=author,
        tags=tags or [],
        entities=entities or [],
    )


class TestCleanerNodeBasic:
    @pytest.mark.asyncio
    async def test_successful_cleaning(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output())

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "cleaned" in result
        assert result["cleaned"]["title"] == "Cleaned Title"
        assert result["cleaned"]["body"] == "Cleaned body content."
        assert result["cleaned"]["summary"] == "Summary text"
        assert result["cleaned"]["publish_time"] == sample_raw.publish_time
        assert result["cleaned"]["source_host"] == "example.com"

    @pytest.mark.asyncio
    async def test_sets_prompt_version(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output())

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["cleaner"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_uses_truncated_body(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output())

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        await node.execute(state)

        mock_budget.truncate.assert_called_once()

    @pytest.mark.asyncio
    async def test_extracts_tags(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output(tags=["AI", "technology"]))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["tags"] == ["AI", "technology"]

    @pytest.mark.asyncio
    async def test_extracts_entities(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_entity = CleanerEntity(name="OpenAI", type="ORG", description="AI company")
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output(entities=[mock_entity]))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert len(result["cleaner_entities"]) == 1
        assert result["cleaner_entities"][0]["name"] == "OpenAI"

    @pytest.mark.asyncio
    async def test_llm_publish_time(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(
            return_value=_make_cleaner_output(publish_time="2025-01-15T10:00:00Z")
        )

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "llm_publish_time" in result["cleaned"]
        assert result["cleaned"]["llm_publish_time"] == "2025-01-15T10:00:00Z"

    @pytest.mark.asyncio
    async def test_author_from_llm(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output(author="John Doe"))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["cleaned"]["author"] == "John Doe"


class TestCleanerNodeEdgeCases:
    @pytest.mark.asyncio
    async def test_skips_terminal(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True

        result = await node.execute(state)

        assert "cleaned" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_publish_time(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output(publish_time=None))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "llm_publish_time" not in result["cleaned"]

    @pytest.mark.asyncio
    async def test_no_author(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output(author=None))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "author" not in result["cleaned"]


class TestCleanerNodeErrorHandling:
    @pytest.mark.asyncio
    async def test_handles_llm_error(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Should use original content as fallback
        assert "cleaned" in result
        assert result["cleaned"]["title"] == sample_raw.title
        assert result["cleaned"]["body"] == sample_raw.body
        assert result["cleaned"]["publish_time"] == sample_raw.publish_time
        assert result["cleaned"]["source_host"] == "example.com"
        assert result["tags"] == []
        assert result["cleaner_entities"] == []

    @pytest.mark.asyncio
    async def test_handles_timeout(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(side_effect=TimeoutError("Request timeout"))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["cleaned"]["title"] == sample_raw.title

    @pytest.mark.asyncio
    async def test_handles_value_error(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(side_effect=ValueError("Invalid response"))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["cleaned"]["body"] == sample_raw.body


class TestCleanerNodeDegradation:
    @pytest.mark.asyncio
    async def test_marks_degraded_fields_on_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Check degraded fields are marked
        assert "degraded_fields" in result
        assert "cleaned.title" in result["degraded_fields"]
        assert "cleaned.body" in result["degraded_fields"]
        assert "tags" in result["degraded_fields"]
        assert "cleaner_entities" in result["degraded_fields"]

        # Check degradation reasons
        assert "degradation_reasons" in result
        assert "cleaned.title" in result["degradation_reasons"]
        assert "LLM cleaner failed" in result["degradation_reasons"]["cleaned.title"]

    @pytest.mark.asyncio
    async def test_no_degraded_fields_on_success(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output())

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # No degraded fields when successful
        assert not result.get("degraded_fields")
        assert not result.get("degradation_reasons")


class TestCleanerNodePreservesState:
    @pytest.mark.asyncio
    async def test_preserves_existing_fields(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output())

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["is_news"] = True
        state["existing_field"] = "preserved"

        result = await node.execute(state)

        assert result["is_news"] is True
        assert result["existing_field"] == "preserved"

    @pytest.mark.asyncio
    async def test_no_publish_time_in_raw(self, mock_llm, mock_budget, mock_prompt_loader):
        raw = ArticleRaw(
            url="https://example.com/article",
            title="Test",
            body="Body",
            source="test",
            source_host="example.com",
        )
        mock_llm.call_at = AsyncMock(return_value=_make_cleaner_output())

        node = CleanerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=raw)

        result = await node.execute(state)

        assert result["cleaned"]["publish_time"] is None
