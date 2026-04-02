# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for AdaptiveSearchEngine."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import IntentType
from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine


@pytest.fixture
def mock_temporal_repo():
    """Create mock temporal repository."""
    repo = MagicMock()
    repo.get_temporal_chain = AsyncMock(return_value=[])
    repo.get_neighbors = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_causal_repo():
    """Create mock causal repository."""
    repo = MagicMock()
    repo.get_causes = AsyncMock(return_value=[])
    repo.get_effects = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_embedding_service():
    """Create mock embedding service."""
    service = MagicMock()
    service.embed = AsyncMock(return_value=[0.1] * 384)
    return service


@pytest.fixture
def mock_intent_classifier():
    """Create mock intent classifier."""
    classifier = MagicMock()
    classification = MagicMock()
    classification.intent = IntentType.OPEN
    classifier.classify = AsyncMock(return_value=classification)
    return classifier


@pytest.fixture
def engine(
    mock_temporal_repo,
    mock_causal_repo,
    mock_embedding_service,
    mock_intent_classifier,
):
    """Create AdaptiveSearchEngine with mocks."""
    return AdaptiveSearchEngine(
        temporal_repo=mock_temporal_repo,
        causal_repo=mock_causal_repo,
        embedding_service=mock_embedding_service,
        intent_classifier=mock_intent_classifier,
        max_depth=3,
        beam_width=5,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_classifies_intent(engine, mock_intent_classifier, mock_temporal_repo):
    """Test that search classifies query intent."""
    mock_temporal_repo.get_temporal_chain.return_value = [{"id": "event-001", "content": "Test"}]

    await engine.search("Why did this happen?")

    mock_intent_classifier.classify.assert_called_once_with("Why did this happen?")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_computes_embedding(engine, mock_embedding_service, mock_temporal_repo):
    """Test that search computes query embedding."""
    mock_temporal_repo.get_temporal_chain.return_value = [{"id": "event-001", "content": "Test"}]

    await engine.search("Test query")

    mock_embedding_service.embed.assert_called_once_with("Test query")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_returns_empty_without_anchors(engine, mock_temporal_repo):
    """Test search returns empty when no anchors found."""
    mock_temporal_repo.get_temporal_chain.return_value = []

    results = await engine.search("Test query")

    assert results == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_with_provided_anchors(engine, mock_temporal_repo, mock_intent_classifier):
    """Test search with pre-provided anchors."""
    mock_temporal_repo.get_temporal_chain.return_value = [
        {"id": "event-001", "content": "Test event"}
    ]

    results = await engine.search(
        query="Test",
        anchors=["event-001"],
        intent=IntentType.WHY,
    )

    # Should not call intent classifier when intent is provided
    mock_intent_classifier.classify.assert_not_called()
    assert len(results) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_why_intent_gets_causal_neighbors(
    engine, mock_temporal_repo, mock_causal_repo
):
    """Test WHY queries retrieve causal neighbors."""
    mock_temporal_repo.get_temporal_chain.return_value = [
        {"id": "event-001", "content": "Test", "timestamp": "2026-04-02"}
    ]
    mock_temporal_repo.get_neighbors.return_value = []
    mock_causal_repo.get_causes.return_value = [{"id": "cause-001", "content": "Cause"}]
    mock_causal_repo.get_effects.return_value = []

    results = await engine.search(
        query="Why did this happen?",
        anchors=["event-001"],
        intent=IntentType.WHY,
    )

    mock_causal_repo.get_causes.assert_called()
    mock_causal_repo.get_effects.assert_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_beam_search_respects_depth_limit(engine, mock_temporal_repo, mock_embedding_service):
    """Test beam search respects max depth."""
    call_count = 0

    async def count_calls(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return []

    mock_temporal_repo.get_neighbors = count_calls
    mock_temporal_repo.get_temporal_chain.return_value = [{"id": "event-001", "content": "Test"}]
    mock_embedding_service.embed = AsyncMock(return_value=[0.1] * 384)

    await engine.search("Test", anchors=["event-001"], intent=IntentType.OPEN)

    # Should not exceed max_depth iterations
    assert call_count <= engine._max_depth + 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_handles_errors_gracefully(engine, mock_intent_classifier):
    """Test search handles errors gracefully."""
    mock_intent_classifier.classify.side_effect = Exception("Classification error")

    results = await engine.search("Test query")

    assert results == []


@pytest.mark.unit
def test_estimate_tokens(engine):
    """Test token estimation."""
    results = [
        {"content": "This is a test with about 40 characters total"},
        {"content": "Another test string"},
    ]

    tokens = engine._estimate_tokens(results)

    assert tokens > 0
    assert isinstance(tokens, int)
