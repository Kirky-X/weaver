# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Shared fixtures for memory module tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import IntentType


@pytest.fixture
def mock_graph_pool():
    """Create mock Neo4j pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


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
def mock_llm():
    """Create mock LLM client."""
    client = MagicMock()
    client.call = AsyncMock(return_value='{"causal_edges": []}')
    return client


@pytest.fixture
def mock_cache_client():
    """Create mock Redis client."""
    redis = MagicMock()
    redis.lpush = AsyncMock(return_value=1)
    redis.rpop = AsyncMock(return_value=None)
    redis.llen = AsyncMock(return_value=0)
    return redis
