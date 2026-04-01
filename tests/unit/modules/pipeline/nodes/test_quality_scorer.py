# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for QualityScorerNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import QualityScorerOutput
from modules.ingestion.domain.models import ArticleRaw
from modules.pipeline.nodes.quality_scorer import QualityScorerNode
from modules.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return ArticleRaw(
        url="https://example.com/test-article",
        title="Test Article Title",
        body="Test article body content.",
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
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


class TestQualityScorerNodeBasic:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_successful_execution(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should score article and update state."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.85))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert "quality_score" in result
        assert result["quality_score"] == 0.85

    @pytest.mark.asyncio
    async def test_sets_prompt_version(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should record prompt version in state."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.7))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["quality_scorer"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_truncates_long_body(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should truncate long body text."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.5))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "A" * 5000}

        await node.execute(state)

        mock_budget.truncate.assert_called()

    @pytest.mark.asyncio
    async def test_default_score_on_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should use default score 0.5 on LLM error."""
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM error"))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.5


class TestQualityScorerNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should skip processing if terminal flag is set."""
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        mock_llm.call_at.assert_not_called()
        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_skips_merged_articles(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should skip processing for merged articles."""
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_zero_score(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should handle score of 0.0."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.0))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.0

    @pytest.mark.asyncio
    async def test_handles_max_score(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should handle score of 1.0."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=1.0))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 1.0

    @pytest.mark.asyncio
    async def test_handles_low_score(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should handle very low scores."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.15))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.15


class TestQualityScorerNodeErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_handles_timeout(self, mock_llm, mock_budget, mock_prompt_loader, sample_raw):
        """Should use default score on timeout."""
        mock_llm.call_at = AsyncMock(side_effect=TimeoutError("Request timeout"))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_handles_invalid_response(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should use default score on invalid response."""
        mock_llm.call_at = AsyncMock(side_effect=ValueError("Invalid format"))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.5

    @pytest.mark.asyncio
    async def test_handles_connection_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should use default score on connection error."""
        mock_llm.call_at = AsyncMock(side_effect=ConnectionError("Connection failed"))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}

        result = await node.execute(state)

        assert result["quality_score"] == 0.5


class TestQualityScorerNodeIntegration:
    """Integration-like tests."""

    @pytest.mark.asyncio
    async def test_preserves_existing_state(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should preserve existing state fields."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.75))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "tech"
        state["article_id"] = "test-123"

        result = await node.execute(state)

        assert result["category"] == "tech"
        assert result["article_id"] == "test-123"
        assert result["quality_score"] == 0.75

    @pytest.mark.asyncio
    async def test_passes_article_id_to_llm(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should pass article_id and task_id to LLM call."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.8))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["article_id"] = "article-456"
        state["task_id"] = "task-789"

        await node.execute(state)

        call_args = mock_llm.call_at.call_args
        input_data = call_args[0][1]
        assert input_data["article_id"] == "article-456"
        assert input_data["task_id"] == "task-789"

    @pytest.mark.asyncio
    async def test_does_not_overwrite_existing_prompt_versions(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Should merge with existing prompt_versions."""
        mock_llm.call_at = AsyncMock(return_value=QualityScorerOutput(score=0.7))
        node = QualityScorerNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["prompt_versions"] = {"cleaner": "1.5.0"}

        result = await node.execute(state)

        assert result["prompt_versions"]["cleaner"] == "1.5.0"
        assert result["prompt_versions"]["quality_scorer"] == "1.0.0"
