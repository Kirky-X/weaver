# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for processing NarrativeSchemaExtractorNode.

Covers the merged narrative+schema single-call node: success path, terminal/
merged skips, LLM failure degradation (both outputs), and independent
per-write graph persistence degradation (narrative write failure must not
block schema write, and vice versa).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import NarrativeSchemaOutput
from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.extraction.narrative_schema_extractor import (
    NarrativeSchemaExtractorNode,
)
from modules.processing.pipeline.state import PipelineState

_VALID_PATTERN = (
    '{"type":"object","properties":{"company":{"type":"string"},"amount":{"type":"string"}}}'
)


@pytest.fixture
def sample_raw():
    return RawArticle(
        url="https://example.com/tech-news",
        title="OpenAI and Microsoft Announce Partnership",
        body=(
            "OpenAI and Microsoft have announced a major partnership deal. "
            "The agreement involves GPT-4 integration into Azure services."
        ),
        source="tech_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_budget():
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_prompt_loader():
    loader = MagicMock()
    loader.get = MagicMock(return_value="Narrative+schema prompt")
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_graph_writer():
    writer = AsyncMock()
    writer.merge_narrative = AsyncMock(return_value="narrative-uuid-123")
    writer.merge_schema = AsyncMock(return_value="schema-uuid-789")
    return writer


@pytest.fixture
def base_state(sample_raw):
    state = PipelineState(raw=sample_raw)
    state["article_id"] = "article-uuid-456"
    state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
    state["entities"] = [{"canonical_name": "OpenAI", "type": "组织机构"}]
    return state


def _output() -> NarrativeSchemaOutput:
    return NarrativeSchemaOutput(
        source_bias="中立",
        frame="经济影响",
        tone="客观",
        emphasis="合作战略",
        event_type="合作",
        pattern=_VALID_PATTERN,
        confidence=0.9,
    )


class TestNarrativeSchemaBasic:
    """Basic functionality tests."""

    @pytest.mark.asyncio
    async def test_successful_both_persisted(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        """One LLM call writes both NarrativeNode and SchemaNode."""
        mock_llm.call_at = AsyncMock(return_value=_output())

        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)

        # Single LLM call with NARRATIVE_SCHEMA call point + merged output model
        mock_llm.call_at.assert_awaited_once()
        call_kwargs = mock_llm.call_at.await_args
        assert call_kwargs.args[0] == CallPoint.NARRATIVE_SCHEMA
        assert call_kwargs.kwargs["output_model"] is NarrativeSchemaOutput

        # Both graph writes invoked with correct fields
        mock_graph_writer.merge_narrative.assert_awaited_once()
        narr = mock_graph_writer.merge_narrative.await_args.kwargs
        assert narr["article_id"] == "article-uuid-456"
        assert narr["source_bias"] == "中立" and narr["frame"] == "经济影响"
        mock_graph_writer.merge_schema.assert_awaited_once()
        schema = mock_graph_writer.merge_schema.await_args.kwargs
        assert schema["event_type"] == "合作" and schema["confidence"] == 0.9

        # Both state keys set
        assert result["narrative"]["narrative_id"] == "narrative-uuid-123"
        assert result["schema"]["schema_id"] == "schema-uuid-789"
        assert result["schema"]["event_type"] == "合作"
        assert "narrative" not in result.get("degraded_fields", [])
        assert "schema" not in result.get("degraded_fields", [])
        assert result["prompt_versions"]["narrative_schema"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_skips_terminal(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        base_state["terminal"] = True
        mock_llm.call_at = AsyncMock(return_value=_output())
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)
        mock_llm.call_at.assert_not_awaited()
        assert "narrative" not in result and "schema" not in result

    @pytest.mark.asyncio
    async def test_skips_merged(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        base_state["is_merged"] = True
        mock_llm.call_at = AsyncMock(return_value=_output())
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        await node.execute(base_state)
        mock_llm.call_at.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_truncate_uses_narrative_schema_callpoint(
        self, mock_llm, mock_prompt_loader, mock_graph_writer, base_state
    ):
        budget = MagicMock()
        budget.truncate = MagicMock(side_effect=lambda text, call_point: text)
        mock_llm.call_at = AsyncMock(return_value=_output())
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        await node.execute(base_state)
        budget.truncate.assert_called_once_with(
            base_state["cleaned"]["body"], CallPoint.NARRATIVE_SCHEMA
        )


class TestNarrativeSchemaDegradation:
    """Failure-path degradation tests."""

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_both(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        mock_llm.call_at = AsyncMock(side_effect=AllProvidersFailedError("no providers"))
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)
        assert "narrative" in result["degraded_fields"]
        assert "schema" in result["degraded_fields"]
        mock_graph_writer.merge_narrative.assert_not_awaited()
        mock_graph_writer.merge_schema.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_llm_value_error_degrades_both(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        # ValueError covers pydantic ValidationError / bad JSON from LLM
        mock_llm.call_at = AsyncMock(side_effect=ValueError("bad output"))
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)
        assert "narrative" in result["degraded_fields"]
        assert "schema" in result["degraded_fields"]

    @pytest.mark.asyncio
    async def test_missing_article_id_degrades_narrative_writes_schema(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        base_state["article_id"] = None
        mock_llm.call_at = AsyncMock(return_value=_output())
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)
        # Narrative cannot link EventNode without article_id → degraded
        assert "narrative" in result["degraded_fields"]
        mock_graph_writer.merge_narrative.assert_not_awaited()
        # Schema is MERGEd by event_type, still written
        mock_graph_writer.merge_schema.assert_awaited_once()
        assert result["schema"]["event_type"] == "合作"

    @pytest.mark.asyncio
    async def test_narrative_persist_failure_does_not_block_schema(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        mock_graph_writer.merge_narrative = AsyncMock(side_effect=RuntimeError("graph down"))
        mock_llm.call_at = AsyncMock(return_value=_output())
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)
        assert "narrative" in result["degraded_fields"]
        assert "narrative" not in result  # not committed on write failure
        # Schema write proceeds independently
        mock_graph_writer.merge_schema.assert_awaited_once()
        assert result["schema"]["schema_id"] == "schema-uuid-789"

    @pytest.mark.asyncio
    async def test_schema_persist_failure_does_not_block_narrative(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        mock_graph_writer.merge_schema = AsyncMock(side_effect=RuntimeError("graph down"))
        mock_llm.call_at = AsyncMock(return_value=_output())
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)
        assert "schema" in result["degraded_fields"]
        # Narrative write proceeded independently
        mock_graph_writer.merge_narrative.assert_awaited_once()
        assert result["narrative"]["narrative_id"] == "narrative-uuid-123"

    @pytest.mark.asyncio
    async def test_prompt_version_recorded_even_on_failure(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_graph_writer, base_state
    ):
        mock_llm.call_at = AsyncMock(side_effect=CircuitOpenError("open"))
        node = NarrativeSchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )
        result = await node.execute(base_state)
        # try/finally guarantees prompt version recorded on degradation path
        assert result["prompt_versions"]["narrative_schema"] == "1.0.0"
