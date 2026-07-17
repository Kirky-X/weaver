# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for processing SchemaExtractorNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import SchemaExtractorOutput
from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.extraction.schema_extractor import (
    SchemaExtractorNode,
)
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return RawArticle(
        url="https://example.com/funding-news",
        title="Company X Raises $500M in Series C Funding",
        body=(
            "Company X announced today it has raised $500 million in a Series C "
            "funding round led by Investor Y. The company plans to use the capital "
            "to expand into Asian markets and accelerate AI research."
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
    loader.get = MagicMock(return_value="Schema extraction prompt")
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_graph_writer():
    """Mock GraphWriter for SchemaNode persistence."""
    writer = AsyncMock()
    writer.merge_schema = AsyncMock(return_value="schema-融资")
    return writer


@pytest.fixture
def base_state(sample_raw):
    """Create base pipeline state with cleaned content and article_id."""
    state = PipelineState(raw=sample_raw)
    state["article_id"] = "article-uuid-789"
    state["cleaned"] = {
        "title": sample_raw.title,
        "body": sample_raw.body,
    }
    state["entities"] = [
        {"canonical_name": "Company X", "type": "组织机构"},
        {"canonical_name": "Investor Y", "type": "组织机构"},
    ]
    return state


class TestSchemaExtractorNodeBasic:
    """Basic functionality tests for SchemaExtractorNode."""

    @pytest.mark.asyncio
    async def test_schema_extraction_successful(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test successful schema extraction with event_type/pattern/confidence."""
        expected_pattern = (
            '{"type":"object","properties":{'
            '"company":{"type":"string"},'
            '"amount":{"type":"string"},'
            '"round":{"type":"string"},'
            '"investors":{"type":"array"}'
            "}}"
        )
        expected_output = SchemaExtractorOutput(
            event_type="融资",
            pattern=expected_pattern,
            confidence=0.92,
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        # Verify LLM called with correct call_point and payload
        mock_llm.call_at.assert_awaited_once()
        call_kwargs = mock_llm.call_at.await_args
        assert call_kwargs.args[0] == CallPoint.SCHEMA_EXTRACTION
        payload = call_kwargs.args[1]
        assert payload["title"] == base_state["cleaned"]["title"]
        assert payload["body"] == base_state["cleaned"]["body"]
        assert "entities" in payload
        assert call_kwargs.kwargs["output_model"] == SchemaExtractorOutput

        # Verify graph_writer.merge_schema called with correct args
        mock_graph_writer.merge_schema.assert_awaited_once()
        schema_args = mock_graph_writer.merge_schema.await_args
        assert schema_args.kwargs["event_type"] == "融资"
        assert schema_args.kwargs["pattern"] == expected_pattern
        assert schema_args.kwargs["confidence"] == pytest.approx(0.92)

        # Verify state updated with schema data
        assert "schema" in result
        assert result["schema"]["event_type"] == "融资"
        assert result["schema"]["pattern"] == expected_pattern
        assert result["schema"]["confidence"] == pytest.approx(0.92)
        assert result["schema"]["schema_id"] == "schema-融资"

        # Verify prompt version recorded
        assert result.get("prompt_versions", {}).get("schema_extraction") == "1.0.0"

        # Verify no degraded_fields added on success
        assert "schema" not in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_schema_skips_terminal_state(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that terminal articles are skipped."""
        base_state["terminal"] = True

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_llm.call_at.assert_not_called()
        mock_graph_writer.merge_schema.assert_not_called()
        assert "schema" not in result

    @pytest.mark.asyncio
    async def test_schema_skips_merged_state(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that merged articles are skipped."""
        base_state["is_merged"] = True

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_llm.call_at.assert_not_called()
        mock_graph_writer.merge_schema.assert_not_called()
        assert "schema" not in result


class TestSchemaExtractorNodeDegradation:
    """Failure handling and degradation tests."""

    @pytest.mark.asyncio
    async def test_schema_llm_all_providers_failed_degrades(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that AllProvidersFailedError marks schema as degraded."""
        mock_llm.call_at = AsyncMock(side_effect=AllProvidersFailedError("all providers failed"))

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_llm.call_at.assert_awaited_once()
        mock_graph_writer.merge_schema.assert_not_called()
        assert "schema" not in result
        assert "schema" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_schema_llm_circuit_open_degrades(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that CircuitOpenError marks schema as degraded."""
        mock_llm.call_at = AsyncMock(side_effect=CircuitOpenError("circuit open"))

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_graph_writer.merge_schema.assert_not_called()
        assert "schema" not in result
        assert "schema" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_schema_llm_value_error_degrades(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that ValueError (e.g., parse failure) marks schema as degraded."""
        mock_llm.call_at = AsyncMock(side_effect=ValueError("invalid JSON response"))

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_graph_writer.merge_schema.assert_not_called()
        assert "schema" not in result
        assert "schema" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_schema_graph_writer_failure_does_not_block_pipeline(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        base_state,
    ):
        """Test that graph_writer failure is logged but does not block pipeline.

        LLM succeeded so schema data is available, but persistence failed.
        Per Rule 12 (失败显性化), this should be logged as warning and
        schema marked as degraded (because the data isn't persisted).
        """
        expected_pattern = '{"type":"object","properties":{"company":{"type":"string"}}}'
        expected_output = SchemaExtractorOutput(
            event_type="融资",
            pattern=expected_pattern,
            confidence=0.85,
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        failing_graph_writer = AsyncMock()
        failing_graph_writer.merge_schema = AsyncMock(
            side_effect=RuntimeError("graph db connection lost")
        )

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=failing_graph_writer,
        )

        result = await node.execute(base_state)

        mock_llm.call_at.assert_awaited_once()
        failing_graph_writer.merge_schema.assert_awaited_once()
        assert "schema" not in result
        assert "schema" in result.get("degraded_fields", [])


class TestSchemaExtractorNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_schema_with_empty_entities(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that schema extraction works with empty entities list."""
        base_state["entities"] = []

        expected_output = SchemaExtractorOutput(
            event_type="政策发布",
            pattern='{"type":"object","properties":{"title":{"type":"string"}}}',
            confidence=0.78,
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        result = await node.execute(base_state)

        mock_llm.call_at.assert_awaited_once()
        payload = mock_llm.call_at.await_args.args[1]
        assert payload["entities"] == []
        assert result["schema"]["event_type"] == "政策发布"

    @pytest.mark.asyncio
    async def test_schema_truncates_long_body(
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

        truncated_body = "B" * 10000
        mock_budget.truncate = MagicMock(return_value=truncated_body)

        expected_output = SchemaExtractorOutput(
            event_type="融资",
            pattern='{"type":"object","properties":{}}',
            confidence=0.7,
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        await node.execute(base_state)

        mock_budget.truncate.assert_called_once_with(long_body, CallPoint.SCHEMA_EXTRACTION)
        payload = mock_llm.call_at.await_args.args[1]
        assert payload["body"] == truncated_body

    @pytest.mark.asyncio
    async def test_schema_same_event_type_calls_merge_schema_idempotently(
        self,
        mock_llm,
        mock_budget,
        mock_prompt_loader,
        mock_graph_writer,
        base_state,
    ):
        """Test that merge_schema is called with event_type for idempotent MERGE.

        SchemaNode is MERGEd by event_type — multiple articles with the same
        event_type should produce one SchemaNode. The dedup behavior is
        enforced by GraphWriter.merge_schema (Cypher MERGE + unique constraint).
        This test verifies the node passes event_type correctly so that
        GraphWriter can dedup.
        """
        expected_output = SchemaExtractorOutput(
            event_type="融资",
            pattern='{"type":"object","properties":{}}',
            confidence=0.9,
        )
        mock_llm.call_at = AsyncMock(return_value=expected_output)

        node = SchemaExtractorNode(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            graph_writer=mock_graph_writer,
        )

        await node.execute(base_state)

        # merge_schema called with event_type as the MERGE key
        schema_args = mock_graph_writer.merge_schema.await_args
        assert schema_args.kwargs["event_type"] == "融资"
        # Return value is the SchemaNode id (stable across re-runs)
        assert mock_graph_writer.merge_schema.return_value == "schema-融资"
