# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for NarrativeSynthesizer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import OutputMode
from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer


class TestNarrativeSynthesizerContextMode:
    """Tests for CONTEXT output mode."""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.fixture
    def context_nodes(self):
        return [
            {
                "id": "node-1",
                "content": "First piece of context",
                "score": 0.9,
                "source": "news",
            },
            {
                "id": "node-2",
                "content": "Second piece of context",
                "score": 0.7,
                "source": "tech",
            },
        ]

    @pytest.mark.asyncio
    async def test_context_mode_basic(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.CONTEXT,
        )

        assert result.mode == OutputMode.CONTEXT
        assert result.node_count == 2
        assert "First piece of context" in result.output
        assert "Second piece of context" in result.output

    @pytest.mark.asyncio
    async def test_context_mode_includes_scores(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.CONTEXT,
        )

        assert "Score: 0.90" in result.output
        assert "Score: 0.70" in result.output

    @pytest.mark.asyncio
    async def test_context_mode_includes_provenance(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.CONTEXT,
            include_provenance=True,
        )

        assert "Source: news" in result.output
        assert "Source: tech" in result.output

    @pytest.mark.asyncio
    async def test_context_mode_excludes_provenance(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.CONTEXT,
            include_provenance=False,
        )

        assert "Source:" not in result.output

    @pytest.mark.asyncio
    async def test_context_mode_included_nodes(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.CONTEXT,
        )

        assert "node-1" in result.included_nodes
        assert "node-2" in result.included_nodes
        assert result.summarized_nodes == []

    @pytest.mark.asyncio
    async def test_context_mode_respects_token_budget(self, mock_llm):
        large_content = "A" * 4000  # ~1000 tokens each
        nodes = [
            {"id": f"node-{i}", "content": large_content, "score": 0.9, "source": "test"}
            for i in range(10)
        ]

        synthesizer = NarrativeSynthesizer(llm=mock_llm, max_context_tokens=2000)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=nodes,
            mode=OutputMode.CONTEXT,
        )

        assert result.node_count < 10
        assert len(result.summarized_nodes) > 0

    @pytest.mark.asyncio
    async def test_context_mode_does_not_call_llm(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.CONTEXT,
        )

        mock_llm.call_at.assert_not_called()


class TestNarrativeSynthesizerNarrativeMode:
    """Tests for NARRATIVE output mode."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.call_at = AsyncMock(
            return_value={
                "answer": "This is a synthesized narrative answer.",
                "tokens_used": 150,
            }
        )
        return llm

    @pytest.fixture
    def context_nodes(self):
        return [
            {
                "id": "node-1",
                "content": "First piece of context",
                "score": 0.9,
                "source": "news",
            },
            {
                "id": "node-2",
                "content": "Second piece of context",
                "score": 0.7,
                "source": "tech",
            },
        ]

    @pytest.mark.asyncio
    async def test_narrative_mode_basic(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
        )

        assert result.mode == OutputMode.NARRATIVE
        assert result.output == "This is a synthesized narrative answer."
        assert result.node_count == 2

    @pytest.mark.asyncio
    async def test_narrative_mode_calls_llm(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
        )

        mock_llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_narrative_mode_llm_payload(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        await synthesizer.synthesize(
            query="What happened?",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
        )

        call_kwargs = mock_llm.call_at.call_args
        payload = call_kwargs.kwargs["payload"]
        assert payload["query"] == "What happened?"
        assert "First piece of context" in payload["context"]
        assert payload["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_narrative_mode_with_provenance(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
            include_provenance=True,
        )

        payload = mock_llm.call_at.call_args.kwargs["payload"]
        assert "[news]" in payload["context"]

    @pytest.mark.asyncio
    async def test_narrative_mode_without_provenance(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
            include_provenance=False,
        )

        payload = mock_llm.call_at.call_args.kwargs["payload"]
        assert "[news]" not in payload["context"]

    @pytest.mark.asyncio
    async def test_narrative_mode_llm_returns_string(self, mock_llm, context_nodes):
        mock_llm.call_at = AsyncMock(return_value="Raw string narrative")

        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
        )

        assert result.output == "Raw string narrative"

    @pytest.mark.asyncio
    async def test_narrative_mode_llm_error_fallback(self, mock_llm, context_nodes):
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM error"))

        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
        )

        assert "First piece of context" in result.output
        assert result.mode == OutputMode.NARRATIVE

    @pytest.mark.asyncio
    async def test_narrative_mode_custom_max_tokens(self, mock_llm, context_nodes):
        synthesizer = NarrativeSynthesizer(llm=mock_llm, narrative_max_tokens=512)

        await synthesizer.synthesize(
            query="test query",
            context_nodes=context_nodes,
            mode=OutputMode.NARRATIVE,
        )

        payload = mock_llm.call_at.call_args.kwargs["payload"]
        assert payload["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_narrative_mode_respects_token_budget(self, mock_llm):
        large_content = "A" * 4000
        nodes = [{"id": f"node-{i}", "content": large_content, "source": "test"} for i in range(10)]

        synthesizer = NarrativeSynthesizer(llm=mock_llm, max_context_tokens=2000)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=nodes,
            mode=OutputMode.NARRATIVE,
        )

        assert result.node_count < 10
        assert len(result.summarized_nodes) > 0


class TestNarrativeSynthesizerEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def mock_llm(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_empty_context_nodes(self, mock_llm):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=[],
            mode=OutputMode.CONTEXT,
        )

        assert result.node_count == 0
        assert "No relevant" in result.output

    @pytest.mark.asyncio
    async def test_empty_context_nodes_narrative(self, mock_llm):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=[],
            mode=OutputMode.NARRATIVE,
        )

        assert result.node_count == 0
        assert "No relevant" in result.output

    @pytest.mark.asyncio
    async def test_unknown_output_mode(self, mock_llm):
        synthesizer = NarrativeSynthesizer(llm=mock_llm)
        unknown_mode = MagicMock(value="UNKNOWN")

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=[{"id": "1", "content": "test"}],
            mode=unknown_mode,
        )

        assert "Unknown output mode" in result.output

    @pytest.mark.asyncio
    async def test_context_node_without_source(self, mock_llm):
        nodes = [{"id": "1", "content": "No source", "score": 0.9}]

        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=nodes,
            mode=OutputMode.CONTEXT,
            include_provenance=True,
        )

        assert "No source" in result.output

    @pytest.mark.asyncio
    async def test_context_node_without_id(self, mock_llm):
        nodes = [{"content": "No ID", "score": 0.9}]

        synthesizer = NarrativeSynthesizer(llm=mock_llm)

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=nodes,
            mode=OutputMode.CONTEXT,
        )

        assert "unknown" in result.included_nodes

    @pytest.mark.asyncio
    async def test_synthesis_exception_handling(self, mock_llm):
        """Test that exception in synthesize() is caught and returns error message."""
        # Force an exception in the synthesize method itself
        synthesizer = NarrativeSynthesizer(llm=mock_llm)
        # Patch _synthesize_context to raise an exception
        synthesizer._synthesize_context = AsyncMock(side_effect=RuntimeError("unexpected"))

        result = await synthesizer.synthesize(
            query="test query",
            context_nodes=[{"id": "1", "content": "test"}],
            mode=OutputMode.CONTEXT,
        )

        assert "Synthesis failed" in result.output
