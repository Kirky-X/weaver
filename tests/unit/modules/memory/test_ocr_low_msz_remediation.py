# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LOW remediation behaviour tests: modules/memory batch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import OutputMode
from modules.memory.core.schema_node import SchemaNode
from modules.memory.retrieval.narrative_synthesizer import NarrativeSynthesizer


class TestSchemaNodeConfidenceValidation:
    """#228: frozen dataclass validates the documented 0.0-1.0 range."""

    def test_valid_confidence_constructs(self):
        node = SchemaNode(id="s1", event_type="t", pattern="p", confidence=0.5)
        assert node.confidence == 0.5

    @pytest.mark.parametrize("bad", [-0.1, 1.01, 2.0])
    def test_out_of_range_confidence_raises(self, bad):
        with pytest.raises(ValueError, match="confidence must be in"):
            SchemaNode(id="s2", event_type="t", pattern="p", confidence=bad)


class TestNarrativeAnswerKeyMissing:
    """#375: a missing/odd answer key must not stringify the whole payload."""

    @pytest.fixture
    def synthesizer(self):
        llm = MagicMock()
        llm.call_at = AsyncMock()
        return NarrativeSynthesizer(llm=llm)

    @pytest.mark.asyncio
    async def test_missing_answer_yields_empty_output(self, synthesizer):
        synthesizer._llm.call_at.return_value = {
            "context": "secret-context",
            "tokens_used": 42,
        }

        result = await synthesizer._synthesize_narrative(
            query="q",
            context_nodes=[{"id": "n1", "content": "c", "score": 1.0, "source": "s"}],
            include_provenance=False,
        )

        assert result.output == ""
        assert "secret-context" not in result.output
        assert result.total_tokens == 42

    @pytest.mark.asyncio
    async def test_non_string_answer_yields_empty_output(self, synthesizer):
        synthesizer._llm.call_at.return_value = {"answer": {"nested": True}}

        result = await synthesizer._synthesize_narrative(
            query="q", context_nodes=[], include_provenance=False
        )

        assert result.output == ""


class TestContextModeTokenMirrorRemoved:
    """#105/#81: total_tokens mirrors current_tokens; membership uses a set."""

    @pytest.mark.asyncio
    async def test_context_total_tokens_counts_included_nodes(self):
        synthesizer = NarrativeSynthesizer(llm=MagicMock())
        nodes = [{"id": f"n{i}", "content": "x" * 40, "score": 0.5} for i in range(5)]

        result = await synthesizer._synthesize_context(
            context_nodes=nodes, include_provenance=False
        )

        assert result.total_tokens == sum(len(n["content"]) // 4 for n in nodes)
        assert result.summarized_nodes == []


def test_cosine_similarity_is_public_api():
    """#229: traversal exposes cosine_similarity without the private alias."""
    from modules.memory.core import traversal

    assert hasattr(traversal, "cosine_similarity")
    assert not hasattr(traversal, "_cosine_similarity")
    assert traversal.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


class TestLadybugCausalEdgeUpdatedAt:
    """#233: Ladybug edge writes carry updated_at for change auditing."""

    @pytest.mark.asyncio
    async def test_query_sets_updated_at(self):
        from core.constants import DatabaseType
        from modules.memory.core.graph_types import CausalRelationType
        from modules.memory.graphs.causal import CausalGraphRepo

        pool = MagicMock()
        pool.database_type = DatabaseType.LADYBUG.value
        pool.execute_query = AsyncMock(return_value=[{"r": {}}])
        repo = CausalGraphRepo(pool=pool)

        created = await repo.add_causal_edge("s1", "t1", CausalRelationType.CAUSES, 0.9)

        assert created is True
        query = pool.execute_query.call_args[0][0]
        params = pool.execute_query.call_args[0][1]
        assert "r.updated_at = $updated_at" in query
        assert "updated_at" in params
