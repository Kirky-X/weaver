# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for search endpoint integration with intent-aware routing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.search.intent.router import IntentRouter, RoutingConfig
from modules.knowledge.search.intent.schemas import IntentClassification, QueryIntent


@pytest.mark.integration
@pytest.mark.asyncio
async def test_intent_routing_to_local():
    """Test that WHY intent routes to local search engine."""
    mock_local = AsyncMock()
    mock_local.search.return_value = MagicMock(answer="why result", metadata={})
    mock_global = AsyncMock()
    mock_llm = AsyncMock()

    config = RoutingConfig(enable_intent_routing=True, fallback_mode="local")
    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
        config=config,
    )

    classification = IntentClassification(intent=QueryIntent.WHY, confidence=0.9)
    result = await router.route("为什么服务器会崩溃？", classification)

    mock_local.search.assert_called_once()
    assert result.metadata.get("intent") == "why"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_intent_routing_to_global():
    """Test that OPEN intent routes to global search engine."""
    mock_local = AsyncMock()
    mock_global = AsyncMock()
    mock_global.search.return_value = MagicMock(answer="open result", metadata={})
    mock_llm = AsyncMock()

    config = RoutingConfig(enable_intent_routing=True, fallback_mode="local")
    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
        config=config,
    )

    classification = IntentClassification(intent=QueryIntent.OPEN, confidence=0.7)
    result = await router.route("关于知识图谱的技术", classification)

    mock_global.search.assert_called_once()
    assert result.metadata.get("intent") == "open"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_intent_routing_error_fallback():
    """Test that routing error returns fallback dict."""
    mock_local = AsyncMock()
    mock_local.search.side_effect = Exception("search engine crashed")
    mock_global = AsyncMock()
    mock_llm = AsyncMock()

    config = RoutingConfig(enable_intent_routing=True, fallback_mode="local")
    router = IntentRouter(
        local_engine=mock_local,
        global_engine=mock_global,
        vector_repo=None,
        hybrid_engine=None,
        llm=mock_llm,
        config=config,
    )

    classification = IntentClassification(intent=QueryIntent.WHY, confidence=0.9)
    result = await router.route("test query", classification)

    assert isinstance(result, dict)
    assert "error" in result.get("metadata", {})
