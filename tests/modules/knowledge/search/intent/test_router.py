# Copyright (c) 2026 KirkyX. All Rights Reserved
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
