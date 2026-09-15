# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for intent router module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.intent.schemas import (
    IntentClassification,
    QueryIntent,
    TemporalSignal,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_why_routing():
    """Test WHY intent routes to local search."""
    from modules.knowledge.search.intent.router import IntentRouter

    mock_local = AsyncMock()
    mock_local.search.return_value = MagicMock(answer="local result", metadata={})
    mock_global = AsyncMock()
    mock_llm = AsyncMock()

    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
    )

    classification = IntentClassification(intent=QueryIntent.WHY, confidence=0.9)
    result = await router.route("为什么服务器会崩溃？", classification)

    mock_local.search.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_when_routing():
    """Test WHEN intent routes with temporal window."""
    from modules.knowledge.search.intent.router import IntentRouter

    mock_local = AsyncMock()
    mock_local.search.return_value = MagicMock(answer="when result", metadata={})
    mock_global = AsyncMock()
    mock_llm = AsyncMock()

    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
    )

    temporal_signal = TemporalSignal(
        expression="yesterday",
        anchor_type="relative",
        resolved_timestamp=None,
    )
    classification = IntentClassification(
        intent=QueryIntent.WHEN,
        confidence=0.9,
        temporal_signals=[temporal_signal],
    )

    result = await router.route("昨天发生了什么？", classification)
    mock_local.search.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_entity_routing():
    """Test ENTITY intent routes with entity filtering."""
    from modules.knowledge.search.intent.router import IntentRouter

    mock_local = AsyncMock()
    mock_local.search.return_value = MagicMock(answer="entity result", metadata={})
    mock_global = AsyncMock()
    mock_llm = AsyncMock()

    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
    )

    classification = IntentClassification(
        intent=QueryIntent.ENTITY,
        entity_signals=["Neo4j"],
        confidence=0.8,
    )

    result = await router.route("Neo4j是什么？", classification)
    mock_local.search.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_multi_hop_routing():
    """Test MULTI_HOP intent routes to global search with deeper level."""
    from modules.knowledge.search.intent.router import IntentRouter

    mock_local = AsyncMock()
    mock_global = AsyncMock()
    mock_global.search.return_value = MagicMock(answer="multi_hop result", metadata={})
    mock_llm = AsyncMock()

    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
    )

    classification = IntentClassification(intent=QueryIntent.MULTI_HOP, confidence=0.85)
    result = await router.route("GraphRAG和MAGMA有什么区别？", classification)

    mock_global.search.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_open_routing():
    """Test OPEN intent routes to global search."""
    from modules.knowledge.search.intent.router import IntentRouter

    mock_local = AsyncMock()
    mock_global = AsyncMock()
    mock_global.search.return_value = MagicMock(answer="open result", metadata={})
    mock_llm = AsyncMock()

    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
    )

    classification = IntentClassification(intent=QueryIntent.OPEN, confidence=0.7)
    result = await router.route("关于知识图谱的技术", classification)

    mock_global.search.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_fallback_on_error():
    """Test router falls back when search fails."""
    from modules.knowledge.search.intent.router import IntentRouter

    mock_local = AsyncMock()
    mock_local.search.side_effect = Exception("search failed")
    mock_global = AsyncMock()
    mock_llm = AsyncMock()

    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
    )

    classification = IntentClassification(intent=QueryIntent.WHY, confidence=0.0)
    result = await router.route("test query", classification)

    # Should return fallback dict
    assert isinstance(result, dict)
    assert "error" in result.get("metadata", {})


class TestFallbackModeConfig:
    """Regression: unknown-intent fallback must honour the configured
    fallback_mode instead of always routing to global."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode,local_calls,global_calls", [("local", 1, 0), ("global", 0, 1)])
    async def test_unknown_intent_uses_configured_fallback_mode(
        self, mode, local_calls, global_calls
    ):
        from modules.knowledge.search.intent.router import IntentRouter, RoutingConfig

        mock_local = AsyncMock()
        mock_local.search.return_value = MagicMock(metadata={})
        mock_global = AsyncMock()
        mock_global.search.return_value = MagicMock(metadata={})

        router = IntentRouter(
            local_engine=mock_local,
            global_engine=mock_global,
            config=RoutingConfig(fallback_mode=mode),
        )

        # All QueryIntent enum members are mapped, so simulate an
        # unmapped intent via a mock carrying a .value attribute.
        unknown_intent = MagicMock(value="totally-unknown")
        classification = IntentClassification(intent=unknown_intent, confidence=0.5)
        await router.route("test query", classification)

        assert mock_local.search.call_count == local_calls
        assert mock_global.search.call_count == global_calls


class TestWhenUsesTemporalSignals:
    """Regression: _search_when must differentiate from _search_why by
    consuming classification.temporal_signals."""

    @pytest.mark.asyncio
    async def test_when_search_anchors_query_with_temporal_expressions(self):
        from modules.knowledge.search.intent.router import IntentRouter

        mock_local = AsyncMock()
        mock_local.search.return_value = MagicMock(metadata={})
        mock_global = AsyncMock()

        router = IntentRouter(
            local_engine=mock_local,
            global_engine=mock_global,
        )

        classification = IntentClassification(
            intent=QueryIntent.WHEN,
            confidence=0.9,
            temporal_signals=[
                TemporalSignal(expression="yesterday", anchor_type="relative"),
                TemporalSignal(expression="last week", anchor_type="relative"),
            ],
        )
        await router.route("发生了什么", classification)

        call_kwargs = mock_local.search.call_args.kwargs
        assert "时间限定：yesterday、last week" in call_kwargs["query"]

    @pytest.mark.asyncio
    async def test_when_search_without_signals_keeps_query_intact(self):
        from modules.knowledge.search.intent.router import IntentRouter

        mock_local = AsyncMock()
        mock_local.search.return_value = MagicMock(metadata={})
        mock_global = AsyncMock()

        router = IntentRouter(
            local_engine=mock_local,
            global_engine=mock_global,
        )

        classification = IntentClassification(intent=QueryIntent.WHEN, confidence=0.9)
        await router.route("发生了什么", classification)

        call_kwargs = mock_local.search.call_args.kwargs
        assert call_kwargs["query"] == "发生了什么"
