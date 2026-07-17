# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for processing NarrativeGeneratorNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import NarrativeOutput
from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.extraction.narrative_generator import (
    NarrativeGeneratorNode,
)
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return RawArticle(
        url="https://example.com/tech-news",
        title="OpenAI and Microsoft Announce Partnership",
        body=(
            "OpenAI and Microsoft have announced a major partnership deal. "
            "The agreement involves GPT-4 integration into Azure services. "
            "CEO Satya Nadella expressed enthusiasm about the collaboration."
        ),
        source="tech_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_budget():
    """Mock token budget manager."""
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader."""
    loader = MagicMock()
    loader.get = MagicMock(return_value="Narrative synthesis prompt")
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_graph_writer():
    """Mock GraphWriter for NarrativeNode persistence."""
    writer = AsyncMock()
    writer.merge_narrative = AsyncMock(return_value="narrative-uuid-123")
    return writer


@pytest.fixture
def base_state(sample_raw):
    """Create base pipeline state with cleaned content and article_id."""
    state = PipelineState(raw=sample_raw)
    state["article_id"] = "article-uuid-456"
    state["cleaned"] = {
        "title": sample_raw.title,
        "body": sample_raw.body,
    }
    state["entities"] = [
        {"canonical_name": "OpenAI", "type": "组织机构"},
        {"canonical_name": "Microsoft", "type": "组织机构"},
    ]
    return state


class TestNarrativeGeneratorNodeBasic:
    """Basic functionality tests for NarrativeGeneratorNode."""

    @pytest.mark.asyncio
    async def test_narrative_generation_successful(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test successful narrative generation with all 4 dimensions."""
        # Mock LLM returns NarrativeOutput with 4 framing dimensions
        expected_output = NarrativeOutput(
            source_bias="中立",
            frame="经济影响",
            tone="乐观",
            emphasis="合作战略",
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        # Verify LLM called with correct call_point and payload
        mock_llm.call_at.assert_awaited_once()
        call_kwargs = mock_llm.call_at.await_args
        assert call_kwargs.args[0] == CallPoint.NARRATIVE_SYNTHESIS
        payload = call_kwargs.args[1]
        assert payload["title"] == base_state["cleaned"]["title"]
        assert payload["body"] == base_state["cleaned"]["body"]
        assert "entities" in payload
        assert call_kwargs.kwargs["output_model"] == NarrativeOutput

        # Verify graph_writer.merge_narrative called with correct args
        mock_graph_writer.merge_narrative.assert_awaited_once()
        narrative_args = mock_graph_writer.merge_narrative.await_args
        assert narrative_args.kwargs["article_id"] == "article-uuid-456"
        assert narrative_args.kwargs["source_bias"] == "中立"
        assert narrative_args.kwargs["frame"] == "经济影响"
        assert narrative_args.kwargs["tone"] == "乐观"
        assert narrative_args.kwargs["emphasis"] == "合作战略"

        # Verify state updated with narrative data
        assert "narrative" in result
        assert result["narrative"]["source_bias"] == "中立"
        assert result["narrative"]["frame"] == "经济影响"
        assert result["narrative"]["tone"] == "乐观"
        assert result["narrative"]["emphasis"] == "合作战略"
        assert result["narrative"]["narrative_id"] == "narrative-uuid-123"

        # Verify prompt version recorded
        assert result.get("prompt_versions", {}).get("narrative_synthesis") == "1.0.0"

        # Verify no degraded_fields added on success
        assert "narrative" not in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_narrative_skips_terminal_state(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that terminal articles are skipped."""
        base_state["terminal"] = True

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        # LLM and graph_writer should not be called
        mock_llm.call_at.assert_not_called()
        mock_graph_writer.merge_narrative.assert_not_called()
        assert "narrative" not in result

    @pytest.mark.asyncio
    async def test_narrative_skips_merged_state(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that merged articles are skipped."""
        base_state["is_merged"] = True

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_llm.call_at.assert_not_called()
        mock_graph_writer.merge_narrative.assert_not_called()
        assert "narrative" not in result


class TestNarrativeGeneratorNodeDegradation:
    """Failure handling and degradation tests."""

    @pytest.mark.asyncio
    async def test_narrative_llm_all_providers_failed_degrades(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that AllProvidersFailedError marks narrative as degraded."""
        mock_llm.call_at = AsyncMock(side_effect=AllProvidersFailedError("all providers failed"))

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        # LLM was attempted but failed
        mock_llm.call_at.assert_awaited_once()
        # graph_writer should not be called when LLM fails
        mock_graph_writer.merge_narrative.assert_not_called()
        # state["narrative"] should NOT be set
        assert "narrative" not in result
        # degraded_fields should contain "narrative"
        assert "narrative" in result.get("degraded_fields", [])
        # Pipeline should not be blocked (no exception raised)

    @pytest.mark.asyncio
    async def test_narrative_llm_circuit_open_degrades(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that CircuitOpenError marks narrative as degraded."""
        mock_llm.call_at = AsyncMock(side_effect=CircuitOpenError("circuit open"))

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_graph_writer.merge_narrative.assert_not_called()
        assert "narrative" not in result
        assert "narrative" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_narrative_llm_value_error_degrades(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that ValueError (e.g., parse failure) marks narrative as degraded."""
        mock_llm.call_at = AsyncMock(side_effect=ValueError("invalid JSON response"))

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_graph_writer.merge_narrative.assert_not_called()
        assert "narrative" not in result
        assert "narrative" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_narrative_graph_writer_failure_does_not_block_pipeline(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        base_state,
    ):
        """Test that graph_writer failure is logged but does not block pipeline.

        LLM succeeded so narrative data is in state, but persistence failed.
        Per Rule 12 (失败显性化), this should be logged as warning and
        narrative marked as degraded (because the data isn't persisted).
        """
        expected_output = NarrativeOutput(
            source_bias="中立",
            frame="经济影响",
            tone="乐观",
            emphasis="合作战略",
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        failing_graph_writer = AsyncMock()
        failing_graph_writer.merge_narrative = AsyncMock(
            side_effect=RuntimeError("graph db connection lost")
        )

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=failing_graph_writer,
        )

        result = await node.execute(base_state)

        # LLM succeeded
        mock_llm.call_at.assert_awaited_once()
        # graph_writer attempted but failed
        failing_graph_writer.merge_narrative.assert_awaited_once()
        # narrative should NOT be in state (persistence failed)
        assert "narrative" not in result
        # degraded_fields should contain "narrative"
        assert "narrative" in result.get("degraded_fields", [])
        # Pipeline should not be blocked


class TestNarrativeGeneratorNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_narrative_with_empty_entities(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that narrative generation works with empty entities list."""
        base_state["entities"] = []

        expected_output = NarrativeOutput(
            source_bias="中立",
            frame="经济影响",
            tone="客观",
            emphasis="市场反应",
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        # Should still call LLM with empty entities
        mock_llm.call_at.assert_awaited_once()
        payload = mock_llm.call_at.await_args.args[1]
        assert payload["entities"] == []
        # Narrative should be generated successfully
        assert result["narrative"]["source_bias"] == "中立"

    @pytest.mark.asyncio
    async def test_narrative_missing_article_id_skips_graph_write(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that missing article_id skips graph write but logs warning.

        Per Rule 12 (失败显性化), missing article_id means we cannot
        link NarrativeNode to EventNode (which uses article_id as id).
        The narrative data should still be in state (LLM succeeded) but
        marked as degraded because it's not persisted.
        """
        del base_state["article_id"]

        expected_output = NarrativeOutput(
            source_bias="中立",
            frame="经济影响",
            tone="客观",
            emphasis="市场反应",
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        # LLM succeeded
        mock_llm.call_at.assert_awaited_once()
        # graph_writer should NOT be called (no article_id to link)
        mock_graph_writer.merge_narrative.assert_not_called()
        # narrative should NOT be in state (not persisted)
        assert "narrative" not in result
        # degraded_fields should contain "narrative"
        assert "narrative" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_narrative_truncates_long_body(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that body is truncated via budget manager before LLM call."""
        long_body = "A" * 50000  # 50K chars
        base_state["cleaned"]["body"] = long_body

        # Track truncation call
        truncated_body = "B" * 10000
        mock_budget.truncate = MagicMock(return_value=truncated_body)

        expected_output = NarrativeOutput(
            source_bias="中立",
            frame="经济影响",
            tone="客观",
            emphasis="市场反应",
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = NarrativeGeneratorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        await node.execute(base_state)

        # Verify truncate was called with the long body and NARRATIVE_SYNTHESIS call point
        mock_budget.truncate.assert_called_once_with(long_body, CallPoint.NARRATIVE_SYNTHESIS)
        # Verify truncated body was passed to LLM
        payload = mock_llm.call_at.await_args.args[1]
        assert payload["body"] == truncated_body
